"""raw table for ListenBrainz listens

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-12

Pages of a user's listens from /1/user/<name>/listens, stored exactly as received
(ADR 0009). Written by hand, like 0002 and 0003: raw tables are not ORM models.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "listenbrainz_listens",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("user_name", sa.Text(), nullable=False),
        # The `max_ts` sent in the request (NULL for the newest page).
        sa.Column("max_ts", sa.BigInteger(), nullable=True),
        sa.Column("request_url", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "loaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        schema="raw",
    )
    op.create_index(
        "ix_listenbrainz_listens_user_name", "listenbrainz_listens", ["user_name"], schema="raw"
    )


def downgrade() -> None:
    # staging views read this table, so drop them first; the pipeline recreates them.
    op.execute("DROP SCHEMA IF EXISTS marts CASCADE")
    op.execute("DROP SCHEMA IF EXISTS staging CASCADE")
    op.drop_table("listenbrainz_listens", schema="raw")
