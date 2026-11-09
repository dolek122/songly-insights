from datetime import UTC, datetime

from sqlalchemy import func, select

from app.models import ListeningEvent
from tests.conftest import assert_error

URL = "/api/v1/listening-events"


def event(listener, track, listened_at: str) -> dict:
    return {"listener_id": listener.id, "track_id": track.id, "listened_at": listened_at}


def test_bulk_import_inserts_events(client, factory, db):
    alice, track = factory.listener(), factory.track(factory.artist())
    events = [
        event(alice, track, "2026-01-01T10:00:00Z"),
        event(alice, track, "2026-01-01T11:00:00Z"),
    ]

    response = client.post(f"{URL}/bulk", json={"events": events})

    assert response.status_code == 200
    assert response.json() == {"received": 2, "inserted": 2, "duplicates": 0}
    assert db.scalar(select(func.count()).select_from(ListeningEvent)) == 2


def test_bulk_import_is_idempotent(client, factory, db):
    alice, track = factory.listener(), factory.track(factory.artist())
    events = [event(alice, track, "2026-01-01T10:00:00Z")]
    client.post(f"{URL}/bulk", json={"events": events})

    response = client.post(f"{URL}/bulk", json={"events": events})

    assert response.json() == {"received": 1, "inserted": 0, "duplicates": 1}
    assert db.scalar(select(func.count()).select_from(ListeningEvent)) == 1


def test_duplicates_inside_one_batch_are_counted_once(client, factory):
    alice, track = factory.listener(), factory.track(factory.artist())
    same = event(alice, track, "2026-01-01T10:00:00Z")
    # The same moment written in another time zone is the same event.
    same_other_zone = event(alice, track, "2026-01-01T12:00:00+02:00")

    response = client.post(f"{URL}/bulk", json={"events": [same, same, same_other_zone]})

    assert response.json() == {"received": 3, "inserted": 1, "duplicates": 2}


def test_same_track_at_another_time_is_a_new_event(client, factory):
    alice, bob = factory.listener("alice"), factory.listener("bob")
    track = factory.track(factory.artist())
    events = [
        event(alice, track, "2026-01-01T10:00:00Z"),
        event(alice, track, "2026-01-01T10:00:01Z"),
        event(bob, track, "2026-01-01T10:00:00Z"),
    ]
    response = client.post(f"{URL}/bulk", json={"events": events})
    assert response.json()["inserted"] == 3


def test_imported_time_is_stored_in_utc(client, factory, db):
    alice, track = factory.listener(), factory.track(factory.artist())
    client.post(f"{URL}/bulk", json={"events": [event(alice, track, "2026-01-01T01:30:00+02:00")]})

    stored = db.scalar(select(ListeningEvent.listened_at))

    assert stored == datetime(2025, 12, 31, 23, 30, tzinfo=UTC)


def test_import_rejects_time_without_zone(client, factory):
    alice, track = factory.listener(), factory.track(factory.artist())
    response = client.post(
        f"{URL}/bulk", json={"events": [event(alice, track, "2026-01-01T10:00:00")]}
    )
    assert_error(response, 422, "validation_error")


def test_import_rejects_unknown_references(client, factory, db):
    alice, track = factory.listener(), factory.track(factory.artist())
    events = [
        {"listener_id": alice.id, "track_id": 999, "listened_at": "2026-01-01T10:00:00Z"},
        {"listener_id": 42, "track_id": track.id, "listened_at": "2026-01-01T10:00:00Z"},
    ]

    response = client.post(f"{URL}/bulk", json={"events": events})

    error = assert_error(response, 422, "unknown_reference")

    assert error["details"] == {"listener_ids": [42], "track_ids": [999]}
    # Nothing is imported when one event is invalid (all or nothing).
    assert db.scalar(select(func.count()).select_from(ListeningEvent)) == 0


def test_import_rejects_empty_and_too_large_batches(client, factory):
    alice, track = factory.listener(), factory.track(factory.artist())
    assert_error(client.post(f"{URL}/bulk", json={"events": []}), 422, "validation_error")
    too_many = [event(alice, track, "2026-01-01T10:00:00Z")] * 10_001
    assert_error(client.post(f"{URL}/bulk", json={"events": too_many}), 422, "validation_error")


def test_list_events_uses_half_open_window(client, factory):
    alice, bob = factory.listener("alice"), factory.listener("bob")
    track = factory.track(factory.artist())
    factory.plays(
        alice,
        track,
        datetime(2026, 1, 1, tzinfo=UTC),  # exactly `from`: included
        datetime(2026, 1, 1, 12, tzinfo=UTC),
        datetime(2026, 1, 2, tzinfo=UTC),  # exactly `to`: excluded
    )
    factory.plays(bob, track, datetime(2026, 1, 1, 6, tzinfo=UTC))

    body = client.get(
        URL, params={"from": "2026-01-01", "to": "2026-01-02", "listener_id": alice.id}
    ).json()

    assert body["total"] == 2
    assert [e["listened_at"] for e in body["items"]] == [
        "2026-01-01T00:00:00Z",
        "2026-01-01T12:00:00Z",
    ]
