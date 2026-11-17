from sqlalchemy import BigInteger, Column, Date, DateTime, Integer, MetaData, Table

marts_metadata = MetaData(schema="marts")

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

build_info = Table(
    "build_info",
    marts_metadata,
    Column("built_at", DateTime(timezone=True)),
)

listening_sessions = Table(
    "listening_sessions",
    marts_metadata,
    Column("listener_id", Integer, primary_key=True),
    Column("started_at", DateTime(timezone=True), primary_key=True),
    Column("last_play_at", DateTime(timezone=True)),
    Column("ended_at", DateTime(timezone=True)),
    Column("day", Date),
    Column("plays", BigInteger),
    Column("unique_tracks", BigInteger),
    Column("unique_artists", BigInteger),
    Column("listening_ms", BigInteger),
)
