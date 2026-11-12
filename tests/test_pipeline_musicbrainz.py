import httpx
import pytest
from sqlalchemy import text

from pipeline import layers, musicbrainz, quality
from tests.pipeline_helpers import (
    MBID_A,
    MBID_B,
    MBID_C,
    REC_1,
    REC_2,
    REC_3,
    FakeMusicBrainz,
    mb_artist,
    mb_recording,
    recordings_page,
    search_page,
)


def raw_pages(db) -> list[tuple]:
    sql = "SELECT tag, page_offset FROM raw.musicbrainz_artist_search ORDER BY id"
    return [tuple(r) for r in db.execute(text(sql))]


# --- client ---------------------------------------------------------------------------------


def test_user_agent_names_the_app_and_contact():
    assert musicbrainz.make_user_agent(None) == "songly-insights/0.1"
    assert musicbrainz.make_user_agent("me@example.com") == "songly-insights/0.1 ( me@example.com )"


def test_search_request_quotes_the_tag():
    request = FakeMusicBrainz({}).client().artist_search_request("hip hop", limit=10, offset=20)
    params = request.url.params
    assert params["query"] == 'tag:"hip hop"'
    assert (params["limit"], params["offset"], params["fmt"]) == ("10", "20", "json")


def test_client_waits_between_requests():
    now = [100.0]
    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    client = musicbrainz.MusicBrainzClient(http, sleep=sleep, clock=lambda: now[0])
    request = http.build_request("GET", "https://musicbrainz.test/ws/2/artist")

    client.send(request)  # first request: no waiting
    now[0] += 0.25
    client.send(request)  # 0.25 s later: wait the remaining 0.75 s
    now[0] += 5
    client.send(request)  # long after: no waiting

    assert waits == [pytest.approx(0.75)]


def test_client_raises_on_server_error():
    fake = FakeMusicBrainz({}, status_code=503)
    client = fake.client()
    with pytest.raises(httpx.HTTPStatusError):
        client.send(client.artist_search_request("jazz", 10, 0))


# --- extract --------------------------------------------------------------------------------


def test_extract_follows_offsets(engine, db, monkeypatch):
    monkeypatch.setattr(musicbrainz, "MAX_PAGE_SIZE", 2)
    fake = FakeMusicBrainz(
        {
            ("jazz", 0): search_page([mb_artist(MBID_A, "A"), mb_artist(MBID_B, "B")]),
            ("jazz", 2): search_page([mb_artist(MBID_C, "C")], offset=2),
        }
    )

    result = musicbrainz.extract_artists_by_tag(
        engine, fake.client(), ["jazz"], artists_per_tag=6, run_id="t"
    )

    # Offset 2 returned fewer than 2 artists, so offset 4 is never requested.
    assert result.pages_downloaded == 2
    assert raw_pages(db) == [("jazz", 0), ("jazz", 2)]


def test_extract_uses_raw_as_cache(engine, db):
    fake = FakeMusicBrainz({("jazz", 0): search_page([mb_artist(MBID_A, "A")])})
    musicbrainz.extract_artists_by_tag(engine, fake.client(), ["jazz"], 5, run_id="first")

    again = musicbrainz.extract_artists_by_tag(engine, fake.client(), ["jazz"], 5, run_id="second")

    assert (again.pages_downloaded, again.pages_from_cache) == (0, 1)
    assert len(fake.requests) == 1
    assert len(raw_pages(db)) == 1


def test_extract_downloads_again_when_cache_is_too_old(engine, db):
    fake = FakeMusicBrainz({("jazz", 0): search_page([mb_artist(MBID_A, "A")])})
    musicbrainz.extract_artists_by_tag(engine, fake.client(), ["jazz"], 5, run_id="first")

    again = musicbrainz.extract_artists_by_tag(
        engine, fake.client(), ["jazz"], 5, run_id="second", max_age_days=0
    )

    assert again.pages_downloaded == 1
    assert len(raw_pages(db)) == 2  # raw is append-only, history is kept


def test_extract_stores_nothing_when_the_api_fails(engine, db):
    fake = FakeMusicBrainz({}, status_code=503)
    with pytest.raises(httpx.HTTPStatusError):
        musicbrainz.extract_artists_by_tag(engine, fake.client(), ["jazz"], 5, run_id="t")
    assert raw_pages(db) == []


# --- publish to catalog ---------------------------------------------------------------------


def load(engine, artists: list[dict]) -> None:
    fake = FakeMusicBrainz({("jazz", 0): search_page(artists)})
    musicbrainz.extract_artists_by_tag(
        engine, fake.client(), ["jazz"], 25, run_id="t", max_age_days=0
    )
    layers.build_staging(engine)


def catalog(db) -> list[tuple]:
    sql = """
        SELECT a.name, a.mbid::text, coalesce(string_agg(g.name, ',' ORDER BY g.name), '')
        FROM artists a
        LEFT JOIN artist_genres ag ON ag.artist_id = a.id
        LEFT JOIN genres g ON g.id = ag.genre_id
        GROUP BY a.id ORDER BY a.name
    """
    return [tuple(r) for r in db.execute(text(sql))]


def test_publish_adds_artists_and_genres(engine, db, factory):
    factory.genre("bebop")
    load(
        engine,
        [
            mb_artist(MBID_A, "Miles", tags=[("jazz", 5), ("bebop", 2), ("trumpet", 1)]),
            mb_artist(MBID_B, "Disliked", tags=[("jazz", 1), ("bebop", -3)]),
        ],
    )

    result = musicbrainz.publish_to_catalog(engine, ["Jazz"])

    # "jazz" is created because it was searched; "trumpet" is not a known genre;
    # the negative "bebop" vote does not link Disliked to bebop.
    assert catalog(db) == [("Disliked", MBID_B, "jazz"), ("Miles", MBID_A, "bebop,jazz")]
    assert result.artists_upserted == 2
    assert result.genre_links_added == 3


def test_publish_is_idempotent_and_updates_names(engine, db):
    load(engine, [mb_artist(MBID_A, "Miles")])
    musicbrainz.publish_to_catalog(engine, ["jazz"])

    load(engine, [mb_artist(MBID_A, "Miles Davis")])
    second = musicbrainz.publish_to_catalog(engine, ["jazz"])

    assert catalog(db) == [("Miles Davis", MBID_A, "jazz")]
    assert second.genre_links_added == 0


# --- recordings -----------------------------------------------------------------------------


def test_recording_browse_request():
    request = FakeMusicBrainz({}).client().recording_browse_request(MBID_A, limit=25, offset=50)
    assert request.url.path.endswith("/recording")
    params = request.url.params
    assert (params["artist"], params["limit"], params["offset"]) == (MBID_A, "25", "50")


def load_artists(engine, *artists: dict) -> None:
    """Land artists in raw and build staging (recordings are fetched for staging artists)."""
    fake = FakeMusicBrainz({("jazz", 0): search_page(list(artists))})
    musicbrainz.extract_artists_by_tag(engine, fake.client(), ["jazz"], 25, run_id="t")
    layers.build_staging(engine)


def test_extract_recordings_for_every_staging_artist(engine, db, monkeypatch):
    monkeypatch.setattr(musicbrainz, "MAX_PAGE_SIZE", 2)
    load_artists(engine, mb_artist(MBID_A, "A"), mb_artist(MBID_B, "B"))
    fake = FakeMusicBrainz(
        {},
        recordings={
            (MBID_A, 0): recordings_page([mb_recording(REC_1, "One"), mb_recording(REC_2, "Two")]),
            (MBID_A, 2): recordings_page([mb_recording(REC_3, "Three")], offset=2),
        },
    )

    result = musicbrainz.extract_recordings(engine, fake.client(), 10, run_id="t")

    # A: page 0 is full, page 2 is short -> stop. B: page 0 is empty -> stop.
    assert fake.recording_requests() == [(MBID_A, 0), (MBID_A, 2), (MBID_B, 0)]
    assert result.pages_downloaded == 3
    # Staging views read raw live: no rebuild needed to see the recordings.
    titles = db.execute(text("SELECT title FROM staging.musicbrainz_recordings ORDER BY title"))
    assert titles.scalars().all() == ["One", "Three", "Two"]


def test_extract_recordings_uses_raw_as_cache(engine):
    load_artists(engine, mb_artist(MBID_A, "A"))
    fake = FakeMusicBrainz(
        {}, recordings={(MBID_A, 0): recordings_page([mb_recording(REC_1, "x")])}
    )
    musicbrainz.extract_recordings(engine, fake.client(), 10, run_id="first")

    again = musicbrainz.extract_recordings(engine, fake.client(), 10, run_id="second")

    assert (again.pages_downloaded, again.pages_from_cache) == (0, 1)
    assert len(fake.recording_requests()) == 1


def publish_with_recordings(engine, recordings: list[dict], tags=("jazz",)):
    load_artists(engine, mb_artist(MBID_A, "Miles"))
    fake = FakeMusicBrainz({}, recordings={(MBID_A, 0): recordings_page(recordings)})
    musicbrainz.extract_recordings(engine, fake.client(), 25, run_id="t", max_age_days=0)
    return musicbrainz.publish_to_catalog(engine, list(tags))


def tracks(db) -> list[tuple]:
    sql = """
        SELECT t.title, t.duration_ms, t.mbid::text, a.name
        FROM tracks t JOIN artists a ON a.id = t.artist_id ORDER BY t.title
    """
    return [tuple(r) for r in db.execute(text(sql))]


def test_publish_turns_recordings_into_tracks(engine, db):
    result = publish_with_recordings(
        engine,
        [
            mb_recording(REC_1, "So What", length=545_000),
            mb_recording(REC_2, "No Length", length=None),
            mb_recording(REC_3, "Live Video", video=True),
        ],
    )

    # Recordings without a length or that are videos are skipped.
    assert tracks(db) == [("So What", 545_000, REC_1, "Miles")]
    assert result.tracks_upserted == 1


def test_publish_tracks_is_idempotent_and_updates_title(engine, db):
    publish_with_recordings(engine, [mb_recording(REC_1, "So What", length=545_000)])

    second = publish_with_recordings(
        engine, [mb_recording(REC_1, "So What (Remastered)", length=546_000)]
    )

    assert tracks(db) == [("So What (Remastered)", 546_000, REC_1, "Miles")]
    assert second.tracks_upserted == 1  # updated, not inserted again


def test_publish_shortens_too_long_titles(engine, db):
    publish_with_recordings(engine, [mb_recording(REC_1, "x" * 400)])
    assert len(tracks(db)[0][0]) == 300


def test_staging_flags_recordings_without_length(engine):
    load_artists(engine, mb_artist(MBID_A, "A"))
    fake = FakeMusicBrainz(
        {}, recordings={(MBID_A, 0): recordings_page([mb_recording(REC_1, "x", length=None)])}
    )
    musicbrainz.extract_recordings(engine, fake.client(), 10, run_id="t")

    results = quality.run_checks(engine, quality.STAGING_CHECKS)

    failed = [(r.check.name, r.check.severity) for r in results if not r.passed]
    assert failed == [("musicbrainz_recordings_have_length", "warn")]
