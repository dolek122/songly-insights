from pydantic import BaseModel, ConfigDict


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
