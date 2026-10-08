"""assets: scope — the library, or Ask files

Adds `scope` ('library' | 'ask', default 'library', indexed). A file attached to a chat question in the bubble or
on the Ask page is an Ask file, kept out of the Assets library until moved there (services/assets/scope.py).

Backfill: an upload the bubble or Ask page sent (`metadata_json.attachedVia` is bubble / ask_page), or one the
Ask page uploaded before that marker existed (slug `ask-<name>-<base36 time>`), becomes 'ask' — unless an entry
already uses it, in which case it was filed and stays in the library. Additive; safe on Postgres and SQLite.

Revision ID: a6c2f19d4e70
Revises: c4e8a1f05b27
Create Date: 2026-10-08 21:00:00.000000

"""

import json
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6c2f19d4e70"
down_revision: str | None = "c4e8a1f05b27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ASK_SLUG = re.compile(r"^ask-.*-[0-9a-z]{8,}$")
ASK_SURFACES = {"bubble", "ask_page"}


def _was_attached_in_chat(slug: str, metadata) -> bool:
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            metadata = None
    if isinstance(metadata, dict) and metadata.get("attachedVia") in ASK_SURFACES:
        return True
    return bool(ASK_SLUG.match(slug or ""))


def upgrade() -> None:
    with op.batch_alter_table("assets", schema=None) as batch_op:
        batch_op.add_column(sa.Column("scope", sa.String(), nullable=False, server_default="library"))
        batch_op.create_index("ix_assets_scope", ["scope"], unique=False)

    bind = op.get_bind()
    used = {row[0] for row in bind.execute(sa.text("SELECT DISTINCT asset_id FROM entry_assets"))}
    ask = [
        row.id
        for row in bind.execute(sa.text("SELECT id, slug, metadata_json FROM assets WHERE slug LIKE 'ask-%'"))
        if row.id not in used and _was_attached_in_chat(row.slug, row.metadata_json)
    ]
    for asset_id in ask:
        bind.execute(sa.text("UPDATE assets SET scope = 'ask' WHERE id = :id"), {"id": asset_id})


def downgrade() -> None:
    with op.batch_alter_table("assets", schema=None) as batch_op:
        batch_op.drop_index("ix_assets_scope")
        batch_op.drop_column("scope")
