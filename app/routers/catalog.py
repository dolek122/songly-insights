"""Artists, tracks and genres. Routers only translate HTTP <-> service calls."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.deps import PaginationDep
from app.schemas.catalog import (
    ArtistCreate,
    ArtistOut,
    GenreCreate,
    GenreOut,
    TrackCreate,
    TrackOut,
)
from app.schemas.common import Page
from app.services import catalog

router = APIRouter(tags=["catalog"])


@router.get("/genres", response_model=list[GenreOut])
def list_genres(db: Session = Depends(get_db)):
    return catalog.list_genres(db)


@router.post("/genres", response_model=GenreOut, status_code=status.HTTP_201_CREATED)
def create_genre(data: GenreCreate, db: Session = Depends(get_db)):
    return catalog.create_genre(db, data)


@router.get("/artists", response_model=Page[ArtistOut])
def list_artists(
    page: PaginationDep,
    q: str | None = Query(None, min_length=1, max_length=100, description="Search by name"),
    db: Session = Depends(get_db),
):
    items, total = catalog.list_artists(db, page.limit, page.offset, q)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.get("/artists/{artist_id}", response_model=ArtistOut)
def get_artist(artist_id: int, db: Session = Depends(get_db)):
    return catalog.get_artist(db, artist_id)


@router.post("/artists", response_model=ArtistOut, status_code=status.HTTP_201_CREATED)
def create_artist(data: ArtistCreate, db: Session = Depends(get_db)):
    return catalog.create_artist(db, data)


@router.get("/tracks", response_model=Page[TrackOut])
def list_tracks(
    page: PaginationDep,
    artist_id: int | None = Query(None, description="Only tracks of this artist"),
    db: Session = Depends(get_db),
):
    items, total = catalog.list_tracks(db, page.limit, page.offset, artist_id)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.get("/tracks/{track_id}", response_model=TrackOut)
def get_track(track_id: int, db: Session = Depends(get_db)):
    return catalog.get_track(db, track_id)


@router.post("/tracks", response_model=TrackOut, status_code=status.HTTP_201_CREATED)
def create_track(data: TrackCreate, db: Session = Depends(get_db)):
    return catalog.create_track(db, data)
