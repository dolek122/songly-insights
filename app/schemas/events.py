from pydantic import AwareDatetime, BaseModel, Field

from app.schemas.common import OrmModel

# One import is a single INSERT with 3 parameters per event. PostgreSQL allows at most
# 65 535 parameters per statement, so 10 000 events (30 000 parameters) is a safe limit.
MAX_EVENTS_PER_IMPORT = 10_000


class ListeningEventIn(BaseModel):
    listener_id: int
    track_id: int
    # AwareDatetime rejects timestamps without a time zone: stored data must be unambiguous.
    listened_at: AwareDatetime


class BulkImportRequest(BaseModel):
    events: list[ListeningEventIn] = Field(min_length=1, max_length=MAX_EVENTS_PER_IMPORT)


class BulkImportResult(BaseModel):
    received: int
    inserted: int
    # Events that already existed (same listener, track and time) and were skipped.
    duplicates: int


class ListeningEventOut(OrmModel):
    id: int
    listener_id: int
    track_id: int
    listened_at: AwareDatetime
