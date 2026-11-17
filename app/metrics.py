import logging
import time
import uuid

from fastapi import FastAPI, Request
from prometheus_client import Counter, Gauge, Histogram

from app.logging_config import request_id

API_PREFIX = "/api/v1"

HTTP_REQUESTS = Counter(
    "songly_http_requests_total",
    "HTTP requests handled by the API",
    ["method", "route", "status"],
)
HTTP_DURATION = Histogram(
    "songly_http_request_duration_seconds",
    "Time to handle an HTTP request",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
DATABASE_UP = Gauge("songly_database_up", "1 when the API can query the database")
MARTS_BUILT = Gauge("songly_marts_built", "1 when the marts exist (the pipeline ran)")
MARTS_AGE = Gauge("songly_marts_age_seconds", "Seconds since the marts were built")
PIPELINE_LAST_RUN_FAILED = Gauge(
    "songly_pipeline_last_run_failed", "1 when the newest pipeline run failed"
)
PIPELINE_LAST_SUCCESS = Gauge(
    "songly_pipeline_last_success_timestamp_seconds",
    "Unix time when the newest successful pipeline run finished",
)
PIPELINE_DQ_WARNINGS = Gauge(
    "songly_pipeline_dq_warnings", "Data quality warnings in the newest pipeline run"
)
PIPELINE_DQ_ERRORS = Gauge(
    "songly_pipeline_dq_errors", "Failed data quality checks (errors) in the newest run"
)

BACKUP_LAST_SUCCESS = Gauge(
    "songly_backup_last_success_timestamp_seconds",
    "Unix time of the newest verified database backup (0 = none yet)",
)
BACKUP_LAST_FAILED = Gauge("songly_backup_last_failed", "1 when the newest backup failed")

access_log = logging.getLogger("songly.access")

NOT_RECORDED = {"/metrics", "/health"}


def route_template(request: Request) -> str:
    route = request.scope.get("route")
    if route is None:
        return "unmatched"
    if request.url.path.startswith(API_PREFIX) and not route.path.startswith(API_PREFIX):
        return API_PREFIX + route.path
    return route.path


def _incoming_request_id(request: Request) -> str:
    value = request.headers.get("x-request-id", "")
    if 0 < len(value) <= 64 and all(c.isalnum() or c in "-_." for c in value):
        return value
    return uuid.uuid4().hex


def install_middleware(app: FastAPI) -> None:

    @app.middleware("http")
    async def observe_request(request: Request, call_next):
        started = time.perf_counter()
        rid = _incoming_request_id(request)
        request_id.set(rid)
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            path = route_template(request)
            if path not in NOT_RECORDED:
                duration = time.perf_counter() - started
                HTTP_REQUESTS.labels(request.method, path, str(status)).inc()
                HTTP_DURATION.labels(request.method, path).observe(duration)
                access_log.info(
                    "%s %s %s",
                    request.method,
                    request.url.path,
                    status,
                    extra={
                        "fields": {
                            "request_id": rid,
                            "method": request.method,
                            "route": path,
                            "path": request.url.path,
                            "status": status,
                            "duration_ms": round(duration * 1000, 1),
                        }
                    },
                )
