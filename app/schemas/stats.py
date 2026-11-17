from datetime import date, datetime

from pydantic import BaseModel, Field


class Window(BaseModel):
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


class StatsResponse(BaseModel):
    window: Window
    data_as_of: datetime


class TopTracksResponse(StatsResponse):
    items: list[TopTrack]


class TopArtistsResponse(StatsResponse):
    items: list[TopArtist]


class TopGenresResponse(StatsResponse):
    items: list[TopGenre]


class DailyPlaysResponse(StatsResponse):
    items: list[DailyPlays]


class ListenerSummary(StatsResponse):
    listener_id: int
    total_plays: int
    unique_tracks: int
    unique_artists: int
    total_listening_ms: int
    first_listened_at: datetime | None
    last_listened_at: datetime | None
    top_artist: TopArtist | None
    top_genre: TopGenre | None


class ListeningSession(BaseModel):
    started_at: datetime
    ended_at: datetime
    duration_minutes: float
    plays: int
    unique_tracks: int
    unique_artists: int
    listening_ms: int | None


class ListenerSessionsResponse(StatsResponse):
    listener_id: int
    total: int
    limit: int
    offset: int
    items: list[ListeningSession]


class SessionStats(StatsResponse):
    sessions: int
    avg_plays: float | None
    avg_duration_minutes: float | None
    median_duration_minutes: float | None
    longest_duration_minutes: float | None


class TrendItem(BaseModel):
    id: int
    name: str
    plays: int
    previous_plays: int
    change: int
    change_pct: float | None


class TrendResponse(StatsResponse):
    previous_window: Window
    direction: str
    items: list[TrendItem]


class SharedArtist(BaseModel):
    artist_id: int
    name: str


class SimilarListener(BaseModel):
    listener_id: int
    username: str
    similarity: float
    shared_artists: int
    top_shared_artists: list[SharedArtist]


class SimilarListenersResponse(StatsResponse):
    listener_id: int
    items: list[SimilarListener]
