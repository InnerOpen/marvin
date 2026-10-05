"""media_embed_cache

The platform-wide cache of resolved media embeds (``MediaEmbedCacheModel``): one row per link as
written, filled by the editor's resolve endpoint and the save-time listener, read by the publishing
API (which never calls a provider). Additive — safe on Postgres and SQLite.

Revision ID: a78a8895a6a1
Revises: d5b1e8a3c7f2
Create Date: 2026-10-05 16:07:26.906966

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types as mt

# revision identifiers, used by Alembic.
revision: str = "a78a8895a6a1"
down_revision: str | None = "d5b1e8a3c7f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_embed_cache",
        sa.Column("id", mt.GUID(), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("embed_src", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("author_name", sa.Text(), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("aspect_ratio", sa.String(length=16), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("fetched_at", mt.NaiveDateTime(), nullable=False),
        sa.Column("expires_at", mt.NaiveDateTime(), nullable=False),
        sa.Column("created_at", mt.NaiveDateTime(), nullable=True),
        sa.Column("update_at", mt.NaiveDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url_hash", name="uq_media_embed_cache_url_hash"),
    )
    with op.batch_alter_table("media_embed_cache", schema=None) as batch_op:
        batch_op.create_index("ix_media_embed_cache_created_at", ["created_at"], unique=False)
        batch_op.create_index("ix_media_embed_cache_expires_at", ["expires_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("media_embed_cache", schema=None) as batch_op:
        batch_op.drop_index("ix_media_embed_cache_expires_at")
        batch_op.drop_index("ix_media_embed_cache_created_at")
    op.drop_table("media_embed_cache")
