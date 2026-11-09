from pydantic import BaseModel, ConfigDict


class Page[T](BaseModel):
    """A page of results plus what is needed to ask for the next one."""

    items: list[T]
    total: int
    limit: int
    offset: int


class OrmModel(BaseModel):
    # from_attributes lets Pydantic read values from SQLAlchemy objects (obj.name, ...).
    model_config = ConfigDict(from_attributes=True)
