from pydantic import AwareDatetime, BaseModel, Field

from app.schemas.common import OrmModel

MAX_EVENTS_PER_IMPORT = 10_000


class ListeningEventIn(BaseModel):
    listener_id: int
    track_id: int
    listened_at: AwareDatetime


class BulkImportRequest(BaseModel):
    events: list[ListeningEventIn] = Field(min_length=1, max_length=MAX_EVENTS_PER_IMPORT)


class BulkImportResult(BaseModel):
    received: int
    inserted: int
    duplicates: int


class ListeningEventOut(OrmModel):
    id: int
    listener_id: int
    track_id: int
    listened_at: AwareDatetime
