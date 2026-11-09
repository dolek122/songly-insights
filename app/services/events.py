"""Import and list listening events. Idempotency rules are described in ADR 0002."""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.errors import UnprocessableError
from app.models import Listener, ListeningEvent, Track
from app.schemas.events import BulkImportResult, ListeningEventIn
from app.services.time_window import TimeWindow, to_utc


def _check_references(session: Session, events: Sequence[ListeningEventIn]) -> None:
    """Fail with a readable 422 instead of a foreign key error from the database."""
    listener_ids = {e.listener_id for e in events}
    track_ids = {e.track_id for e in events}
    found_listeners = set(session.scalars(select(Listener.id).where(Listener.id.in_(listener_ids))))
    found_tracks = set(session.scalars(select(Track.id).where(Track.id.in_(track_ids))))
    missing = {
        "listener_ids": sorted(listener_ids - found_listeners),
        "track_ids": sorted(track_ids - found_tracks),
    }
    if missing["listener_ids"] or missing["track_ids"]:
        raise UnprocessableError(
            "Events reference unknown listeners or tracks",
            details=missing,
            code="unknown_reference",
        )


def import_events(session: Session, events: Sequence[ListeningEventIn]) -> BulkImportResult:
    """Insert events, silently skipping ones that already exist.

    Idempotent: sending the same batch again inserts nothing and returns duplicates == received.
    It relies on the unique constraint (listener_id, track_id, listened_at) and PostgreSQL's
    INSERT ... ON CONFLICT DO NOTHING, so it is also safe when two imports run at the same time.
    """
    _check_references(session, events)
    rows = [
        {
            "listener_id": e.listener_id,
            "track_id": e.track_id,
            "listened_at": to_utc(e.listened_at),
        }
        for e in events
    ]
    stmt = (
        pg_insert(ListeningEvent)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_listening_events_natural_key")
        # RETURNING gives back only the rows that were really inserted.
        .returning(ListeningEvent.id)
    )
    inserted = len(session.scalars(stmt).all())
    session.commit()
    return BulkImportResult(received=len(rows), inserted=inserted, duplicates=len(rows) - inserted)


def list_events(
    session: Session,
    window: TimeWindow,
    limit: int,
    offset: int,
    listener_id: int | None = None,
) -> tuple[list[ListeningEvent], int]:
    stmt = select(ListeningEvent).where(window.filter(ListeningEvent.listened_at))
    if listener_id is not None:
        stmt = stmt.where(ListeningEvent.listener_id == listener_id)
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    page = stmt.order_by(ListeningEvent.listened_at, ListeningEvent.id).limit(limit).offset(offset)
    return list(session.scalars(page)), total
