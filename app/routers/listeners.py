from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.deps import PaginationDep, TimeWindowDep
from app.schemas.catalog import ListenerCreate, ListenerOut
from app.schemas.common import Page
from app.schemas.stats import ListenerSummary
from app.services import catalog, stats

router = APIRouter(prefix="/listeners", tags=["listeners"])


@router.get("", response_model=Page[ListenerOut])
def list_listeners(page: PaginationDep, db: Session = Depends(get_db)):
    items, total = catalog.list_listeners(db, page.limit, page.offset)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.get("/{listener_id}", response_model=ListenerOut)
def get_listener(listener_id: int, db: Session = Depends(get_db)):
    return catalog.get_listener(db, listener_id)


@router.post("", response_model=ListenerOut, status_code=status.HTTP_201_CREATED)
def create_listener(data: ListenerCreate, db: Session = Depends(get_db)):
    return catalog.create_listener(db, data)


@router.get("/{listener_id}/summary", response_model=ListenerSummary)
def listener_summary(listener_id: int, window: TimeWindowDep, db: Session = Depends(get_db)):
    return stats.listener_summary(db, listener_id, window)
