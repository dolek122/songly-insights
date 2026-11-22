import pytest

from app.config import get_settings
from tests.conftest import assert_error

API = "/api/v1"

WRITE_REQUESTS = [
    ("/genres", {"name": "rock"}),
    ("/artists", {"name": "Bowie"}),
    ("/tracks", {"title": "Heroes", "artist_id": 1, "duration_ms": 300_000}),
    ("/listeners", {"username": "alice"}),
    ("/listening-events/bulk", {"events": []}),
]


@pytest.mark.parametrize(("path", "body"), WRITE_REQUESTS)
def test_write_without_key_is_rejected(client, path, body):
    client.headers.pop("X-API-Key")

    assert_error(client.post(API + path, json=body), 401, "unauthorized")


@pytest.mark.parametrize(("path", "body"), WRITE_REQUESTS)
def test_write_with_wrong_key_is_rejected(client, path, body):
    response = client.post(API + path, json=body, headers={"X-API-Key": "wrong"})

    assert_error(response, 401, "unauthorized")


def test_key_is_checked_before_the_body(client):
    client.headers.pop("X-API-Key")

    assert_error(client.post(f"{API}/genres", json={}), 401, "unauthorized")


def test_writes_are_disabled_when_no_key_is_configured(client):
    client.app.dependency_overrides[get_settings] = lambda: get_settings().model_copy(
        update={"api_key": None}
    )

    error = assert_error(client.post(f"{API}/genres", json={"name": "rock"}), 401, "unauthorized")
    assert "API_KEY" in error["message"]


def test_write_with_valid_key_works(client):
    response = client.post(f"{API}/genres", json={"name": "rock"})

    assert response.status_code == 201


def test_reads_do_not_need_a_key(client):
    client.headers.pop("X-API-Key")

    assert client.get(f"{API}/genres").status_code == 200
    assert client.get(f"{API}/artists").status_code == 200
