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
    mbid: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    genres: Mapped[list[Genre]] = relationship(
        secondary=artist_genres, lazy="selectin", order_by=Genre.name
    )


class Track(Base):
    __tablename__ = "tracks"
    __table_args__ = (CheckConstraint("duration_ms > 0", name="duration_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id"), index=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    mbid: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    artist: Mapped[Artist] = relationship(lazy="joined")


class Listener(Base):
    __tablename__ = "listeners"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    country: Mapped[str | None] = mapped_column(String(2))
    listenbrainz_user: Mapped[str | None] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ListeningEvent(Base):
    __tablename__ = "listening_events"
    __table_args__ = (
        UniqueConstraint(
            "listener_id", "track_id", "listened_at", name="uq_listening_events_natural_key"
        ),
        Index("ix_listening_events_listener_listened_at", "listener_id", "listened_at"),
        Index("ix_listening_events_listened_at", "listened_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    listener_id: Mapped[int] = mapped_column(ForeignKey("listeners.id", ondelete="CASCADE"))
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id"), index=True)
    listened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
