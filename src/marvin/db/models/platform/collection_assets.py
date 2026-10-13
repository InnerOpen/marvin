"""Collection-Assets junction — membership of assets in an (asset-target) smart collection."""

from typing import TYPE_CHECKING

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy.orm import Mapped, mapped_column

from .. import SqlAlchemyBase
from .._model_utils.guid import GUID

if TYPE_CHECKING:
    from .assets import Assets
    from .collections import Collections


class CollectionAssets(SqlAlchemyBase):
    """Junction table for the many-to-many relationship between collections and assets."""

    __tablename__ = "collection_assets"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    collection_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("collections.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0, server_default="0")

    collection: Mapped["Collections"] = orm.relationship("Collections", overlaps="assets")
    asset: Mapped["Assets"] = orm.relationship("Assets", overlaps="asset_collections")

    __table_args__ = (sa.UniqueConstraint("collection_id", "asset_id"),)
