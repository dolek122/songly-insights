"""Create and read artists, tracks, genres and listeners."""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError, UnprocessableError
from app.models import Artist, Genre, Listener, Track
from app.schemas.catalog import ArtistCreate, GenreCreate, ListenerCreate, TrackCreate


def _paginate(session: Session, stmt, limit: int, offset: int) -> tuple[list, int]:
    """Run `stmt` for one page and count all rows it would return without paging."""
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    items = list(session.scalars(stmt.limit(limit).offset(offset)))
    return items, total


def _get_or_404(session: Session, model, object_id: int):
    obj = session.get(model, object_id)
    if obj is None:
        raise NotFoundError(f"{model.__name__} {object_id} not found")
    return obj


def _commit_or_conflict(session: Session, message: str) -> None:
    # The database enforces uniqueness. Checking "does it exist?" before inserting
    # would leave a race between two requests, so we insert and translate the error.
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(message) from exc


# --- genres ---------------------------------------------------------------------------------


def list_genres(session: Session) -> list[Genre]:
    return list(session.scalars(select(Genre).order_by(Genre.name)))


def create_genre(session: Session, data: GenreCreate) -> Genre:
    genre = Genre(name=data.name.strip().lower())
    session.add(genre)
    _commit_or_conflict(session, f"Genre '{genre.name}' already exists")
    return genre


# --- artists --------------------------------------------------------------------------------


def list_artists(
    session: Session, limit: int, offset: int, q: str | None = None
) -> tuple[list[Artist], int]:
    stmt = select(Artist).order_by(Artist.name, Artist.id)
    if q:
        # autoescape: a "%" or "_" typed by the user is matched literally, not as a wildcard.
        stmt = stmt.where(Artist.name.icontains(q, autoescape=True))
    return _paginate(session, stmt, limit, offset)


def get_artist(session: Session, artist_id: int) -> Artist:
    return _get_or_404(session, Artist, artist_id)


def create_artist(session: Session, data: ArtistCreate) -> Artist:
    genre_ids = set(data.genre_ids)
    # Sorted like the relationship (order_by=Genre.name), so the response matches a later GET.
    genres = list(
        session.scalars(select(Genre).where(Genre.id.in_(genre_ids)).order_by(Genre.name))
    )
    missing = sorted(genre_ids - {g.id for g in genres})
    if missing:
        raise UnprocessableError(
            "Unknown genre ids", details={"genre_ids": missing}, code="unknown_reference"
        )
    artist = Artist(name=data.name, mbid=str(data.mbid) if data.mbid else None, genres=genres)
    session.add(artist)
    _commit_or_conflict(session, "An artist with this mbid already exists")
    return artist


# --- tracks ---------------------------------------------------------------------------------


def list_tracks(
    session: Session, limit: int, offset: int, artist_id: int | None = None
) -> tuple[list[Track], int]:
    stmt = select(Track).order_by(Track.id)
    if artist_id is not None:
        stmt = stmt.where(Track.artist_id == artist_id)
    return _paginate(session, stmt, limit, offset)


def get_track(session: Session, track_id: int) -> Track:
    return _get_or_404(session, Track, track_id)


def create_track(session: Session, data: TrackCreate) -> Track:
    if session.get(Artist, data.artist_id) is None:
        raise UnprocessableError(
            "Unknown artist id", details={"artist_id": data.artist_id}, code="unknown_reference"
        )
    track = Track(
        title=data.title,
        artist_id=data.artist_id,
        duration_ms=data.duration_ms,
        mbid=str(data.mbid) if data.mbid else None,
    )
    session.add(track)
    _commit_or_conflict(session, "A track with this mbid already exists")
    return track


# --- listeners ------------------------------------------------------------------------------


def list_listeners(session: Session, limit: int, offset: int) -> tuple[list[Listener], int]:
    return _paginate(session, select(Listener).order_by(Listener.id), limit, offset)


def get_listener(session: Session, listener_id: int) -> Listener:
    return _get_or_404(session, Listener, listener_id)


def create_listener(session: Session, data: ListenerCreate) -> Listener:
    listener = Listener(username=data.username, country=data.country)
    session.add(listener)
    _commit_or_conflict(session, f"Username '{data.username}' is already taken")
    return listener
