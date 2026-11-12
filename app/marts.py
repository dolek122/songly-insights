"""Tables of the `marts` schema, as the API sees them (read-only). See ADR 0007.

They use their own MetaData on purpose: marts are created by the pipeline
(pipeline/sql/marts.sql), not by Alembic, so they must not be part of Base.metadata
(otherwise autogenerate would try to create them in a migration).
Keep these definitions in sync with pipeline/sql/marts.sql.
"""

from sqlalchemy import BigInteger, Column, Date, DateTime, Integer, MetaData, Table

marts_metadata = MetaData(schema="marts")

# One row per (UTC day, listener, track).
listener_track_daily = Table(
    "listener_track_daily",
    marts_metadata,
    Column("day", Date, primary_key=True),
    Column("listener_id", Integer, primary_key=True),
    Column("track_id", Integer, primary_key=True),
    Column("artist_id", Integer),
    Column("plays", BigInteger),
    Column("listening_ms", BigInteger),
    Column("first_listened_at", DateTime(timezone=True)),
    Column("last_listened_at", DateTime(timezone=True)),
)

# A single row with the time the marts were built.
build_info = Table(
    "build_info",
    marts_metadata,
    Column("built_at", DateTime(timezone=True)),
)
