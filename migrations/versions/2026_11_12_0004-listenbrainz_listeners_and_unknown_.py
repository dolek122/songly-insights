from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("listeners", sa.Column("listenbrainz_user", sa.String(length=100), nullable=True))
    op.create_unique_constraint(
        op.f("uq_listeners_listenbrainz_user"), "listeners", ["listenbrainz_user"]
    )
    op.alter_column("tracks", "duration_ms", existing_type=sa.INTEGER(), nullable=True)


def downgrade() -> None:
    op.alter_column("tracks", "duration_ms", existing_type=sa.INTEGER(), nullable=False)
    op.drop_constraint(op.f("uq_listeners_listenbrainz_user"), "listeners", type_="unique")
    op.drop_column("listeners", "listenbrainz_user")
