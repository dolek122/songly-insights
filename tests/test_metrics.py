import math

from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import create_app


def requests_count(route: str, status: str, method: str = "GET") -> float:
    # Counters live for the whole test process, so tests compare before/after.
    value = REGISTRY.get_sample_value(
        "songly_http_requests_total", {"method": method, "route": route, "status": status}
    )
    return value or 0.0


def gauge(name: str) -> float:
    return REGISTRY.get_sample_value(name)


def test_metrics_endpoint_uses_prometheus_format(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# TYPE songly_http_requests_total counter" in response.text


def test_requests_are_counted_per_route_template(client, factory):
    artist = factory.artist()
    route = "/api/v1/artists/{artist_id}"
    before = requests_count(route, "200")

    client.get(f"/api/v1/artists/{artist.id}")
    client.get(f"/api/v1/artists/{artist.id}")

    # One series for the endpoint, not one per artist id.
    assert requests_count(route, "200") == before + 2


def test_errors_and_unknown_urls_are_counted(client):
    not_found = requests_count("/api/v1/artists/{artist_id}", "404")
    unmatched = requests_count("unmatched", "404")

    client.get("/api/v1/artists/999")
    client.get("/no/such/url")

    assert requests_count("/api/v1/artists/{artist_id}", "404") == not_found + 1
    assert requests_count("unmatched", "404") == unmatched + 1


def test_unexpected_exception_is_counted_as_500():
    app = create_app()

    @app.get("/boom")
    def boom():
        raise RuntimeError("boom")

    before = requests_count("/boom", "500")
    TestClient(app, raise_server_exceptions=False).get("/boom")
    assert requests_count("/boom", "500") == before + 1


def test_health_and_metrics_are_not_counted(client):
    before = requests_count("/health", "200"), requests_count("/metrics", "200")
    client.get("/health")
    client.get("/metrics")
    assert (requests_count("/health", "200"), requests_count("/metrics", "200")) == before


def test_request_duration_is_recorded(client):
    labels = {"method": "GET", "route": "/api/v1/genres"}
    before = REGISTRY.get_sample_value("songly_http_request_duration_seconds_count", labels) or 0
    client.get("/api/v1/genres")
    after = REGISTRY.get_sample_value("songly_http_request_duration_seconds_count", labels)
    assert after == before + 1


def test_data_metrics_without_marts(client):
    client.get("/metrics")

    assert gauge("songly_database_up") == 1
    assert gauge("songly_marts_built") == 0
    assert math.isnan(gauge("songly_marts_age_seconds"))
    assert gauge("songly_pipeline_last_run_failed") == 0
    assert math.isnan(gauge("songly_pipeline_last_success_timestamp_seconds"))


def test_data_metrics_after_pipeline_runs(client, db, build_marts):
    build_marts()
    db.execute(
        text(
            """
            INSERT INTO ops.pipeline_runs
                (flow_run_id, started_at, finished_at, status, dq_warnings, dq_errors)
            VALUES
                ('a', '2026-01-01T03:00Z', '2026-01-01T03:01Z', 'completed', 2, 0),
                ('b', '2026-01-02T03:00Z', '2026-01-02T03:01Z', 'failed', 1, 3),
                ('c', '2026-01-03T03:00Z', NULL, 'running', 0, 0)
            """
        )
    )
    db.commit()

    client.get("/metrics")

    assert gauge("songly_marts_built") == 1
    assert 0 <= gauge("songly_marts_age_seconds") < 60
    # The newest finished run (b) failed; the running one (c) is not finished yet.
    assert gauge("songly_pipeline_last_run_failed") == 1
    assert (gauge("songly_pipeline_dq_warnings"), gauge("songly_pipeline_dq_errors")) == (1, 3)
    # Last success: run a.
    assert gauge("songly_pipeline_last_success_timestamp_seconds") == 1767236460


def test_metrics_work_when_the_database_is_down():
    broken = create_engine("postgresql+psycopg://user:pass@127.0.0.1:1/none")
    app = create_app()

    def broken_db():
        with Session(broken) as session:
            yield session

    app.dependency_overrides[get_db] = broken_db
    response = TestClient(app).get("/metrics")

    # Prometheus still gets an answer; the problem is visible as a metric.
    assert response.status_code == 200
    assert gauge("songly_database_up") == 0
