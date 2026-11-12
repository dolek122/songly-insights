"""Reads the state of the data for the Prometheus gauges in app/metrics.py (ADR 0014)."""

import math
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import metrics


def refresh_data_metrics(session: Session) -> None:
    """Called on every scrape of /metrics. Never raises: a broken database is a metric too."""
    try:
        _refresh(session)
        metrics.DATABASE_UP.set(1)
    except SQLAlchemyError:
        session.rollback()
        metrics.DATABASE_UP.set(0)


def _refresh(session: Session) -> None:
    built_at = None
    if session.scalar(text("SELECT to_regclass('marts.build_info')")) is not None:
        built_at = session.scalar(text("SELECT built_at FROM marts.build_info"))
    metrics.MARTS_BUILT.set(1 if built_at else 0)
    # NaN = "no value": an alert like "age > 26 h" stays quiet; MartsMissing covers it.
    age = (datetime.now(UTC) - built_at).total_seconds() if built_at else math.nan
    metrics.MARTS_AGE.set(age)

    last = session.execute(
        text(
            "SELECT status, dq_warnings, dq_errors FROM ops.pipeline_runs "
            "WHERE status <> 'running' ORDER BY id DESC LIMIT 1"
        )
    ).one_or_none()
    metrics.PIPELINE_LAST_RUN_FAILED.set(1 if last and last.status == "failed" else 0)
    metrics.PIPELINE_DQ_WARNINGS.set(last.dq_warnings if last else 0)
    metrics.PIPELINE_DQ_ERRORS.set(last.dq_errors if last else 0)

    last_success = session.scalar(
        text("SELECT max(finished_at) FROM ops.pipeline_runs WHERE status = 'completed'")
    )
    metrics.PIPELINE_LAST_SUCCESS.set(last_success.timestamp() if last_success else math.nan)
