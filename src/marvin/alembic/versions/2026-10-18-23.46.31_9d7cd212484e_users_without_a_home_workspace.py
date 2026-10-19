"""users without a home workspace

``users.group_id`` (the home workspace) becomes nullable and its foreign key ``ON DELETE SET NULL``, so a user can
have no home — Admin-created, OIDC and LDAP sign-ups start that way — and deleting a workspace clears the homes
pointing at it instead of being refused. Existing homes are kept.

Downgrade restores NOT NULL: a user left without a home is given the platform workspace (else the first workspace
by name) first. With no workspace at all it can't, and says so.

Revision ID: 9d7cd212484e
Revises: 3442416ae2bd
Create Date: 2026-10-18 23:46:31.114872

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "9d7cd212484e"
down_revision: str | None = "3442416ae2bd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# SQLite stores the original foreign key unnamed; the convention names it while the table is rebuilt so it can be
# dropped. Postgres has its own name for it, read from the database below.
CONVENTION = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
FK = "fk_users_group_id_groups"


def _home_fk_name(bind: sa.engine.Connection) -> str:
    for fk in sa.inspect(bind).get_foreign_keys("users"):
        if fk["constrained_columns"] == ["group_id"]:
            return fk["name"] or FK
    return FK


def upgrade() -> None:
    old_fk = _home_fk_name(op.get_bind())
    with op.batch_alter_table("users", schema=None, naming_convention=CONVENTION) as batch_op:
        batch_op.alter_column("group_id", existing_type=marvin.db.migration_types.GUID(), nullable=True)
        batch_op.drop_constraint(old_fk, type_="foreignkey")
        batch_op.create_foreign_key(FK, "groups", ["group_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    bind = op.get_bind()
    users = sa.table("users", sa.column("group_id", marvin.db.migration_types.GUID()))
    groups = sa.table("groups", sa.column("id", marvin.db.migration_types.GUID()), sa.column("name", sa.String()))
    if bind.execute(sa.select(sa.func.count()).select_from(users).where(users.c.group_id.is_(None))).scalar():
        fallback = None
        if "is_platform" in {c["name"] for c in sa.inspect(bind).get_columns("groups")}:
            platform = sa.table("groups", sa.column("id", marvin.db.migration_types.GUID()), sa.column("is_platform", sa.Boolean()))
            fallback = bind.execute(sa.select(platform.c.id).where(platform.c.is_platform.is_(True))).scalar()
        if fallback is None:
            fallback = bind.execute(sa.select(groups.c.id).order_by(groups.c.name).limit(1)).scalar()
        if fallback is None:
            raise RuntimeError("Users have no home workspace and no workspace exists to give them: create one first.")
        bind.execute(users.update().where(users.c.group_id.is_(None)).values(group_id=fallback))

    old_fk = _home_fk_name(bind)
    with op.batch_alter_table("users", schema=None, naming_convention=CONVENTION) as batch_op:
        batch_op.drop_constraint(old_fk, type_="foreignkey")
        batch_op.create_foreign_key(FK, "groups", ["group_id"], ["id"])
        batch_op.alter_column("group_id", existing_type=marvin.db.migration_types.GUID(), nullable=False)
