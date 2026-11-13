from datetime import UTC, datetime

import pytest

from tests.conftest import assert_error

API = "/api/v1"


def day(d: int, minute: int = 0) -> datetime:
    return datetime(2026, 1, d, 12, minute, tzinfo=UTC)


@pytest.fixture
def make_plays(factory):
    """Create listeners with given play counts per artist: make_plays(alice={"A": 3, "B": 4})."""
    artists = {}

    def make(**listeners: dict[str, int]):
        created = {}
        for username, counts in listeners.items():
            listener = factory.listener(username)
            for name, count in counts.items():
                if name not in artists:
                    artists[name] = factory.track(factory.artist(name), name)
                # Different minutes, so each play is a separate event.
                factory.plays(listener, artists[name], *(day(1, m) for m in range(count)))
            created[username] = listener
        return created

    return make


def similar(client, listener, **params) -> list[dict]:
    response = client.get(f"{API}/listeners/{listener.id}/similar", params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_cosine_similarity_value(client, make_plays, build_marts):
    people = make_plays(alice={"A": 3, "B": 4}, bob={"A": 4, "B": 3})
    build_marts()

    items = similar(client, people["alice"])

    # (3*4 + 4*3) / (5 * 5) = 24 / 25
    assert [(i["username"], i["similarity"], i["shared_artists"]) for i in items] == [
        ("bob", 0.96, 2)
    ]


def test_same_proportions_mean_the_same_taste(client, make_plays, build_marts):
    # carol plays the same artists in the same proportions, just 10x more.
    people = make_plays(alice={"A": 1, "B": 2}, carol={"A": 10, "B": 20})
    build_marts()

    assert similar(client, people["alice"])[0]["similarity"] == 1.0


def test_ranking_excludes_self_and_strangers(client, make_plays, build_marts):
    people = make_plays(
        alice={"A": 5, "B": 1},
        twin={"A": 5, "B": 1},
        partial={"A": 1, "C": 5},
        stranger={"Z": 9},  # nothing in common: not listed
    )
    build_marts()

    items = similar(client, people["alice"])

    assert [i["username"] for i in items] == ["twin", "partial"]
    assert items[0]["similarity"] == 1.0
    assert 0 < items[1]["similarity"] < 1


def test_top_shared_artists_explain_the_similarity(client, make_plays, build_marts):
    people = make_plays(
        alice={"A": 9, "B": 1, "C": 5, "D": 2, "E": 7},
        bob={"A": 1, "B": 8, "C": 6, "D": 2, "E": 7},
    )
    build_marts()

    shared = similar(client, people["alice"])[0]["top_shared_artists"]

    # Ranked by the smaller of the two play counts: E (7), C (5), D (2). A and B are
    # big for only one of them.
    assert [a["name"] for a in shared] == ["E", "C", "D"]


def test_limit(client, make_plays, build_marts):
    people = make_plays(alice={"A": 1}, b1={"A": 1}, b2={"A": 1}, b3={"A": 1})
    build_marts()
    assert len(similar(client, people["alice"], limit=2)) == 2


def test_window_changes_the_vectors(client, factory, build_marts):
    alice, bob = factory.listener("alice"), factory.listener("bob")
    a = factory.track(factory.artist("A"))
    b = factory.track(factory.artist("B"))
    factory.plays(alice, a, day(1))
    factory.plays(bob, a, day(5))
    factory.plays(bob, b, day(1))
    build_marts()

    # On Jan 1 bob only played B: nothing in common with alice.
    assert similar(client, alice, **{"from": "2026-01-01", "to": "2026-01-02"}) == []
    assert len(similar(client, alice)) == 1


def test_listener_without_plays_has_no_similar_listeners(client, factory, build_marts):
    alice = factory.listener("alice")
    build_marts()
    assert similar(client, alice) == []


def test_similar_for_missing_listener(client, build_marts):
    build_marts()
    assert_error(client.get(f"{API}/listeners/404/similar"), 404, "not_found")


def test_similar_needs_whole_days(client, factory, build_marts):
    alice = factory.listener()
    build_marts()
    response = client.get(f"{API}/listeners/{alice.id}/similar", params={"to": "2026-01-01T01:00"})
    assert_error(response, 422, "invalid_time_window")


def test_similar_needs_the_pipeline(client, factory):
    alice = factory.listener()
    assert_error(client.get(f"{API}/listeners/{alice.id}/similar"), 503, "marts_not_ready")
