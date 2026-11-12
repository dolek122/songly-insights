from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.deps import StatsQueryDep, TopLimit
from app.schemas.stats import (
    DailyPlaysResponse,
    TopArtistsResponse,
    TopGenresResponse,
    TopTracksResponse,
)
from app.services import stats

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
