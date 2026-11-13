"""Query parameters shared by many endpoints, written once as FastAPI dependencies."""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.services import stats
from app.services.time_window import TimeWindow


@dataclass(frozen=True)
class Pagination:
    limit: int
    offset: int


def pagination(
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> Pagination:
    return Pagination(limit=limit, offset=offset)


def time_window(
    # `from` is a Python keyword, so the argument is from_ and `alias` sets the URL name.
    from_: datetime | None = Query(
        None, alias="from", description="Inclusive start. Without a time zone it means UTC."
    ),
    to: datetime | None = Query(
        None, description="Exclusive end. Without a time zone it means UTC."
    ),
) -> TimeWindow:
    return TimeWindow.create(from_, to)


PaginationDep = Annotated[Pagination, Depends(pagination)]
TimeWindowDep = Annotated[TimeWindow, Depends(time_window)]


@dataclass(frozen=True)
class StatsQuery:
    window: TimeWindow
    data_as_of: datetime


def stats_query(window: TimeWindowDep, db: Session = Depends(get_db)) -> StatsQuery:
    """Shared by all statistics endpoints: whole-day window + marts must exist (ADR 0007).

    FastAPI caches dependencies within one request, so `db` is the same session
    the endpoint gets.
    """
    stats.require_whole_days(window)
    return StatsQuery(window=window, data_as_of=stats.marts_built_at(db))


StatsQueryDep = Annotated[StatsQuery, Depends(stats_query)]
TopLimit = Annotated[int, Query(ge=1, le=100, description="How many items to return")]
