"""Writes a SyntheticDataset to the database."""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Artist, Genre, Listener, Track
from app.schemas.events import MAX_EVENTS_PER_IMPORT, ListeningEventIn
from app.seed.generator import SyntheticDataset
from app.services.events import import_events

# Order does not matter for TRUNCATE ... CASCADE, but listing every table makes it explicit.
TABLES = ["listening_events", "tracks", "artist_genres", "artists", "genres", "listeners"]


@dataclass
class LoadResult:
    genres: int
    artists: int
    tracks: int
    listeners: int
    events_inserted: int
    events_duplicates: int


def reset(session: Session) -> None:
    """Delete all data (keeps the schema). RESTART IDENTITY makes ids start at 1 again."""
    session.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
    session.commit()


def load(session: Session, data: SyntheticDataset) -> LoadResult:
    genres = {name: Genre(name=name) for name in data.genres}
    artists = [Artist(name=a.name, genres=[genres[g] for g in a.genres]) for a in data.artists]
    tracks = [
        Track(title=t.title, artist=artists[t.artist_index], duration_ms=t.duration_ms)
        for t in data.tracks
    ]
    listeners = [Listener(username=u, country=c) for u, c in data.listeners]
    session.add_all([*genres.values(), *artists, *tracks, *listeners])
    session.commit()  # after commit every object has its database id

    # Events go through the same idempotent import as the API, so running the seed
    # twice without --reset does not duplicate plays.
    events = [
        ListeningEventIn(
            listener_id=listeners[e.listener_index].id,
            track_id=tracks[e.track_index].id,
            listened_at=e.listened_at,
        )
        for e in data.events
    ]
    inserted = duplicates = 0
    for i in range(0, len(events), MAX_EVENTS_PER_IMPORT):
        result = import_events(session, events[i : i + MAX_EVENTS_PER_IMPORT])
        inserted += result.inserted
        duplicates += result.duplicates

    return LoadResult(
        genres=len(genres),
        artists=len(artists),
        tracks=len(tracks),
        listeners=len(listeners),
        events_inserted=inserted,
        events_duplicates=duplicates,
    )
