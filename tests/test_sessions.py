from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from tests.conftest import assert_error

API = "/api/v1"


def at(day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 1, day, hour, minute, second, tzinfo=UTC)


@pytest.fixture
def plays(factory, build_marts):
    """alice: 3 sessions; bob: 1 session in the middle of alice's first one."""
    alice, bob = factory.listener("alice"), factory.listener("bob")
    five_min = factory.track(factory.artist("A"), "Five", duration_ms=300_000)
    unknown = factory.track(factory.artist("B"), "Unknown", duration_ms=None)
    factory.plays(
        alice,
        five_min,
        at(1, 10, 0),
        at(1, 10, 30),  # exactly 30 minutes later: same session
        at(1, 11, 0, 1),  # 30 min 1 s later: new session
        at(1, 23, 50),  # new session, runs past midnight ...
        at(2, 0, 10),  # ... still the session that started on Jan 1
    )
    factory.plays(alice, unknown, at(1, 23, 55))
    factory.plays(bob, five_min, at(1, 10, 15))
    build_marts()
    return {"alice": alice, "bob": bob}


def sessions_of(client, listener, **params) -> list[dict]:
    response = client.get(f"{API}/listeners/{listener.id}/sessions", params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_sessions_are_split_by_30_minute_gaps(client, plays):
    items = sessions_of(client, plays["alice"])

    # Newest first.
    assert [(s["started_at"], s["plays"]) for s in items] == [
        ("2026-01-01T23:50:00Z", 3),
        ("2026-01-01T11:00:01Z", 1),
        ("2026-01-01T10:00:00Z", 2),
    ]


def test_session_ends_when_its_last_track_ends(client, plays):
    first = sessions_of(client, plays["alice"])[-1]

    # Last play at 10:30 + a 5-minute track.
    assert first["ended_at"] == "2026-01-01T10:35:00Z"
    assert first["duration_minutes"] == 35.0
    assert first["listening_ms"] == 600_000


def test_unknown_length_counts_as_play_not_as_time(client, plays):
    late = sessions_of(client, plays["alice"])[0]
    assert late["unique_tracks"] == 2
    assert late["listening_ms"] == 600_000  # the "Unknown" play adds nothing


def test_session_belongs_to_the_day_it_started(client, plays):
    jan_2 = sessions_of(client, plays["alice"], **{"from": "2026-01-02", "to": "2026-01-03"})
    jan_1 = sessions_of(client, plays["alice"], **{"from": "2026-01-01", "to": "2026-01-02"})

    assert jan_2 == []
    assert len(jan_1) == 3


def test_sessions_of_listeners_are_separate(client, plays):
    # bob listened during alice's first session; it is his own session.
    assert [s["plays"] for s in sessions_of(client, plays["bob"])] == [1]


def test_sessions_are_paginated(client, plays):
    body = client.get(
        f"{API}/listeners/{plays['alice'].id}/sessions", params={"limit": 1, "offset": 1}
    ).json()
    assert (body["total"], len(body["items"])) == (3, 1)
    assert body["items"][0]["started_at"] == "2026-01-01T11:00:01Z"


def test_session_stats(client, plays):
    body = client.get(f"{API}/stats/sessions", params={"listener_id": plays["alice"].id}).json()

    # Durations: 35 min, 5 min, 25 min (23:50 -> 00:10 + 5 min).
    assert body["sessions"] == 3
    assert body["avg_plays"] == 2.0
    assert body["avg_duration_minutes"] == 21.7
    assert body["median_duration_minutes"] == 25.0
    assert body["longest_duration_minutes"] == 35.0


def test_session_stats_without_sessions(client, plays):
    body = client.get(f"{API}/stats/sessions", params={"from": "2027-01-01"}).json()
    assert body["sessions"] == 0
    assert body["avg_plays"] is None
    assert body["median_duration_minutes"] is None


def test_sessions_of_missing_listener(client, plays):
    assert_error(client.get(f"{API}/listeners/999/sessions"), 404, "not_found")


def test_sessions_need_whole_days(client, plays):
    response = client.get(f"{API}/stats/sessions", params={"from": "2026-01-01T10:00:00Z"})
    assert_error(response, 422, "invalid_time_window")


def test_sessions_need_the_pipeline(client, factory):
    alice = factory.listener()
    assert_error(client.get(f"{API}/listeners/{alice.id}/sessions"), 503, "marts_not_ready")
    assert_error(client.get(f"{API}/stats/sessions"), 503, "marts_not_ready")


def test_quality_check_catches_sessions_too_close(engine, db, plays):
    from pipeline import quality

    # Move a session to start 10 minutes after the previous one ended: breaks the rule.
    db.execute(
        text(
            "UPDATE marts.listening_sessions SET started_at = :t "
            "WHERE started_at = '2026-01-01T11:00:01Z'"
        ),
        {"t": at(1, 10, 30) + timedelta(minutes=10)},
    )
    db.commit()

    results = quality.run_checks(engine, quality.MART_CHECKS)

    assert [r.check.name for r in results if not r.passed] == [
        "listening_sessions_separated_by_gap"
    ]
