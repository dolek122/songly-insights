from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.marts import listening_sessions as sessions
from app.schemas.stats import ListeningSession
from app.services import catalog
from app.services.stats import filter_days
from app.services.time_window import TimeWindow

_DURATION_MINUTES = func.extract("epoch", sessions.c.ended_at - sessions.c.started_at) / 60


def _minutes(start: datetime, end: datetime) -> float:
    return round((end - start).total_seconds() / 60, 1)


def _rounded(value: Decimal | float | None) -> float | None:
    return None if value is None else round(float(value), 1)


def list_sessions(
    session: Session, listener_id: int, window: TimeWindow, limit: int, offset: int
) -> tuple[list[ListeningSession], int]:
    catalog.get_listener(session, listener_id)
    stmt = filter_days(select(sessions), window, listener_id, table=sessions)
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = session.execute(
        stmt.order_by(sessions.c.started_at.desc()).limit(limit).offset(offset)
    ).mappings()
    items = [
        ListeningSession(
            started_at=r["started_at"],
            ended_at=r["ended_at"],
            duration_minutes=_minutes(r["started_at"], r["ended_at"]),
            plays=r["plays"],
            unique_tracks=r["unique_tracks"],
            unique_artists=r["unique_artists"],
            listening_ms=r["listening_ms"],
        )
        for r in rows
    ]
    return items, total


def session_stats(session: Session, window: TimeWindow, listener_id: int | None) -> dict:
    stmt = select(
        func.count(),
        func.avg(sessions.c.plays),
        func.avg(_DURATION_MINUTES),
        func.percentile_cont(0.5).within_group(_DURATION_MINUTES),
        func.max(_DURATION_MINUTES),
    ).select_from(sessions)
    count, avg_plays, avg_minutes, median, longest = session.execute(
        filter_days(stmt, window, listener_id, table=sessions)
    ).one()
    return {
        "sessions": count,
        "avg_plays": _rounded(avg_plays),
        "avg_duration_minutes": _rounded(avg_minutes),
        "median_duration_minutes": _rounded(median),
        "longest_duration_minutes": _rounded(longest),
    }
