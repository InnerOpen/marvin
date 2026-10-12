"""asset origin and source

Where an asset came from (upload | derived | generated) and, for a derived one, the asset it was made from — so the
library can fold versions under their original. Existing rows are filled in from the lineage their metadata already
carries (derived_from / generated_by, written by the media pipeline and workflow media steps).

Revision ID: d00dff591ea6
Revises: 9a3f6c2e1b84
Create Date: 2026-10-12 11:54:20.456393

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "d00dff591ea6"
down_revision: str | None = "9a3f6c2e1b84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("assets", schema=None) as batch_op:
        batch_op.add_column(sa.Column("origin", sa.String(length=16), server_default="upload", nullable=False))
        batch_op.add_column(sa.Column("source_asset_id", marvin.db.migration_types.GUID(), nullable=True))
        batch_op.create_index(batch_op.f("ix_assets_origin"), ["origin"], unique=False)
        batch_op.create_index(batch_op.f("ix_assets_source_asset_id"), ["source_asset_id"], unique=False)
        batch_op.create_foreign_key("fk_assets_source_asset_id", "assets", ["source_asset_id"], ["id"], ondelete="SET NULL")
    _backfill()


def _backfill() -> None:
    """origin/source from the metadata lineage; a derived_from naming an asset that no longer exists leaves the
    source empty (the version stands on its own)."""
    assets = sa.table(
        "assets",
        sa.column("id", marvin.db.migration_types.GUID()),
        sa.column("metadata_json", sa.JSON()),
        sa.column("origin", sa.String()),
        sa.column("source_asset_id", marvin.db.migration_types.GUID()),
    )
    conn = op.get_bind()
    rows = conn.execute(sa.select(assets.c.id, assets.c.metadata_json).where(assets.c.metadata_json.isnot(None))).all()
    ids = {str(r.id) for r in conn.execute(sa.select(assets.c.id))}
    for row in rows:
        meta = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        source = str(meta.get("derived_from") or "")
        if source:
            known = source in ids
            values = {"origin": "derived", "source_asset_id": uuid.UUID(source) if known else None}
        elif meta.get("generated_by"):
            values = {"origin": "generated"}
        else:
            continue
        conn.execute(sa.update(assets).where(assets.c.id == row.id).values(**values))


def downgrade() -> None:
    with op.batch_alter_table("assets", schema=None) as batch_op:
        batch_op.drop_constraint("fk_assets_source_asset_id", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_assets_source_asset_id"))
        batch_op.drop_index(batch_op.f("ix_assets_origin"))
        batch_op.drop_column("source_asset_id")
        batch_op.drop_column("origin")
