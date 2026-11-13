import json
import logging
import sys

import pytest
from fastapi.testclient import TestClient

from app.logging_config import JsonFormatter, configure_logging
from app.main import create_app


@pytest.fixture
def json_logs():
    """Collect formatted JSON lines from all loggers while a test runs."""
    lines: list[dict] = []

    class Collect(logging.Handler):
        def emit(self, record):
            # format() runs inside the request, so the request id ContextVar is visible.
            lines.append(json.loads(JsonFormatter().format(record)))

    handler = Collect()
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    yield lines
    root.removeHandler(handler)
    root.setLevel(previous_level)


def test_formatter_writes_one_json_object():
    record = logging.LogRecord(
        "songly.test", logging.WARNING, __file__, 1, "hello %s", ("you",), None
    )
    record.fields = {"status": 200}

    data = json.loads(JsonFormatter().format(record))

    assert data["level"] == "WARNING"
    assert data["logger"] == "songly.test"
    assert data["message"] == "hello you"
    assert data["status"] == 200
    assert data["time"].endswith("+00:00")


def test_formatter_includes_exceptions():
    try:
        raise ValueError("broken")
    except ValueError:
        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed", (), None)
        record.exc_info = sys.exc_info()

    data = json.loads(JsonFormatter().format(record))

    assert "ValueError: broken" in data["exception"]


def test_request_id_is_generated_and_returned(client):
    response = client.get("/api/v1/genres")

    rid = response.headers["X-Request-ID"]
    assert len(rid) == 32  # uuid4 hex


def test_incoming_request_id_is_kept(client):
    response = client.get("/api/v1/genres", headers={"X-Request-ID": "abc-123"})
    assert response.headers["X-Request-ID"] == "abc-123"


@pytest.mark.parametrize("bad", ["x" * 65, "has space", "inject\\nline"])
def test_suspicious_request_id_is_replaced(client, bad):
    response = client.get("/api/v1/genres", headers={"X-Request-ID": bad})
    assert response.headers["X-Request-ID"] != bad


def test_access_log_line(client, json_logs):
    client.get("/api/v1/artists/42", headers={"X-Request-ID": "req-1"})

    [line] = [x for x in json_logs if x["logger"] == "songly.access"]
    assert line["message"] == "GET /api/v1/artists/42 404"
    assert line["request_id"] == "req-1"
    assert line["route"] == "/api/v1/artists/{artist_id}"
    assert line["status"] == 404
    assert line["duration_ms"] >= 0


def test_health_and_metrics_are_not_in_the_access_log(client, json_logs):
    client.get("/health")
    client.get("/metrics")
    assert [x for x in json_logs if x["logger"] == "songly.access"] == []


def test_every_log_of_a_request_has_its_id(json_logs):
    app = create_app()
    logger = logging.getLogger("songly.endpoint")

    @app.get("/work")
    def work():
        logger.info("doing work")
        return {}

    @app.get("/boom")
    def boom():
        raise RuntimeError("boom")

    client = TestClient(app, raise_server_exceptions=False)
    client.get("/work", headers={"X-Request-ID": "work-1"})
    client.get("/boom", headers={"X-Request-ID": "boom-1"})

    by_message = {x["message"]: x for x in json_logs}
    assert by_message["doing work"]["request_id"] == "work-1"
    # The unexpected error is logged by the error handler, after the middleware: same id.
    assert by_message["Unhandled error"]["request_id"] == "boom-1"
    assert "RuntimeError: boom" in by_message["Unhandled error"]["exception"]


def test_configure_logging_routes_uvicorn_through_json(capsys):
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    try:
        configure_logging("INFO")
        logging.getLogger("uvicorn.error").info("Started server process")
    finally:
        root.handlers, root.level = saved[0], saved[1]

    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (line["logger"], line["message"]) == ("uvicorn.error", "Started server process")
