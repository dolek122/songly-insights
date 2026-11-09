"""Time window used by all statistics. Rules are described in ADR 0003.

* The window is half-open: `from` is inclusive, `to` is exclusive.
  Thanks to that, consecutive windows (Jan 1-Feb 1, Feb 1-Mar 1) never count a play twice.
* Both ends are optional; a missing end means "unbounded".
* Everything is in UTC. A timestamp without a time zone is treated as UTC.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, and_, true

from app.errors import UnprocessableError


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True)
class TimeWindow:
    from_: datetime | None = None
    to: datetime | None = None

    @classmethod
    def create(cls, from_: datetime | None, to: datetime | None) -> "TimeWindow":
        from_ = to_utc(from_) if from_ else None
        to = to_utc(to) if to else None
        if from_ and to and from_ >= to:
            raise UnprocessableError(
                "`from` must be earlier than `to`",
                details={"from": from_.isoformat(), "to": to.isoformat()},
                code="invalid_time_window",
            )
        return cls(from_=from_, to=to)

    def filter(self, column) -> ColumnElement[bool]:
        """SQL condition `from <= column < to` (skipping the ends that are not set)."""
        conditions = []
        if self.from_ is not None:
            conditions.append(column >= self.from_)
        if self.to is not None:
            conditions.append(column < self.to)
        return and_(true(), *conditions)
