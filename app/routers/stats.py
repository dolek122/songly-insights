from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.deps import StatsQueryDep, TopLimit
from app.schemas.stats import (
    DailyPlaysResponse,
    DataRange,
    SessionStats,
    TopArtistsResponse,
    TopGenresResponse,
    TopTracksResponse,
    TrendResponse,
)
from app.services import sessions, stats, trends

router = APIRouter(prefix="/stats", tags=["stats"])

ListenerFilter = Query(None, description="Only plays of this listener")


@router.get("/data-range", response_model=DataRange)
def data_range(db: Session = Depends(get_db)):
    data_as_of = stats.marts_built_at(db)
    first_day, last_day = stats.data_range(db)
    return DataRange(first_day=first_day, last_day=last_day, data_as_of=data_as_of)


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
