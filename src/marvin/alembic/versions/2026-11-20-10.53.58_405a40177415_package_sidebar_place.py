"""where a package shows in the app sidebar: under Collections, in a section of its own, or not at all

Adds ``workspace_packages.sidebar`` (string, not null, server default ``collections``): the workspace's choice of where the
sidebar lists a package's collections and view links. Every package installed before this is ``collections`` (a group
inside the Collections fold); one that wants the section it had before is switched on the Packages page.

Downgrade drops the column.

Revision ID: 405a40177415
Revises: b7596d29dc7c
Create Date: 2026-11-20 10:53:58.801238

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "405a40177415"
down_revision: str | None = "b7596d29dc7c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workspace_packages", schema=None) as batch_op:
        batch_op.add_column(sa.Column("sidebar", sa.String(length=16), server_default="collections", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("workspace_packages", schema=None) as batch_op:
        batch_op.drop_column("sidebar")
