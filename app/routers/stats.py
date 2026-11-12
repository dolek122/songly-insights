from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.deps import StatsQueryDep, TopLimit
from app.schemas.stats import (
    DailyPlaysResponse,
    SessionStats,
    TopArtistsResponse,
    TopGenresResponse,
    TopTracksResponse,
    TrendResponse,
)
from app.services import sessions, stats, trends

# All statistics are read from the marts built by the pipeline (ADR 0007):
# windows must be whole UTC days and data is as fresh as `data_as_of`.
router = APIRouter(prefix="/stats", tags=["stats"])

ListenerFilter = Query(None, description="Only plays of this listener")


@router.get("/top-tracks", response_model=TopTracksResponse)
def top_tracks(
    query: StatsQueryDep,
    limit: TopLimit = 10,
    listener_id: int | None = ListenerFilter,
    db: Session = Depends(get_db),
):
    items = stats.top_tracks(db, query.window, limit, listener_id)
    return TopTracksResponse(
        window=stats.window_out(query.window), data_as_of=query.data_as_of, items=items
    )


@router.get("/top-artists", response_model=TopArtistsResponse)
def top_artists(
    query: StatsQueryDep,
    limit: TopLimit = 10,
    listener_id: int | None = ListenerFilter,
    db: Session = Depends(get_db),
):
    items = stats.top_artists(db, query.window, limit, listener_id)
    return TopArtistsResponse(
        window=stats.window_out(query.window), data_as_of=query.data_as_of, items=items
    )


@router.get("/top-genres", response_model=TopGenresResponse)
def top_genres(
    query: StatsQueryDep,
    limit: TopLimit = 10,
    listener_id: int | None = ListenerFilter,
    db: Session = Depends(get_db),
):
    """A play counts towards every genre of its artist, so the sum can exceed total plays."""
    items = stats.top_genres(db, query.window, limit, listener_id)
    return TopGenresResponse(
        window=stats.window_out(query.window), data_as_of=query.data_as_of, items=items
    )


@router.get("/daily", response_model=DailyPlaysResponse)
def daily_plays(
    query: StatsQueryDep,
    listener_id: int | None = ListenerFilter,
    db: Session = Depends(get_db),
):
    """Plays per UTC day. Requires both `from` and `to`; days without plays have plays=0."""
    items = stats.daily_plays(db, query.window, listener_id)
    return DailyPlaysResponse(
        window=stats.window_out(query.window), data_as_of=query.data_as_of, items=items
    )


@router.get("/sessions", response_model=SessionStats)
def session_stats(
    query: StatsQueryDep,
    listener_id: int | None = ListenerFilter,
    db: Session = Depends(get_db),
):
    """Listening sessions: plays with gaps of at most 30 minutes (ADR 0010).

    A session counts in the window of the UTC day it started on.
    """
    values = sessions.session_stats(db, query.window, listener_id)
    return SessionStats(
        window=stats.window_out(query.window), data_as_of=query.data_as_of, **values
    )


DirectionQuery = Query("rising", description="rising: biggest growth first; falling: biggest drop")


@router.get("/trending-artists", response_model=TrendResponse)
def trending_artists(
    query: StatsQueryDep,
    direction: trends.Direction = DirectionQuery,
    limit: TopLimit = 10,
    listener_id: int | None = ListenerFilter,
    db: Session = Depends(get_db),
):
    """Plays in the window compared with the previous window of the same length (ADR 0011).

    Requires both `from` and `to`.
    """
    items = trends.trending_artists(db, query.window, direction, limit, listener_id)
    return _trend_response(query, direction, items)


@router.get("/trending-genres", response_model=TrendResponse)
def trending_genres(
    query: StatsQueryDep,
    direction: trends.Direction = DirectionQuery,
    limit: TopLimit = 10,
    listener_id: int | None = ListenerFilter,
    db: Session = Depends(get_db),
):
    """Like /trending-artists; a play counts towards every genre of its artist."""
    items = trends.trending_genres(db, query.window, direction, limit, listener_id)
    return _trend_response(query, direction, items)


def _trend_response(query, direction: str, items) -> TrendResponse:
    return TrendResponse(
        window=stats.window_out(query.window),
        previous_window=stats.window_out(trends.previous_window(query.window)),
        data_as_of=query.data_as_of,
        direction=direction,
        items=items,
    )
