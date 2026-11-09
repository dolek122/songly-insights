from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.deps import TimeWindowDep, TopLimit
from app.schemas.stats import (
    DailyPlaysResponse,
    TopArtistsResponse,
    TopGenresResponse,
    TopTracksResponse,
)
from app.services import stats

router = APIRouter(prefix="/stats", tags=["stats"])

ListenerFilter = Query(None, description="Only plays of this listener")


@router.get("/top-tracks", response_model=TopTracksResponse)
def top_tracks(
    window: TimeWindowDep,
    limit: TopLimit = 10,
    listener_id: int | None = ListenerFilter,
    db: Session = Depends(get_db),
):
    items = stats.top_tracks(db, window, limit, listener_id)
    return TopTracksResponse(window=stats.window_out(window), items=items)


@router.get("/top-artists", response_model=TopArtistsResponse)
def top_artists(
    window: TimeWindowDep,
    limit: TopLimit = 10,
    listener_id: int | None = ListenerFilter,
    db: Session = Depends(get_db),
):
    items = stats.top_artists(db, window, limit, listener_id)
    return TopArtistsResponse(window=stats.window_out(window), items=items)


@router.get("/top-genres", response_model=TopGenresResponse)
def top_genres(
    window: TimeWindowDep,
    limit: TopLimit = 10,
    listener_id: int | None = ListenerFilter,
    db: Session = Depends(get_db),
):
    """A play counts towards every genre of its artist, so the sum can exceed total plays."""
    items = stats.top_genres(db, window, limit, listener_id)
    return TopGenresResponse(window=stats.window_out(window), items=items)


@router.get("/daily", response_model=DailyPlaysResponse)
def daily_plays(
    window: TimeWindowDep,
    listener_id: int | None = ListenerFilter,
    db: Session = Depends(get_db),
):
    """Plays per UTC day. Requires both `from` and `to`; days without plays have plays=0."""
    items = stats.daily_plays(db, window, listener_id)
    return DailyPlaysResponse(window=stats.window_out(window), items=items)
