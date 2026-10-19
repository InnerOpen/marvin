"""approval image

Revision ID: 4aa75d81d41f
Revises: c9d4e7a2b1f8
Create Date: 2026-10-13 23:33:53.934316

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "4aa75d81d41f"
down_revision: str | None = "c9d4e7a2b1f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Only the column: autogenerate also listed two created_at indexes (submission_rate_limits, workspace_agents)
    # that are known pre-existing drift between the models and the database; they are not this migration's to add.
    with op.batch_alter_table("workflow_approvals", schema=None) as batch_op:
        batch_op.add_column(sa.Column("image_url", sa.String(length=2000), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workflow_approvals", schema=None) as batch_op:
        batch_op.drop_column("image_url")
