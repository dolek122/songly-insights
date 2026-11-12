from datetime import UTC, datetime

import pytest

from tests.conftest import assert_error

API = "/api/v1"


def at(day: int, hour: int = 12, month: int = 1) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=UTC)


@pytest.fixture
def empty_marts(build_marts):
    """Marts built from an empty database: statistics work and return nothing."""
    build_marts()


@pytest.fixture
def library(factory, build_marts):
    """Two listeners, three artists. Bowie has two genres, Miles one, Silent none."""
    rock, jazz = factory.genre("rock"), factory.genre("jazz")
    bowie = factory.artist("Bowie", genres=[rock, jazz])
    miles = factory.artist("Miles", genres=[jazz])
    silent = factory.artist("Silent")
    tracks = {
        "heroes": factory.track(bowie, "Heroes", duration_ms=300_000),
        "starman": factory.track(bowie, "Starman", duration_ms=250_000),
        "so_what": factory.track(miles, "So What", duration_ms=500_000),
        "quiet": factory.track(silent, "Quiet", duration_ms=100_000),
    }
    alice, bob = factory.listener("alice"), factory.listener("bob")
    factory.plays(alice, tracks["heroes"], at(1), at(2), at(3))
    factory.plays(alice, tracks["so_what"], at(2))
    factory.plays(alice, tracks["quiet"], at(4))
    factory.plays(bob, tracks["so_what"], at(1), at(5))
    factory.plays(bob, tracks["starman"], at(5))
    build_marts()
    return {"tracks": tracks, "alice": alice, "bob": bob, "rock": rock, "jazz": jazz}


# --- top lists ------------------------------------------------------------------------------


def test_top_tracks(client, library):
    body = client.get(f"{API}/stats/top-tracks").json()

    assert body["window"] == {"from": None, "to": None}
    assert [(t["title"], t["plays"]) for t in body["items"]] == [
        ("Heroes", 3),
        ("So What", 3),  # same count as Heroes: the lower track id wins
        ("Starman", 1),
        ("Quiet", 1),
    ]
    assert body["items"][0]["artist_name"] == "Bowie"


def test_top_tracks_respects_limit(client, library):
    body = client.get(f"{API}/stats/top-tracks", params={"limit": 1}).json()
    assert len(body["items"]) == 1


def test_top_artists_for_one_listener(client, library):
    body = client.get(f"{API}/stats/top-artists", params={"listener_id": library["bob"].id}).json()
    assert [(a["name"], a["plays"]) for a in body["items"]] == [("Miles", 2), ("Bowie", 1)]


def test_play_counts_towards_every_genre_of_the_artist(client, library):
    body = client.get(f"{API}/stats/top-genres").json()

    # jazz: 4 Bowie plays + 3 Miles plays; rock: 4 Bowie plays.
    # Silent has no genre, so its play is not counted anywhere.
    assert [(g["name"], g["plays"]) for g in body["items"]] == [("jazz", 7), ("rock", 4)]


def test_window_is_half_open(client, library):
    # Day 2 is included (`from`), day 3 is excluded (`to`).
    params = {"from": "2026-01-02", "to": "2026-01-03"}
    body = client.get(f"{API}/stats/top-tracks", params=params).json()
    assert [(t["title"], t["plays"]) for t in body["items"]] == [("Heroes", 1), ("So What", 1)]


def test_window_without_time_zone_means_utc(client, library):
    utc = client.get(f"{API}/stats/top-artists", params={"from": "2026-01-05T00:00:00Z"}).json()
    naive = client.get(f"{API}/stats/top-artists", params={"from": "2026-01-05T00:00:00"}).json()

    assert naive == utc
    assert naive["window"]["from"] == "2026-01-05T00:00:00Z"


def test_window_with_offset_is_converted_to_utc(client, library):
    body = client.get(f"{API}/stats/top-artists", params={"from": "2026-01-05T02:00:00+02:00"})
    assert body.json()["window"]["from"] == "2026-01-05T00:00:00Z"


@pytest.mark.parametrize("path", ["top-tracks", "top-artists", "top-genres", "daily"])
def test_from_must_be_before_to(client, empty_marts, path):
    params = {"from": "2026-01-02", "to": "2026-01-02"}
    assert_error(client.get(f"{API}/stats/{path}", params=params), 422, "invalid_time_window")


@pytest.mark.parametrize("limit", [0, 101])
def test_top_limit_is_validated(client, empty_marts, limit):
    response = client.get(f"{API}/stats/top-tracks", params={"limit": limit})
    assert_error(response, 422, "validation_error")


def test_invalid_date_is_rejected(client, empty_marts):
    response = client.get(f"{API}/stats/top-tracks", params={"from": "yesterday"})
    assert_error(response, 422, "validation_error")


def test_top_lists_are_empty_without_data(client, empty_marts):
    assert client.get(f"{API}/stats/top-genres").json()["items"] == []


# --- daily ----------------------------------------------------------------------------------


def test_daily_fills_days_without_plays(client, library):
    params = {"from": "2026-01-03", "to": "2026-01-07"}  # 3rd, 4th, 5th, 6th
    body = client.get(f"{API}/stats/daily", params=params).json()
    assert body["items"] == [
        {"day": "2026-01-03", "plays": 1},
        {"day": "2026-01-04", "plays": 1},
        {"day": "2026-01-05", "plays": 2},
        {"day": "2026-01-06", "plays": 0},
    ]


def test_daily_groups_by_utc_day(client, factory, build_marts):
    alice, track = factory.listener(), factory.track(factory.artist())
    # 23:30 at UTC-02:00 on Jan 1 is 01:30 UTC on Jan 2.
    factory.plays(alice, track, datetime.fromisoformat("2026-01-01T23:30:00-02:00"))
    build_marts()

    body = client.get(f"{API}/stats/daily", params={"from": "2026-01-01", "to": "2026-01-03"})

    assert body.json()["items"] == [
        {"day": "2026-01-01", "plays": 0},
        {"day": "2026-01-02", "plays": 1},
    ]


def test_daily_for_one_listener(client, library):
    params = {"from": "2026-01-01", "to": "2026-01-02", "listener_id": library["bob"].id}
    body = client.get(f"{API}/stats/daily", params=params).json()
    assert body["items"] == [{"day": "2026-01-01", "plays": 1}]


def test_daily_requires_both_ends(client, empty_marts):
    response = client.get(f"{API}/stats/daily", params={"from": "2026-01-01"})
    assert_error(response, 422, "invalid_time_window")


def test_daily_range_is_limited(client, empty_marts):
    ok = client.get(f"{API}/stats/daily", params={"from": "2025-01-01", "to": "2026-01-02"})
    assert ok.status_code == 200
    assert len(ok.json()["items"]) == 366

    too_long = client.get(f"{API}/stats/daily", params={"from": "2025-01-01", "to": "2026-01-03"})
    assert_error(too_long, 422, "invalid_time_window")


# --- listener summary -----------------------------------------------------------------------


def test_listener_summary(client, library):
    alice = library["alice"]

    body = client.get(f"{API}/listeners/{alice.id}/summary").json()

    assert body["total_plays"] == 5
    assert body["unique_tracks"] == 3
    assert body["unique_artists"] == 3
    assert body["total_listening_ms"] == 3 * 300_000 + 500_000 + 100_000
    assert body["first_listened_at"] == "2026-01-01T12:00:00Z"
    assert body["last_listened_at"] == "2026-01-04T12:00:00Z"
    assert body["top_artist"]["name"] == "Bowie"
    assert body["top_genre"] == {"genre_id": library["jazz"].id, "name": "jazz", "plays": 4}


def test_listener_summary_in_window(client, library):
    alice = library["alice"]
    params = {"from": "2026-01-04", "to": "2026-01-05"}

    body = client.get(f"{API}/listeners/{alice.id}/summary", params=params).json()

    assert body["total_plays"] == 1
    assert body["top_artist"]["name"] == "Silent"
    assert body["top_genre"] is None  # Silent has no genres


def test_listener_summary_without_plays(client, factory, build_marts):
    alice = factory.listener()
    build_marts()

    body = client.get(f"{API}/listeners/{alice.id}/summary").json()

    assert body["total_plays"] == 0
    assert body["total_listening_ms"] == 0
    assert body["first_listened_at"] is None
    assert body["top_artist"] is None


def test_listener_summary_for_missing_listener(client, empty_marts):
    assert_error(client.get(f"{API}/listeners/77/summary"), 404, "not_found")


# --- reading from marts (ADR 0007) ----------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2026-01-01T12:00:00Z"},
        {"to": "2026-01-02T00:00:01"},
        # Midnight in Warsaw is 23:00 UTC on the previous day: not a whole UTC day.
        {"from": "2026-01-01T00:00:00+01:00"},
    ],
)
def test_window_must_be_whole_utc_days(client, library, params):
    error = assert_error(
        client.get(f"{API}/stats/top-tracks", params=params), 422, "invalid_time_window"
    )
    assert "whole UTC day" in error["message"]


@pytest.mark.parametrize(
    "path",
    ["stats/top-tracks", "stats/top-artists", "stats/top-genres", "listeners/1/summary"],
)
def test_statistics_need_the_pipeline_to_have_run(client, path):
    error = assert_error(client.get(f"{API}/{path}"), 503, "marts_not_ready")
    assert "python -m pipeline run" in error["message"]


def test_daily_without_marts(client):
    params = {"from": "2026-01-01", "to": "2026-01-02"}
    assert_error(client.get(f"{API}/stats/daily", params=params), 503, "marts_not_ready")


def test_statistics_are_as_fresh_as_the_last_pipeline_run(client, factory, library, build_marts):
    before = client.get(f"{API}/stats/top-artists").json()
    factory.plays(library["bob"], library["tracks"]["quiet"], at(6), at(7))

    # New plays are not visible until the pipeline runs again ...
    assert client.get(f"{API}/stats/top-artists").json() == before

    build_marts()
    after = client.get(f"{API}/stats/top-artists").json()

    # ... and then they are, with a newer data_as_of.
    assert ("Silent", 3) in [(a["name"], a["plays"]) for a in after["items"]]
    assert after["data_as_of"] > before["data_as_of"]
