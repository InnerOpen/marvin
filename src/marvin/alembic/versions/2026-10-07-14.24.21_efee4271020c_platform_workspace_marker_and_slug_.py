"""platform workspace marker and slug aliases: groups.is_platform, group_slug_aliases

The platform (admin's) workspace was found by name (``settings.DEFAULT_GROUP``, "Default"), so it
couldn't be renamed. It is now the one group with ``is_platform`` true, enforced by the partial unique
index ``uq_groups_is_platform`` (Postgres and SQLite both support partial indexes).

Backfill: the group named ``settings.DEFAULT_GROUP`` gets the marker — or, failing that, the one named
"Default" (that setting's built-in value, in case the env var changed since the install) — and if
neither exists, the oldest group does. Idempotent: a database that already has a platform workspace is
left alone.

``group_slug_aliases``: slugs a workspace had before a rename, so old Publishing API URLs, CLI
arguments and backup names keep resolving to it (services/group/workspace_rename.py).

Additive — safe on Postgres and SQLite.

Revision ID: efee4271020c
Revises: 59d0896537fa
Create Date: 2026-10-07 14:24:21.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types as mt

# revision identifiers, used by Alembic.
revision: str = "efee4271020c"
down_revision: str | None = "59d0896537fa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_LEGACY_NAME = "Default"  # DEFAULT_GROUP's built-in value


def _candidate_names() -> list[str]:
    try:
        from marvin.core.config import get_app_settings

        configured = get_app_settings().DEFAULT_GROUP
    except Exception:  # settings unavailable: the legacy name alone
        configured = _LEGACY_NAME
    return list(dict.fromkeys([configured, _LEGACY_NAME]))


def upgrade() -> None:
    op.create_table(
        "group_slug_aliases",
        sa.Column("id", mt.GUID(), nullable=False),
        sa.Column("group_id", mt.GUID(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("created_at", mt.NaiveDateTime(), nullable=True),
        sa.Column("update_at", mt.NaiveDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    with op.batch_alter_table("group_slug_aliases") as batch:
        batch.create_index("ix_group_slug_aliases_created_at", ["created_at"], unique=False)
        batch.create_index("ix_group_slug_aliases_group_id", ["group_id"], unique=False)

    with op.batch_alter_table("groups") as batch:
        batch.add_column(sa.Column("is_platform", sa.Boolean(), server_default=sa.false(), nullable=False))

    conn = op.get_bind()
    groups = sa.table(
        "groups",
        sa.column("id", mt.GUID()),
        sa.column("name", sa.String),
        sa.column("created_at", mt.NaiveDateTime()),
        sa.column("is_platform", sa.Boolean),
    )
    if conn.execute(sa.select(groups.c.id).where(groups.c.is_platform.is_(True)).limit(1)).first() is None:
        platform_id = None
        for name in _candidate_names():
            platform_id = conn.execute(sa.select(groups.c.id).where(groups.c.name == name)).scalar()
            if platform_id is not None:
                break
        if platform_id is None:  # renamed or never created under that name: the first workspace made
            oldest = sa.select(groups.c.id).order_by(groups.c.created_at.is_(None), groups.c.created_at, groups.c.id).limit(1)
            platform_id = conn.execute(oldest).scalar()
        if platform_id is not None:  # an empty database gets its platform workspace from init_db
            conn.execute(sa.update(groups).where(groups.c.id == platform_id).values(is_platform=True))

    with op.batch_alter_table("groups") as batch:
        batch.create_index(
            "uq_groups_is_platform",
            ["is_platform"],
            unique=True,
            postgresql_where=sa.text("is_platform"),
            sqlite_where=sa.text("is_platform"),
        )


def downgrade() -> None:
    with op.batch_alter_table("groups") as batch:
        batch.drop_index("uq_groups_is_platform")
        batch.drop_column("is_platform")

    with op.batch_alter_table("group_slug_aliases") as batch:
        batch.drop_index("ix_group_slug_aliases_group_id")
        batch.drop_index("ix_group_slug_aliases_created_at")
    op.drop_table("group_slug_aliases")
