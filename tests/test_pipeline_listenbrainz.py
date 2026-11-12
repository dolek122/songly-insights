from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import text

from pipeline import layers, listenbrainz, musicbrainz, quality
from tests.pipeline_helpers import (
    MBID_A,
    MBID_B,
    REC_1,
    REC_2,
    REC_3,
    FakeListenBrainz,
    FakeMusicBrainz,
    lb_listen,
    mb_artist,
    mb_recording,
    recordings_page,
    search_page,
)

T0 = 1_767_225_600  # 2026-01-01T00:00:00Z as a Unix timestamp


def rows(db, sql: str, **params) -> list[tuple]:
    return [tuple(r) for r in db.execute(text(sql), params)]


def extract(engine, fake: FakeListenBrainz, max_listens: int = 100, page_size: int = 100):
    layers.build_staging(engine)  # the watermark is read from staging
    return listenbrainz.extract_listens(
        engine, fake.client(), list(fake.listens), max_listens, run_id="t", page_size=page_size
    )


# --- client ---------------------------------------------------------------------------------


def test_listens_request():
    client = FakeListenBrainz({}).client()

    first = client.listens_request("ana bo", count=100, max_ts=None)
    older = client.listens_request("ana", count=50, max_ts=T0)

    assert "/user/ana%20bo/listens" in str(first.url)  # the space is encoded
    assert "max_ts" not in first.url.params
    assert (older.url.params["count"], older.url.params["max_ts"]) == ("50", str(T0))


def test_unknown_user_raises():
    client = FakeListenBrainz({}).client()
    with pytest.raises(httpx.HTTPStatusError):
        client.send(client.listens_request("nobody", 10, None))


# --- extract --------------------------------------------------------------------------------


def test_extract_pages_back_in_time(engine, db):
    fake = FakeListenBrainz({"ana": [lb_listen(T0 + i, REC_1) for i in range(5)]})

    result = extract(engine, fake, page_size=2)

    # Pages: [4, 3], [2, 1], [0], [] -> each next page asks for listens older than the last.
    assert fake.max_ts_sent() == [None, str(T0 + 3), str(T0 + 1), str(T0)]
    assert (result.pages_downloaded, result.listens_downloaded) == (4, 5)
    assert rows(db, "SELECT count(*) FROM staging.listenbrainz_listens") == [(5,)]


def test_extract_stops_at_the_limit(engine):
    fake = FakeListenBrainz({"ana": [lb_listen(T0 + i, REC_1) for i in range(10)]})

    result = extract(engine, fake, max_listens=3, page_size=2)

    # 2 + 1 listens: the second page asks only for what is missing to reach the limit.
    assert result.listens_downloaded == 3
    assert [r.url.params["count"] for r in fake.requests] == ["2", "1"]


def test_extract_is_incremental(engine, db):
    fake = FakeListenBrainz({"ana": [lb_listen(T0 + i, REC_1) for i in range(4)]})
    extract(engine, fake, page_size=2)
    fake.listens["ana"] += [lb_listen(T0 + 10, REC_1), lb_listen(T0 + 11, REC_1)]
    fake.requests.clear()

    again = extract(engine, fake, page_size=2)

    # Watermark = T0+3. The first page [11, 10] is newer, the second [3, 2] reaches it: stop.
    assert fake.max_ts_sent() == [None, str(T0 + 10)]
    assert again.listens_downloaded == 4
    # The overlap (listens 3 and 2 downloaded twice) is removed in staging.
    assert rows(db, "SELECT count(*) FROM staging.listenbrainz_listens") == [(6,)]


# --- staging --------------------------------------------------------------------------------


def test_staging_parses_listens(engine, db):
    fake = FakeListenBrainz(
        {
            "ana": [
                lb_listen(T0, REC_1, MBID_A, "So What", "Miles", duration_ms=545_000),
                lb_listen(T0 + 1, REC_2, MBID_B, "Unmapped", "B", mapped=False),
                lb_listen(T0 + 2, "not-a-uuid", "also-bad", "Broken", "C", duration_ms=-5),
            ]
        }
    )
    extract(engine, fake)

    result = rows(
        db,
        "SELECT listened_at, recording_mbid::text, artist_mbid::text, track_name, "
        "artist_name, duration_ms FROM staging.listenbrainz_listens ORDER BY listened_at",
    )

    first_listen = datetime(2026, 1, 1, tzinfo=UTC)
    assert result[0] == (first_listen, REC_1, MBID_A, "So What", "Miles", 545_000)
    # mbids sent by the app are used when ListenBrainz has no mapping.
    assert result[1][1:3] == (REC_2, MBID_B)
    # Values that are not uuids or positive numbers become NULL instead of breaking the view.
    assert result[2][1:3] == (None, None)
    assert result[2][5] is None


# --- publish --------------------------------------------------------------------------------


def events(db) -> list[tuple]:
    return rows(
        db,
        """
        SELECT li.username, t.title, a.name, t.duration_ms, e.listened_at
        FROM listening_events e
        JOIN listeners li ON li.id = e.listener_id
        JOIN tracks t ON t.id = e.track_id
        JOIN artists a ON a.id = t.artist_id
        ORDER BY e.listened_at
        """,
    )


def test_publish_creates_listeners_tracks_and_events(engine, db):
    fake = FakeListenBrainz(
        {
            "ana": [
                lb_listen(T0, REC_1, MBID_A, "So What", "Miles", duration_ms=545_000),
                lb_listen(T0 + 60, REC_1, MBID_A, "So What", "Miles"),
                lb_listen(T0 + 120, None, None, "No mbid", "Somebody"),
            ]
        }
    )
    extract(engine, fake)

    result = listenbrainz.publish_listens(engine)

    t = datetime.fromtimestamp
    assert events(db) == [
        ("lb_ana", "So What", "Miles", 545_000, t(T0, UTC)),
        ("lb_ana", "So What", "Miles", 545_000, t(T0 + 60, UTC)),
    ]
    assert rows(db, "SELECT listenbrainz_user FROM listeners") == [("ana",)]
    assert (result.listeners_added, result.artists_added, result.tracks_added) == (1, 1, 1)
    assert result.events_added == 2
    # The listen without an mbid is not imported, but a warning reports it.
    results = quality.run_checks(engine, quality.STAGING_CHECKS)
    warnings = [r.check.name for r in results if not r.passed]
    assert warnings == ["listenbrainz_listens_have_recording_mbid"]


def test_publish_is_idempotent(engine, db):
    fake = FakeListenBrainz({"ana": [lb_listen(T0, REC_1, MBID_A, "So What", "Miles")]})
    extract(engine, fake)
    listenbrainz.publish_listens(engine)

    again = listenbrainz.publish_listens(engine)

    assert again == listenbrainz.PublishListensResult(0, 0, 0, 0)
    assert len(events(db)) == 1


def test_publish_reuses_musicbrainz_tracks(engine, db):
    # MusicBrainz knows the artist, the title and the length ...
    mb = FakeMusicBrainz(
        {("jazz", 0): search_page([mb_artist(MBID_A, "Miles Davis")])},
        recordings={(MBID_A, 0): recordings_page([mb_recording(REC_1, "So What", 545_000)])},
    )
    musicbrainz.extract_artists_by_tag(engine, mb.client(), ["jazz"], 5, run_id="t")
    layers.build_staging(engine)
    musicbrainz.extract_recordings(engine, mb.client(), 5, run_id="t")
    musicbrainz.publish_to_catalog(engine, ["jazz"])
    # ... and the listen spells them differently and has no length.
    extract(engine, FakeListenBrainz({"ana": [lb_listen(T0, REC_1, MBID_A, "so what", "MD")]}))

    result = listenbrainz.publish_listens(engine)

    assert (result.artists_added, result.tracks_added) == (0, 0)
    assert events(db)[0][1:4] == ("So What", "Miles Davis", 545_000)


def test_publish_without_artist_mbid_reports_the_listen(engine, db):
    # A recording mbid without an artist mbid: the track cannot be created.
    extract(engine, FakeListenBrainz({"ana": [lb_listen(T0, REC_3, None, "Lonely", "?")]}))

    listenbrainz.publish_listens(engine)
    layers.build_marts(engine)

    assert events(db) == []
    warnings = [
        r.check.name for r in quality.run_checks(engine, quality.MART_CHECKS) if not r.passed
    ]
    assert warnings == ["listenbrainz_listens_not_imported"]


def test_publish_skips_listens_from_the_future(engine, db):
    future = int(datetime.now(UTC).timestamp()) + 86_400
    extract(engine, FakeListenBrainz({"ana": [lb_listen(future, REC_1, MBID_A)]}))

    listenbrainz.publish_listens(engine)

    # Importing it would make the next run's source check fail.
    assert events(db) == []
    assert quality.run_checks(engine, quality.SOURCE_CHECKS)[0].passed
