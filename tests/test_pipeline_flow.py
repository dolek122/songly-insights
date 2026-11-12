"""End-to-end test of the Prefect flow. Slower than the others (Prefect starts a local server)."""

from datetime import UTC, datetime, timedelta

import pytest
from prefect.testing.utilities import prefect_test_harness
from sqlalchemy import text

from pipeline import flows, listenbrainz, musicbrainz
from pipeline.quality import DataQualityError
from tests.pipeline_helpers import (
    MBID_A,
    REC_1,
    FakeListenBrainz,
    FakeMusicBrainz,
    lb_listen,
    mb_artist,
    mb_recording,
    recordings_page,
    search_page,
)


@pytest.fixture(scope="module", autouse=True)
def prefect_server():
    # One temporary Prefect server (with its own throwaway database) for this module.
    with prefect_test_harness():
        yield


@pytest.fixture(autouse=True)
def use_test_database(engine, monkeypatch):
    monkeypatch.setattr(flows, "get_engine", lambda: engine)


def test_flow_builds_marts_and_imports_musicbrainz(db, factory, monkeypatch):
    fake = FakeMusicBrainz(
        {("jazz", 0): search_page([mb_artist(MBID_A, "Miles", country="US")])},
        recordings={(MBID_A, 0): recordings_page([mb_recording(REC_1, "So What")])},
    )
    monkeypatch.setattr(musicbrainz.MusicBrainzClient, "create", lambda contact=None: fake.client())
    track = factory.track(factory.artist("Local Band"))
    factory.plays(factory.listener(), track, datetime(2026, 1, 1, tzinfo=UTC))

    flows.songly_pipeline(musicbrainz_tags=["jazz"], artists_per_tag=10, recordings_per_artist=5)

    result = db.execute(
        text(
            "SELECT artist_name, total_plays, musicbrainz_country "
            "FROM marts.artist_popularity ORDER BY artist_name"
        )
    ).all()
    assert [tuple(r) for r in result] == [("Local Band", 1, None), ("Miles", 0, "US")]
    new_track = db.execute(text("SELECT title FROM tracks WHERE mbid = :m"), {"m": REC_1})
    assert new_track.scalar() == "So What"


def test_flow_can_skip_recordings(db, monkeypatch):
    fake = FakeMusicBrainz({("jazz", 0): search_page([mb_artist(MBID_A, "Miles")])})
    monkeypatch.setattr(musicbrainz.MusicBrainzClient, "create", lambda contact=None: fake.client())

    flows.songly_pipeline(musicbrainz_tags=["jazz"], recordings_per_artist=0)

    assert fake.recording_requests() == []


def test_flow_stops_on_failed_quality_check(db, factory):
    track = factory.track(factory.artist())
    factory.plays(factory.listener(), track, datetime.now(UTC) + timedelta(days=2))

    with pytest.raises(DataQualityError):
        flows.songly_pipeline()

    # The source check failed first, so the marts were never built.
    assert db.execute(text("SELECT to_regclass('marts.artist_popularity')")).scalar() is None


def test_flow_imports_listenbrainz_listens_into_statistics(client, monkeypatch):
    fake = FakeListenBrainz(
        {"ana": [lb_listen(1_767_225_600 + i, REC_1, MBID_A, "So What", "Miles") for i in range(3)]}
    )
    monkeypatch.setattr(
        listenbrainz.ListenBrainzClient, "create", lambda contact=None: fake.client()
    )

    flows.songly_pipeline(listenbrainz_users=["ana"])

    # The listens went raw -> staging -> listening events -> marts -> API statistics.
    body = client.get("/api/v1/stats/top-tracks", params={"from": "2026-01-01"}).json()
    assert [(t["title"], t["plays"]) for t in body["items"]] == [("So What", 3)]
