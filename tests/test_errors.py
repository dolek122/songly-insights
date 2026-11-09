from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import assert_error


def test_unknown_url_uses_error_format(client):
    assert_error(client.get("/api/v1/does-not-exist"), 404, "not_found")


def test_wrong_method_uses_error_format(client):
    assert_error(client.delete("/api/v1/genres"), 405, "method_not_allowed")


def test_validation_error_lists_problems(client):
    response = client.get("/api/v1/artists", params={"limit": "abc"})
    error = assert_error(response, 422, "validation_error")
    assert error["details"][0]["loc"] == ["query", "limit"]


def test_unexpected_exception_returns_500_without_internals():
    app = create_app()

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret database password in a stack trace")

    response = TestClient(app, raise_server_exceptions=False).get("/boom")
    error = assert_error(response, 500, "internal_error")
    assert "secret" not in response.text
    assert "details" not in error
