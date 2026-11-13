from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from pipeline import layers, quality


def failed_names(results: list[quality.CheckResult]) -> list[str]:
    return [r.check.name for r in results if not r.passed]


@pytest.fixture
def one_play(factory):
    track = factory.track(factory.artist(genres=[factory.genre("rock")]))
    factory.plays(factory.listener(), track, datetime(2026, 1, 1, tzinfo=UTC))
    return track


def test_all_checks_pass_on_clean_data(engine, one_play):
    layers.build_staging(engine)
    layers.build_marts(engine)
    all_checks = quality.SOURCE_CHECKS + quality.STAGING_CHECKS + quality.MART_CHECKS

    results = quality.run_checks(engine, all_checks)

    assert failed_names(results) == []
    quality.ensure_passed(results)  # does not raise


def test_play_in_the_future_stops_the_pipeline(engine, factory, one_play):
    factory.plays(factory.listener("bob"), one_play, datetime.now(UTC) + timedelta(days=1))

    results = quality.run_checks(engine, quality.SOURCE_CHECKS)

    assert failed_names(results) == ["listening_events_not_in_future"]
    with pytest.raises(quality.DataQualityError, match="listening_events_not_in_future"):
        quality.ensure_passed(results)


def test_warning_does_not_stop_the_pipeline(engine, factory):
    factory.track(factory.artist(), duration_ms=3 * 60 * 60 * 1000)  # a 3-hour track

    results = quality.run_checks(engine, quality.SOURCE_CHECKS)

    assert failed_names(results) == ["tracks_shorter_than_2_hours"]
    quality.ensure_passed(results)  # only a warning


def test_reconciliation_detects_a_wrong_mart(engine, db, one_play):
    layers.build_staging(engine)
    layers.build_marts(engine)
    db.execute(text("UPDATE marts.daily_listener_activity SET plays = plays + 1"))
    db.commit()

    results = quality.run_checks(engine, quality.MART_CHECKS)

    assert failed_names(results) == ["daily_listener_activity_matches_events"]
