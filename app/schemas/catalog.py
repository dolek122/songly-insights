from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import OrmModel


class GenreCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class GenreOut(OrmModel):
    id: int
    name: str


class ArtistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    mbid: UUID | None = None
    genre_ids: list[int] = Field(default_factory=list, max_length=20)


class ArtistOut(OrmModel):
    id: int
    name: str
    mbid: UUID | None
    genres: list[GenreOut]
    created_at: datetime


class ArtistRef(OrmModel):
    """Short artist representation embedded in other objects."""

    id: int
    name: str


class TrackCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    artist_id: int
    duration_ms: int = Field(gt=0)
    mbid: UUID | None = None


class TrackOut(OrmModel):
    id: int
    title: str
    duration_ms: int
    mbid: UUID | None
    artist: ArtistRef
    created_at: datetime


class ListenerCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")


class ListenerOut(OrmModel):
    id: int
    username: str
    country: str | None
    created_at: datetime
