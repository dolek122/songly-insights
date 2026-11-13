"""Trending artists and genres (ADR 0011).

A trend compares the window with the window right before it, of the same length:
for from=2026-01-08&to=2026-01-15 the previous window is 2026-01-01..2026-01-08.
`change` = plays now - plays before. "rising" lists the biggest growth first,
"falling" the biggest drop first. Read from marts.listener_track_daily (ADR 0007).
"""

from collections.abc import Callable
from typing import Literal

from sqlalchemy import Select, case, select
from sqlalchemy.orm import Session

from app.errors import UnprocessableError
from app.marts import listener_track_daily as facts
from app.models import Artist, Genre, artist_genres
from app.schemas.stats import TrendItem
from app.services.stats import filter_days, total
from app.services.time_window import TimeWindow

Direction = Literal["rising", "falling"]


def previous_window(window: TimeWindow) -> TimeWindow:
    if window.from_ is None or window.to is None:
        raise UnprocessableError(
            "Both `from` and `to` are required for trends", code="invalid_time_window"
        )
    length = window.to - window.from_
    return TimeWindow(from_=window.from_ - length, to=window.from_)


def _trend(
    session: Session,
    window: TimeWindow,
    direction: Direction,
    limit: int,
    listener_id: int | None,
    id_column,
    name_column,
    add_joins: Callable[[Select], Select],
) -> list[TrendItem]:
    previous = previous_window(window)

    # One query reads both windows; CASE decides which window a row belongs to.
    in_current = facts.c.day >= window.from_.date()
    plays_now = total(case((in_current, facts.c.plays), else_=0))
    plays_before = total(case((in_current, 0), else_=facts.c.plays))
    change = plays_now - plays_before

    stmt = add_joins(select(id_column, name_column, plays_now, plays_before).select_from(facts))
    stmt = stmt.group_by(id_column, name_column)
    if direction == "rising":
        stmt = stmt.having(change > 0).order_by(change.desc(), plays_now.desc(), id_column)
    else:
        stmt = stmt.having(change < 0).order_by(change, plays_before.desc(), id_column)
    # Read from the start of the previous window to the end of the current one.
    both_windows = TimeWindow(from_=previous.from_, to=window.to)
    rows = session.execute(filter_days(stmt, both_windows, listener_id).limit(limit))

    return [
        TrendItem(
            id=item_id,
            name=name,
            plays=now,
            previous_plays=before,
            change=now - before,
            change_pct=round(100 * (now - before) / before, 1) if before else None,
        )
        for item_id, name, now, before in rows
    ]


def trending_artists(
    session: Session,
    window: TimeWindow,
    direction: Direction,
    limit: int,
    listener_id: int | None = None,
) -> list[TrendItem]:
    return _trend(
        session,
        window,
        direction,
        limit,
        listener_id,
        Artist.id,
        Artist.name,
        lambda stmt: stmt.join(Artist, Artist.id == facts.c.artist_id),
    )


def trending_genres(
    session: Session,
    window: TimeWindow,
    direction: Direction,
    limit: int,
    listener_id: int | None = None,
) -> list[TrendItem]:
    # A play counts towards every genre of its artist (ADR 0003).
    return _trend(
        session,
        window,
        direction,
        limit,
        listener_id,
        Genre.id,
        Genre.name,
        lambda stmt: stmt.join(artist_genres, artist_genres.c.artist_id == facts.c.artist_id).join(
            Genre, Genre.id == artist_genres.c.genre_id
        ),
    )
