"""opaque storage keys: groups.storage_code, groups.asset_public_base_url, storage_key_aliases

- ``groups.storage_code``: the opaque, stable first segment of a workspace's new storage keys
  (services/storage/keys.py). Every existing workspace gets a random one here.
- ``groups.asset_public_base_url``: a platform admin's per-workspace public domain for files on a remote
  provider (empty: the provider's own).
- ``storage_key_aliases``: old keys of files ``storage_migrate --rekey`` moved, for redirects and
  ``--prune-old``.

Additive — safe on Postgres and SQLite.

Revision ID: 4e1b9c7a2d55
Revises: 7cb7b06de5e6
Create Date: 2026-10-07 12:00:00.000000
"""

import secrets
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types as mt

# revision identifiers, used by Alembic.
revision: str = "4e1b9c7a2d55"
down_revision: str | None = "7cb7b06de5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"  # keys.CODE_ALPHABET, frozen here


def _code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(12))


def upgrade() -> None:
    with op.batch_alter_table("groups") as batch:
        batch.add_column(sa.Column("storage_code", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("asset_public_base_url", sa.String(length=255), nullable=True))

    conn = op.get_bind()
    groups = sa.table("groups", sa.column("id", mt.GUID()), sa.column("storage_code", sa.String))
    taken: set[str] = set()
    for (gid,) in conn.execute(sa.select(groups.c.id)).all():
        code = _code()
        while code in taken:
            code = _code()
        taken.add(code)
        conn.execute(sa.update(groups).where(groups.c.id == gid).values(storage_code=code))

    with op.batch_alter_table("groups") as batch:
        batch.create_unique_constraint("uq_groups_storage_code", ["storage_code"])

    op.create_table(
        "storage_key_aliases",
        sa.Column("id", mt.GUID(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("current_key", sa.String(), nullable=False),
        sa.Column("asset_id", mt.GUID(), nullable=True),
        sa.Column("pack_id", mt.GUID(), nullable=True),
        sa.Column("pruned_at", mt.NaiveDateTime(), nullable=True),
        sa.Column("created_at", mt.NaiveDateTime(), nullable=True),
        sa.Column("update_at", mt.NaiveDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "storage_key", name="uq_storage_key_aliases_provider_key"),
    )
    with op.batch_alter_table("storage_key_aliases") as batch:
        batch.create_index("ix_storage_key_aliases_storage_key", ["storage_key"], unique=False)
        batch.create_index("ix_storage_key_aliases_asset_id", ["asset_id"], unique=False)
        batch.create_index("ix_storage_key_aliases_created_at", ["created_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("storage_key_aliases") as batch:
        batch.drop_index("ix_storage_key_aliases_created_at")
        batch.drop_index("ix_storage_key_aliases_asset_id")
        batch.drop_index("ix_storage_key_aliases_storage_key")
    op.drop_table("storage_key_aliases")
    with op.batch_alter_table("groups") as batch:
        batch.drop_constraint("uq_groups_storage_code", type_="unique")
        batch.drop_column("asset_public_base_url")
        batch.drop_column("storage_code")
