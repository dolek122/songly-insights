"""raw table for MusicBrainz recordings

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-12

Recordings of each MusicBrainz artist, downloaded with the browse endpoint
(/ws/2/recording?artist=<mbid>) and stored exactly as received (ADR 0008).
Written by hand, like 0002: raw tables are not ORM models.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "musicbrainz_recording_browse",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("artist_mbid", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("page_offset", sa.Integer(), nullable=False),
        sa.Column("request_url", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "loaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        schema="raw",
    )
    op.create_index(
        "ix_musicbrainz_recording_browse_request_url",
        "musicbrainz_recording_browse",
        ["request_url", "loaded_at"],
        schema="raw",
    )


def downgrade() -> None:
    # staging views read this table, so drop them first; the pipeline recreates them.
    op.execute("DROP SCHEMA IF EXISTS marts CASCADE")
    op.execute("DROP SCHEMA IF EXISTS staging CASCADE")
    op.drop_table("musicbrainz_recording_browse", schema="raw")
