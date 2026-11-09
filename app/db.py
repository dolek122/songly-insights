"""Database engine, session factory and the FastAPI dependency that hands out sessions."""

from collections.abc import Iterator

from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

# Predictable constraint names (e.g. "uq_listeners_username") instead of names invented by
# PostgreSQL. Future migrations can then drop or change a constraint by a known name.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Parent class of all ORM models. Alembic reads Base.metadata to autogenerate migrations."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# pool_pre_ping checks a pooled connection before using it, so a restarted database
# does not cause "connection closed" errors on the first request.
engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """One session per request; it is always closed, even when the endpoint raises."""
    with SessionLocal() as session:
        yield session
