"""Statistics read from the marts built by the pipeline (ADR 0007).

Facts (play counts, listening time) come from marts.listener_track_daily, one row per
(UTC day, listener, track). Names of tracks, artists and genres come from the catalog
(schema public), so a renamed artist shows its current name.

Because the mart has one row per day, a time window must consist of whole UTC days.
Results with equal play counts are ordered by id, so the output is deterministic.
"""

from datetime import datetime, time, timedelta

from sqlalchemy import BigInteger, Select, Table, cast, func, select, text
from sqlalchemy.orm import Session

from app.errors import MartsNotReadyError, UnprocessableError
from app.marts import build_info
from app.marts import listener_track_daily as facts
from app.models import Artist, Genre, Track, artist_genres
from app.schemas.stats import DailyPlays, ListenerSummary, TopArtist, TopGenre, TopTrack, Window
from app.services import catalog
from app.services.time_window import TimeWindow

MAX_DAILY_RANGE_DAYS = 366


def total(column):
    # SUM over a bigint column returns `numeric` in PostgreSQL; cast it back to an integer.
    return cast(func.sum(column), BigInteger)


def require_whole_days(window: TimeWindow) -> None:
    """The mart has one row per day, so `from` and `to` must be midnights in UTC."""
    for name, value in (("from", window.from_), ("to", window.to)):
        if value is not None and value.time() != time(0):
            raise UnprocessableError(
                f"`{name}` must be a whole UTC day (e.g. 2026-01-01 or 2026-01-01T00:00:00Z)",
                details={name: value.isoformat()},
                code="invalid_time_window",
            )


def marts_built_at(session: Session) -> datetime:
    """When the marts were built; 503 when the pipeline has never run."""
    # to_regclass returns NULL instead of an error when the table does not exist.
    if session.scalar(text("SELECT to_regclass('marts.build_info')")) is None:
        raise MartsNotReadyError(
            "Statistics are not available yet. Run the pipeline: python -m pipeline run"
        )
    return session.scalar(select(build_info.c.built_at))


def filter_days(
    stmt: Select, window: TimeWindow, listener_id: int | None, table: Table = facts
) -> Select:
    """Add the window (as days; `to` stays exclusive) and the optional listener filter.

    Works for every mart with `day` and `listener_id` columns.
    """
    if window.from_ is not None:
        stmt = stmt.where(table.c.day >= window.from_.date())
    if window.to is not None:
        stmt = stmt.where(table.c.day < window.to.date())
    if listener_id is not None:
        stmt = stmt.where(table.c.listener_id == listener_id)
    return stmt


def window_out(window: TimeWindow) -> Window:
    return Window(from_=window.from_, to=window.to)


def top_tracks(
    session: Session, window: TimeWindow, limit: int, listener_id: int | None = None
) -> list[TopTrack]:
    plays = total(facts.c.plays).label("plays")
    stmt = (
        select(Track.id, Track.title, Artist.id, Artist.name, plays)
        .select_from(facts)
        .join(Track, Track.id == facts.c.track_id)
        .join(Artist, Artist.id == facts.c.artist_id)
        .group_by(Track.id, Artist.id)
        .order_by(plays.desc(), Track.id)
        .limit(limit)
    )
    rows = session.execute(filter_days(stmt, window, listener_id))
    return [
        TopTrack(track_id=t_id, title=title, artist_id=a_id, artist_name=a_name, plays=n)
        for t_id, title, a_id, a_name, n in rows
    ]


def top_artists(
    session: Session, window: TimeWindow, limit: int, listener_id: int | None = None
) -> list[TopArtist]:
    plays = total(facts.c.plays).label("plays")
    stmt = (
        select(Artist.id, Artist.name, plays)
        .select_from(facts)
        .join(Artist, Artist.id == facts.c.artist_id)
        .group_by(Artist.id)
        .order_by(plays.desc(), Artist.id)
        .limit(limit)
    )
    rows = session.execute(filter_days(stmt, window, listener_id))
    return [TopArtist(artist_id=a_id, name=name, plays=n) for a_id, name, n in rows]


def top_genres(
    session: Session, window: TimeWindow, limit: int, listener_id: int | None = None
) -> list[TopGenre]:
    # The join with artist_genres turns one row of an artist with 2 genres into 2 rows,
    # so the plays count towards both genres (ADR 0003). The sum over genres can therefore
    # be larger than the number of plays. Artists without genres are not counted here.
    plays = total(facts.c.plays).label("plays")
    stmt = (
        select(Genre.id, Genre.name, plays)
        .select_from(facts)
        .join(artist_genres, artist_genres.c.artist_id == facts.c.artist_id)
        .join(Genre, Genre.id == artist_genres.c.genre_id)
        .group_by(Genre.id)
        .order_by(plays.desc(), Genre.id)
        .limit(limit)
    )
    rows = session.execute(filter_days(stmt, window, listener_id))
    return [TopGenre(genre_id=g_id, name=name, plays=n) for g_id, name, n in rows]


def daily_plays(
    session: Session, window: TimeWindow, listener_id: int | None = None
) -> list[DailyPlays]:
    """Number of plays per UTC day. Days without plays are included with plays=0."""
    if window.from_ is None or window.to is None:
        raise UnprocessableError(
            "Both `from` and `to` are required for daily statistics", code="invalid_time_window"
        )
    first_day = window.from_.date()
    last_day = window.to.date() - timedelta(days=1)  # `to` is exclusive
    if (last_day - first_day).days + 1 > MAX_DAILY_RANGE_DAYS:
        raise UnprocessableError(
            f"Daily statistics are limited to {MAX_DAILY_RANGE_DAYS} days",
            code="invalid_time_window",
        )

    stmt = select(facts.c.day, total(facts.c.plays)).group_by(facts.c.day)
    counts = dict(session.execute(filter_days(stmt, window, listener_id)).all())

    # Fill the gaps in Python: simpler to read than generate_series() in SQL.
    result = []
    current = first_day
    while current <= last_day:
        result.append(DailyPlays(day=current, plays=counts.get(current, 0)))
        current += timedelta(days=1)
    return result


def listener_summary(
    session: Session, listener_id: int, window: TimeWindow, data_as_of: datetime
) -> ListenerSummary:
    catalog.get_listener(session, listener_id)  # 404 when the listener does not exist

    stmt = select(
        func.coalesce(total(facts.c.plays), 0),
        # Distinct counts are why the mart keeps track_id: they cannot be added up per day.
        func.count(func.distinct(facts.c.track_id)),
        func.count(func.distinct(facts.c.artist_id)),
        func.coalesce(total(facts.c.listening_ms), 0),
        func.min(facts.c.first_listened_at),
        func.max(facts.c.last_listened_at),
    )
    plays, tracks, artists, total_ms, first, last = session.execute(
        filter_days(stmt, window, listener_id)
    ).one()

    best_artist = top_artists(session, window, limit=1, listener_id=listener_id)
    best_genre = top_genres(session, window, limit=1, listener_id=listener_id)
    return ListenerSummary(
        listener_id=listener_id,
        window=window_out(window),
        data_as_of=data_as_of,
        total_plays=plays,
        unique_tracks=tracks,
        unique_artists=artists,
        total_listening_ms=total_ms,
        first_listened_at=first,
        last_listened_at=last,
        top_artist=best_artist[0] if best_artist else None,
        top_genre=best_genre[0] if best_genre else None,
    )
