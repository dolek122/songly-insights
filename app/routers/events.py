from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.deps import PaginationDep, TimeWindowDep
from app.schemas.common import Page
from app.schemas.events import BulkImportRequest, BulkImportResult, ListeningEventOut
from app.services import events

router = APIRouter(prefix="/listening-events", tags=["listening events"])


@router.post("/bulk", response_model=BulkImportResult)
def import_events(data: BulkImportRequest, db: Session = Depends(get_db)):
    """Idempotent import: events that already exist are skipped and counted as duplicates.

    Returns 200 (not 201) because a repeated call may create nothing.
    """
    return events.import_events(db, data.events)


@router.get("", response_model=Page[ListeningEventOut])
def list_events(
    page: PaginationDep,
    window: TimeWindowDep,
    listener_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    items, total = events.list_events(db, window, page.limit, page.offset, listener_id)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)
