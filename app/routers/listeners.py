from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.deps import PaginationDep, StatsQueryDep, TopLimit
from app.schemas.catalog import ListenerCreate, ListenerOut
from app.schemas.common import Page
from app.schemas.stats import ListenerSessionsResponse, ListenerSummary, SimilarListenersResponse
from app.services import catalog, sessions, similarity, stats

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
def listener_summary(listener_id: int, query: StatsQueryDep, db: Session = Depends(get_db)):
    """Read from marts, like /stats: whole UTC days, data as of the last pipeline run."""
    return stats.listener_summary(db, listener_id, query.window, query.data_as_of)


@router.get("/{listener_id}/sessions", response_model=ListenerSessionsResponse)
def listener_sessions(
    listener_id: int, query: StatsQueryDep, page: PaginationDep, db: Session = Depends(get_db)
):
    """Listening sessions of one listener, newest first (ADR 0010)."""
    items, total = sessions.list_sessions(db, listener_id, query.window, page.limit, page.offset)
    return ListenerSessionsResponse(
        listener_id=listener_id,
        window=stats.window_out(query.window),
        data_as_of=query.data_as_of,
        total=total,
        limit=page.limit,
        offset=page.offset,
        items=items,
    )


@router.get("/{listener_id}/similar", response_model=SimilarListenersResponse)
def similar_listeners(
    listener_id: int, query: StatsQueryDep, limit: TopLimit = 10, db: Session = Depends(get_db)
):
    """Listeners with the most similar taste (cosine similarity of artist plays, ADR 0012)."""
    items = similarity.similar_listeners(db, listener_id, query.window, limit)
    return SimilarListenersResponse(
        listener_id=listener_id,
        window=stats.window_out(query.window),
        data_as_of=query.data_as_of,
        items=items,
    )
