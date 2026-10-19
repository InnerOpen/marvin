"""drop groups is_platform

The platform (admin's) workspace stops being special: ``groups.is_platform`` and its partial unique index
``uq_groups_is_platform`` go, so that workspace is deleted like any other. Platform alerts, SMTP and secrets already
live in ``platform_settings`` / NULL-group secrets (migrations ``d6896d6a5e2e`` and ``3442416ae2bd``).

Before the column goes, the workspace that carried the marker is recorded as ``{id, name}`` in
``platform_settings.retired_platform_workspace`` (nothing reads it; it is for the people who run the install and for
the downgrade). With no marked workspace nothing is recorded.

Downgrade re-adds the column and the index and marks the recorded workspace again, if it still exists (a deleted
workspace can't be brought back), then forgets the record.

Revision ID: a225a6254088
Revises: 9d7cd212484e
Create Date: 2026-10-19 00:45:24.916708

"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types as mt

# revision identifiers, used by Alembic.
revision: str = "a225a6254088"
down_revision: str | None = "9d7cd212484e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KEY = "retired_platform_workspace"
INDEX = "uq_groups_is_platform"


def _settings() -> sa.TableClause:
    return sa.table(
        "platform_settings",
        sa.column("id", mt.GUID()),
        sa.column("key", sa.String()),
        sa.column("value_json", sa.JSON()),
        sa.column("created_at", sa.DateTime()),
        sa.column("update_at", sa.DateTime()),
    )


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def upgrade() -> None:
    bind = op.get_bind()
    groups = sa.table("groups", sa.column("id", mt.GUID()), sa.column("name", sa.String()), sa.column("is_platform", sa.Boolean()))
    settings = _settings()

    marked = bind.execute(sa.select(groups.c.id, groups.c.name).where(groups.c.is_platform.is_(True))).first()
    if marked is not None:
        value = {"id": str(marked.id if isinstance(marked.id, uuid.UUID) else uuid.UUID(str(marked.id))), "name": marked.name}
        if bind.execute(sa.select(settings.c.id).where(settings.c.key == KEY)).first() is None:
            bind.execute(settings.insert().values(id=uuid.uuid4(), key=KEY, value_json=value, created_at=_now(), update_at=_now()))
        else:
            bind.execute(settings.update().where(settings.c.key == KEY).values(value_json=value, update_at=_now()))

    with op.batch_alter_table("groups", schema=None) as batch_op:
        batch_op.drop_index(INDEX)
        batch_op.drop_column("is_platform")


def downgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("groups", schema=None) as batch_op:
        batch_op.add_column(sa.Column("is_platform", sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.create_index(INDEX, ["is_platform"], unique=True, postgresql_where=sa.text("is_platform"), sqlite_where=sa.text("is_platform"))

    groups = sa.table("groups", sa.column("id", mt.GUID()), sa.column("is_platform", sa.Boolean()))
    settings = _settings()
    recorded = bind.execute(sa.select(settings.c.value_json).where(settings.c.key == KEY)).scalar()
    if isinstance(recorded, str):  # SQLite hands a JSON column back as text through a bare table
        import json

        recorded = json.loads(recorded)
    if recorded and recorded.get("id"):
        bind.execute(groups.update().where(groups.c.id == uuid.UUID(recorded["id"])).values(is_platform=True))
    bind.execute(settings.delete().where(settings.c.key == KEY))
