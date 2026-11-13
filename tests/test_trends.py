from datetime import UTC, datetime

import pytest

from tests.conftest import assert_error

API = "/api/v1"
# Current window: Jan 8-14. Previous window (same length): Jan 1-7.
WINDOW = {"from": "2026-01-08", "to": "2026-01-15"}


def day(d: int, minute: int = 0) -> datetime:
    return datetime(2026, 1, d, 12, minute, tzinfo=UTC)


@pytest.fixture
def library(factory, build_marts):
    rock, jazz = factory.genre("rock"), factory.genre("jazz")
    rising = factory.track(factory.artist("Rising", genres=[rock]))
    falling = factory.track(factory.artist("Falling", genres=[jazz]))
    new = factory.track(factory.artist("Newcomer", genres=[rock, jazz]))
    steady = factory.track(factory.artist("Steady"))
    alice, bob = factory.listener("alice"), factory.listener("bob")

    factory.plays(alice, rising, day(2), day(9), day(10), day(11))  # 1 -> 3
    factory.plays(alice, falling, day(1), day(2), day(3), day(4), day(9))  # 4 -> 1
    factory.plays(bob, new, day(12), day(13))  # 0 -> 2
    factory.plays(alice, steady, day(5), day(12))  # 1 -> 1
    factory.plays(alice, rising, day(20))  # after the window: ignored
    build_marts()
    return {"alice": alice, "bob": bob}


def trend(client, path: str, **params) -> dict:
    response = client.get(f"{API}/stats/{path}", params={**WINDOW, **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_rising_artists(client, library):
    body = trend(client, "trending-artists")

    assert body["previous_window"] == {"from": "2026-01-01T00:00:00Z", "to": "2026-01-08T00:00:00Z"}
    assert body["direction"] == "rising"
    assert [(i["name"], i["previous_plays"], i["plays"]) for i in body["items"]] == [
        # Both grew by 2; the one with more plays now comes first.
        ("Rising", 1, 3),
        ("Newcomer", 0, 2),
    ]


def test_change_percentage(client, library):
    items = {i["name"]: i for i in trend(client, "trending-artists")["items"]}

    assert (items["Rising"]["change"], items["Rising"]["change_pct"]) == (2, 200.0)
    # Growth from zero has no percentage.
    assert items["Newcomer"]["change_pct"] is None


def test_falling_artists(client, library):
    items = trend(client, "trending-artists", direction="falling")["items"]
    assert [(i["name"], i["change"], i["change_pct"]) for i in items] == [("Falling", -3, -75.0)]


def test_trending_for_one_listener(client, library):
    items = trend(client, "trending-artists", listener_id=library["bob"].id)["items"]
    assert [i["name"] for i in items] == ["Newcomer"]


def test_trending_genres_count_every_genre(client, library):
    rising = trend(client, "trending-genres")["items"]
    falling = trend(client, "trending-genres", direction="falling")["items"]

    # rock: Rising 1 -> 3 and Newcomer 0 -> 2. jazz: Falling 4 -> 1 and Newcomer 0 -> 2.
    assert [(i["name"], i["previous_plays"], i["plays"]) for i in rising] == [("rock", 1, 5)]
    assert [(i["name"], i["previous_plays"], i["plays"]) for i in falling] == [("jazz", 4, 3)]


def test_trending_limit(client, library):
    assert len(trend(client, "trending-artists", limit=1)["items"]) == 1


@pytest.mark.parametrize("params", [{"from": "2026-01-08"}, {"to": "2026-01-15"}, {}])
def test_trends_need_both_ends(client, library, params):
    response = client.get(f"{API}/stats/trending-artists", params=params)
    assert_error(response, 422, "invalid_time_window")


def test_unknown_direction_is_rejected(client, library):
    response = client.get(f"{API}/stats/trending-genres", params={**WINDOW, "direction": "up"})
    assert_error(response, 422, "validation_error")


def test_trends_need_whole_days(client, library):
    params = {"from": "2026-01-08T06:00:00Z", "to": "2026-01-15"}
    response = client.get(f"{API}/stats/trending-artists", params=params)
    assert_error(response, 422, "invalid_time_window")


def test_trends_need_the_pipeline(client):
    response = client.get(f"{API}/stats/trending-artists", params=WINDOW)
    assert_error(response, 503, "marts_not_ready")
