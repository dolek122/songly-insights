"""Aggregations over listening events. Rules are described in ADR 0003.

Every function takes a TimeWindow and an optional listener_id, so the same code answers
both "top artists of everyone" and "top artists of one listener".
Results with equal play counts are ordered by id, so the output is deterministic.
"""

from datetime import timedelta

from sqlalchemy import Date, Select, cast, func, select
from sqlalchemy.orm import Session

from app.errors import UnprocessableError
from app.models import Artist, Genre, ListeningEvent, Track, artist_genres
from app.schemas.stats import DailyPlays, ListenerSummary, TopArtist, TopGenre, TopTrack, Window
from app.services import catalog
from app.services.time_window import TimeWindow

MAX_DAILY_RANGE_DAYS = 366


def _filtered(stmt: Select, window: TimeWindow, listener_id: int | None) -> Select:
    """Add the time window and (optionally) the listener filter to a query over events."""
    stmt = stmt.where(window.filter(ListeningEvent.listened_at))
    if listener_id is not None:
        stmt = stmt.where(ListeningEvent.listener_id == listener_id)
    return stmt


def window_out(window: TimeWindow) -> Window:
    return Window(from_=window.from_, to=window.to)


def top_tracks(
    session: Session, window: TimeWindow, limit: int, listener_id: int | None = None
) -> list[TopTrack]:
    plays = func.count(ListeningEvent.id).label("plays")
    stmt = (
        select(Track.id, Track.title, Artist.id, Artist.name, plays)
        .select_from(ListeningEvent)
        .join(Track, Track.id == ListeningEvent.track_id)
        .join(Artist, Artist.id == Track.artist_id)
        .group_by(Track.id, Artist.id)
        .order_by(plays.desc(), Track.id)
        .limit(limit)
    )
    rows = session.execute(_filtered(stmt, window, listener_id))
    return [
        TopTrack(track_id=t_id, title=title, artist_id=a_id, artist_name=a_name, plays=n)
        for t_id, title, a_id, a_name, n in rows
    ]


def top_artists(
    session: Session, window: TimeWindow, limit: int, listener_id: int | None = None
) -> list[TopArtist]:
    plays = func.count(ListeningEvent.id).label("plays")
    stmt = (
        select(Artist.id, Artist.name, plays)
        .select_from(ListeningEvent)
        .join(Track, Track.id == ListeningEvent.track_id)
        .join(Artist, Artist.id == Track.artist_id)
        .group_by(Artist.id)
        .order_by(plays.desc(), Artist.id)
        .limit(limit)
    )
    rows = session.execute(_filtered(stmt, window, listener_id))
    return [TopArtist(artist_id=a_id, name=name, plays=n) for a_id, name, n in rows]


def top_genres(
    session: Session, window: TimeWindow, limit: int, listener_id: int | None = None
) -> list[TopGenre]:
    # The join with artist_genres turns one play of an artist with 2 genres into 2 rows,
    # so the play counts towards both genres (ADR 0003). The sum over genres can therefore
    # be larger than the number of plays. Artists without genres are not counted here.
    plays = func.count(ListeningEvent.id).label("plays")
    stmt = (
        select(Genre.id, Genre.name, plays)
        .select_from(ListeningEvent)
        .join(Track, Track.id == ListeningEvent.track_id)
        .join(artist_genres, artist_genres.c.artist_id == Track.artist_id)
        .join(Genre, Genre.id == artist_genres.c.genre_id)
        .group_by(Genre.id)
        .order_by(plays.desc(), Genre.id)
        .limit(limit)
    )
    rows = session.execute(_filtered(stmt, window, listener_id))
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
    # `to` is exclusive, so the last day is the one containing the moment just before `to`.
    last_day = (window.to - timedelta(microseconds=1)).date()
    if (last_day - first_day).days + 1 > MAX_DAILY_RANGE_DAYS:
        raise UnprocessableError(
            f"Daily statistics are limited to {MAX_DAILY_RANGE_DAYS} days",
            code="invalid_time_window",
        )

    # timezone('UTC', listened_at) converts to UTC wall-clock time, then we cut off the hours.
    # Without the explicit conversion PostgreSQL would use the session's time zone setting,
    # and the same play could land on a different day depending on server configuration.
    day = cast(func.timezone("UTC", ListeningEvent.listened_at), Date).label("day")
    stmt = select(day, func.count(ListeningEvent.id)).group_by(day)
    counts = dict(session.execute(_filtered(stmt, window, listener_id)).all())

    # Fill the gaps in Python: simpler to read than generate_series() in SQL.
    result = []
    current = first_day
    while current <= last_day:
        result.append(DailyPlays(day=current, plays=counts.get(current, 0)))
        current += timedelta(days=1)
    return result


def listener_summary(session: Session, listener_id: int, window: TimeWindow) -> ListenerSummary:
    catalog.get_listener(session, listener_id)  # 404 when the listener does not exist

    stmt = (
        select(
            func.count(ListeningEvent.id),
            func.count(func.distinct(ListeningEvent.track_id)),
            func.count(func.distinct(Track.artist_id)),
            # We only know that a play started, so we assume the whole track was played.
            # coalesce: SUM over zero rows is NULL in SQL, we want 0.
            func.coalesce(func.sum(Track.duration_ms), 0),
            func.min(ListeningEvent.listened_at),
            func.max(ListeningEvent.listened_at),
        )
        .select_from(ListeningEvent)
        .join(Track, Track.id == ListeningEvent.track_id)
    )
    plays, tracks, artists, total_ms, first, last = session.execute(
        _filtered(stmt, window, listener_id)
    ).one()

    best_artist = top_artists(session, window, limit=1, listener_id=listener_id)
    best_genre = top_genres(session, window, limit=1, listener_id=listener_id)
    return ListenerSummary(
        listener_id=listener_id,
        window=window_out(window),
        total_plays=plays,
        unique_tracks=tracks,
        unique_artists=artists,
        total_listening_ms=total_ms,
        first_listened_at=first,
        last_listened_at=last,
        top_artist=best_artist[0] if best_artist else None,
        top_genre=best_genre[0] if best_genre else None,
    )
