"""End-to-end test of the Prefect flow. Slower than the others (Prefect starts a local server)."""

from datetime import UTC, datetime, timedelta

import pytest
from prefect.testing.utilities import prefect_test_harness
from sqlalchemy import text

from pipeline import flows, musicbrainz
from pipeline.quality import DataQualityError
from tests.pipeline_helpers import MBID_A, FakeMusicBrainz, mb_artist, search_page


@pytest.fixture(scope="module", autouse=True)
def prefect_server():
    # One temporary Prefect server (with its own throwaway database) for this module.
    with prefect_test_harness():
        yield


@pytest.fixture(autouse=True)
def use_test_database(engine, monkeypatch):
    monkeypatch.setattr(flows, "get_engine", lambda: engine)


def test_flow_builds_marts_and_imports_musicbrainz(db, factory, monkeypatch):
    fake = FakeMusicBrainz({("jazz", 0): search_page([mb_artist(MBID_A, "Miles", country="US")])})
    monkeypatch.setattr(musicbrainz.MusicBrainzClient, "create", lambda contact=None: fake.client())
    track = factory.track(factory.artist("Local Band"))
    factory.plays(factory.listener(), track, datetime(2026, 1, 1, tzinfo=UTC))

    flows.songly_pipeline(musicbrainz_tags=["jazz"], artists_per_tag=10)

    result = db.execute(
        text(
            "SELECT artist_name, total_plays, musicbrainz_country "
            "FROM marts.artist_popularity ORDER BY artist_name"
        )
    ).all()
    assert [tuple(r) for r in result] == [("Local Band", 1, None), ("Miles", 0, "US")]


def test_flow_stops_on_failed_quality_check(db, factory):
    track = factory.track(factory.artist())
    factory.plays(factory.listener(), track, datetime.now(UTC) + timedelta(days=2))

    with pytest.raises(DataQualityError):
        flows.songly_pipeline()

    # The source check failed first, so the marts were never built.
    assert db.execute(text("SELECT to_regclass('marts.artist_popularity')")).scalar() is None
