"""Prometheus metrics of the API (ADR 0014).

Two kinds of metrics:
* HTTP traffic, recorded by a middleware for every request (counters and a histogram),
* the state of the data (marts age, last pipeline run), read from the database each time
  Prometheus scrapes /metrics (gauges).

prometheus_client keeps metrics in the memory of the process, so the API runs with one
uvicorn worker. Several workers would each have their own numbers (the library has a
multiprocess mode for that, not needed at this scale).
"""

import time

from fastapi import FastAPI, Request
from prometheus_client import Counter, Gauge, Histogram

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

# Requests to these paths are not recorded: Prometheus scrapes /metrics every few seconds
# and Docker calls /health; they would drown the real traffic.
NOT_RECORDED = {"/metrics", "/health"}


def route_template(request: Request) -> str:
    """The route template ("/api/v1/listeners/{listener_id}") instead of the real path
    ("/api/v1/listeners/17"): one time series per endpoint, not one per listener.

    FastAPI stores the matched route in the request scope as declared in its router,
    i.e. without the prefix given to include_router(), so we add our one API prefix back.
    """
    route = request.scope.get("route")
    if route is None:
        return "unmatched"  # 404 for an unknown URL
    if request.url.path.startswith(API_PREFIX) and not route.path.startswith(API_PREFIX):
        return API_PREFIX + route.path
    return route.path


def install_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def record_request(request: Request, call_next):
        started = time.perf_counter()
        status = 500  # stays 500 when the endpoint raises an unexpected exception
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            path = route_template(request)
            if path not in NOT_RECORDED:
                HTTP_REQUESTS.labels(request.method, path, str(status)).inc()
                HTTP_DURATION.labels(request.method, path).observe(time.perf_counter() - started)
