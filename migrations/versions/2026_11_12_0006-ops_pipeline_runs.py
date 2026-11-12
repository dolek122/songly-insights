"""ops schema: history of pipeline runs

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-12

One row per pipeline run with its result and data quality summary (ADR 0014).
The API exposes the newest row as Prometheus metrics, so monitoring can alert
when the pipeline fails or stops running. Written by hand: not an ORM model.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA ops")
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("flow_run_id", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        # running -> completed | failed
        sa.Column("status", sa.Text(), nullable=False, server_default="running"),
        sa.Column("dq_warnings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dq_errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')", name="ck_pipeline_runs_status"
        ),
        schema="ops",
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA ops CASCADE")
