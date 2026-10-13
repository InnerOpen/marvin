"""Asset-Tags junction table — many-to-many between assets and the shared tag vocabulary."""

from typing import TYPE_CHECKING

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy.orm import Mapped, mapped_column

from .. import SqlAlchemyBase
from .._model_utils.guid import GUID

if TYPE_CHECKING:
    from .assets import Assets
    from .tags import Tags


class AssetTags(SqlAlchemyBase):
    """Junction table for the many-to-many relationship between assets and tags."""

    __tablename__ = "asset_tags"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    asset_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    tag_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True)

    asset: Mapped["Assets"] = orm.relationship(
        "Assets",
        foreign_keys=[asset_id],
        overlaps="tags,assets,asset_tags",
    )
    tag: Mapped["Tags"] = orm.relationship(
        "Tags",
        foreign_keys=[tag_id],
        overlaps="tags,assets",
    )

    __table_args__ = (sa.UniqueConstraint("asset_id", "tag_id"),)
