import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from pipeline import layers, musicbrainz
from tests.pipeline_helpers import MBID_A, FakeMusicBrainz, mb_artist, search_page


def rows(db, sql: str) -> list[tuple]:
    return [tuple(r) for r in db.execute(text(sql))]


@pytest.fixture
def plays(factory):
    rock, jazz = factory.genre("rock"), factory.genre("jazz")
    bowie = factory.artist("Bowie", genres=[rock, jazz])
    nobody = factory.artist("Nobody Plays Me")
    heroes = factory.track(bowie, "Heroes", duration_ms=300_000)
    factory.track(nobody, "Unplayed")
    alice, bob = factory.listener("alice"), factory.listener("bob")
    factory.plays(
        alice,
        heroes,
        datetime(2026, 1, 1, 10, tzinfo=UTC),
        datetime(2026, 1, 1, 23, 30, tzinfo=UTC),
        # 01:00 at UTC+02:00 is still Jan 1 (23:00) in UTC (ADR 0003).
        datetime.fromisoformat("2026-01-02T01:00:00+02:00"),
    )
    factory.plays(bob, heroes, datetime(2026, 1, 2, 9, tzinfo=UTC))
    return {"bowie": bowie, "nobody": nobody, "alice": alice, "bob": bob}


def test_daily_listener_activity(engine, db, plays):
    layers.build_staging(engine)
    layers.build_marts(engine)

    result = rows(
        db,
        "SELECT day::text, listener_id, plays, unique_tracks, listening_ms "
        "FROM marts.daily_listener_activity ORDER BY day, listener_id",
    )

    alice, bob = plays["alice"].id, plays["bob"].id
    assert result == [("2026-01-01", alice, 3, 1, 900_000), ("2026-01-02", bob, 1, 1, 300_000)]


def test_daily_genre_plays_count_every_genre(engine, db, plays):
    layers.build_staging(engine)
    layers.build_marts(engine)

    result = rows(
        db,
        "SELECT day::text, genre_name, plays, unique_listeners "
        "FROM marts.daily_genre_plays ORDER BY day, genre_name",
    )

    assert result == [
        ("2026-01-01", "jazz", 3, 1),
        ("2026-01-01", "rock", 3, 1),
        ("2026-01-02", "jazz", 1, 1),
        ("2026-01-02", "rock", 1, 1),
    ]


def test_artist_popularity_includes_unplayed_artists(engine, db, plays):
    layers.build_staging(engine)
    layers.build_marts(engine)

    result = rows(
        db,
        "SELECT artist_name, total_plays, unique_listeners "
        "FROM marts.artist_popularity ORDER BY artist_id",
    )

    assert result == [("Bowie", 4, 2), ("Nobody Plays Me", 0, 0)]


def test_artist_popularity_is_enriched_from_musicbrainz(engine, db, factory):
    artist = factory.artist("Miles")
    artist.mbid = MBID_A
    db.commit()
    fake = FakeMusicBrainz({("jazz", 0): search_page([mb_artist(MBID_A, "Miles", country="US")])})
    musicbrainz.extract_artists_by_tag(engine, fake.client(), ["jazz"], 25, run_id="t")

    layers.build_staging(engine)
    layers.build_marts(engine)

    assert rows(
        db, "SELECT musicbrainz_country, musicbrainz_type FROM marts.artist_popularity"
    ) == [("US", "Person")]


def test_staging_keeps_newest_musicbrainz_version(engine, db):
    old = search_page([mb_artist(MBID_A, "Old Name", tags=[("Jazz ", 2), ("bebop", -1)])])
    new = search_page([mb_artist(MBID_A, "New Name", tags=[("Jazz", 5)])])
    for payload in (old, new):
        db.execute(
            text(
                "INSERT INTO raw.musicbrainz_artist_search "
                "(run_id, tag, page_offset, request_url, payload, loaded_at) "
                "VALUES ('t', 'jazz', 0, 'u', CAST(:p AS jsonb), "
                "now() - make_interval(days => :age))"
            ),
            {"p": json.dumps(payload), "age": 1 if payload is old else 0},
        )
    db.commit()

    layers.build_staging(engine)

    assert rows(db, "SELECT artist_name FROM staging.musicbrainz_artists") == [("New Name",)]
    assert rows(db, "SELECT tag, votes FROM staging.musicbrainz_artist_tags") == [("jazz", 5)]


def test_musicbrainz_tags_are_normalised(engine, db):
    page = search_page([mb_artist(MBID_A, "A", tags=[(" Hip Hop ", 2), ("bebop", -1)])])
    fake = FakeMusicBrainz({("jazz", 0): page})
    musicbrainz.extract_artists_by_tag(engine, fake.client(), ["jazz"], 25, run_id="t")

    layers.build_staging(engine)

    assert rows(db, "SELECT tag, votes FROM staging.musicbrainz_artist_tags ORDER BY tag") == [
        ("bebop", -1),
        ("hip hop", 2),
    ]


def test_failed_build_keeps_previous_marts(engine, db, plays, tmp_path, monkeypatch):
    layers.build_staging(engine)
    layers.build_marts(engine)
    broken = tmp_path / "marts.sql"
    broken.write_text(
        "DROP SCHEMA marts CASCADE; CREATE SCHEMA marts; SELECT * FROM table_that_does_not_exist;"
    )
    monkeypatch.setattr(layers, "SQL_DIR", tmp_path)

    with pytest.raises(Exception, match="table_that_does_not_exist"):
        layers.build_marts(engine)

    # The DROP was rolled back together with the failing statement.
    assert rows(db, "SELECT count(*) FROM marts.artist_popularity") == [(2,)]
