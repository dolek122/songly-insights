from datetime import date, datetime

from pydantic import BaseModel, Field


class Window(BaseModel):
    """Echo of the time window used, so the client sees how its input was interpreted."""

    # `from` is a Python keyword, so the field is called from_ and renamed in JSON.
    from_: datetime | None = Field(serialization_alias="from")
    to: datetime | None


class TopTrack(BaseModel):
    track_id: int
    title: str
    artist_id: int
    artist_name: str
    plays: int


class TopArtist(BaseModel):
    artist_id: int
    name: str
    plays: int


class TopGenre(BaseModel):
    genre_id: int
    name: str
    plays: int


class DailyPlays(BaseModel):
    day: date
    plays: int


class TopTracksResponse(BaseModel):
    window: Window
    items: list[TopTrack]


class TopArtistsResponse(BaseModel):
    window: Window
    items: list[TopArtist]


class TopGenresResponse(BaseModel):
    window: Window
    items: list[TopGenre]


class DailyPlaysResponse(BaseModel):
    window: Window
    items: list[DailyPlays]


class ListenerSummary(BaseModel):
    listener_id: int
    window: Window
    total_plays: int
    unique_tracks: int
    unique_artists: int
    total_listening_ms: int
    first_listened_at: datetime | None
    last_listened_at: datetime | None
    top_artist: TopArtist | None
    top_genre: TopGenre | None
