"""ops.backups: history of database backups

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-13

One row per backup made by deploy/backup/backup.sh (ADR 0017): file, size and whether
a test restore of it worked. The API exposes the newest result as metrics, so an alert
fires when backups stop. Written by hand: not an ORM model.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backups",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        # running -> completed | failed
        sa.Column("status", sa.Text(), nullable=False, server_default="running"),
        sa.Column("file_name", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        # True when the dump was restored into a throwaway database without errors.
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')", name="ck_backups_status"
        ),
        schema="ops",
    )


def downgrade() -> None:
    op.drop_table("backups", schema="ops")
