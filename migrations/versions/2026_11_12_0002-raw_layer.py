from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA raw")
    op.create_table(
        "musicbrainz_artist_search",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("tag", sa.Text(), nullable=False),
        sa.Column("page_offset", sa.Integer(), nullable=False),
        sa.Column("request_url", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "loaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        schema="raw",
    )
    op.create_index(
        "ix_musicbrainz_artist_search_request_url",
        "musicbrainz_artist_search",
        ["request_url", "loaded_at"],
        schema="raw",
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS marts CASCADE")
    op.execute("DROP SCHEMA IF EXISTS staging CASCADE")
    op.execute("DROP SCHEMA raw CASCADE")
