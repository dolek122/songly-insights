from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.monitoring import refresh_data_metrics

router = APIRouter(tags=["monitoring"])


# include_in_schema=False: it is for Prometheus, not for API clients (/docs).
@router.get("/metrics", include_in_schema=False)
def metrics(db: Session = Depends(get_db)) -> Response:
    """Prometheus text format. Data gauges are refreshed from the database on each scrape."""
    refresh_data_metrics(db)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
