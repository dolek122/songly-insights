"""ORM models. Any change here needs a new Alembic migration (see CLAUDE.md)."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Many-to-many link between artists and genres. It has no extra columns,
# so a plain Table is enough (no model class needed).
artist_genres = Table(
    "artist_genres",
    Base.metadata,
    Column("artist_id", ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True),
    Column("genre_id", ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True),
)


class Genre(Base):
    __tablename__ = "genres"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class Artist(Base):
    __tablename__ = "artists"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    # MusicBrainz identifier. Empty for synthetic data, filled when importing MusicBrainz.
    mbid: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # lazy="selectin" loads genres with one extra query for all artists in a result,
    # which avoids the N+1 query problem when listing artists.
    genres: Mapped[list[Genre]] = relationship(
        secondary=artist_genres, lazy="selectin", order_by=Genre.name
    )


class Track(Base):
    __tablename__ = "tracks"
    __table_args__ = (CheckConstraint("duration_ms > 0", name="duration_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id"), index=True)
    # NULL = unknown length. The API always requires it, but tracks created from
    # ListenBrainz listens often come without one (ADR 0009). NULL passes the CHECK.
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    mbid: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    artist: Mapped[Artist] = relationship(lazy="joined")


class Listener(Base):
    __tablename__ = "listeners"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    # ISO 3166-1 alpha-2 code, e.g. "PL". Optional.
    country: Mapped[str | None] = mapped_column(String(2))
    # Set for listeners imported from ListenBrainz: links them to their account there.
    listenbrainz_user: Mapped[str | None] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ListeningEvent(Base):
    """One play of one track by one listener. See ADR 0002 for the uniqueness rule."""

    __tablename__ = "listening_events"
    __table_args__ = (
        # The natural key of an event. It makes the bulk import idempotent:
        # sending the same event twice cannot create a second row.
        UniqueConstraint(
            "listener_id", "track_id", "listened_at", name="uq_listening_events_natural_key"
        ),
        # Most statistics filter by listener and time window.
        Index("ix_listening_events_listener_listened_at", "listener_id", "listened_at"),
        # Global statistics filter by time window only.
        Index("ix_listening_events_listened_at", "listened_at"),
    )

    # BigInteger: events are the one table that can grow to many millions of rows.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    listener_id: Mapped[int] = mapped_column(ForeignKey("listeners.id", ondelete="CASCADE"))
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id"), index=True)
    # Always stored with a time zone (PostgreSQL keeps it as UTC internally).
    listened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
