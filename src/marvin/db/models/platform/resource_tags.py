"""Resource-Tags junction table — many-to-many between resources and the shared tag vocabulary."""

from typing import TYPE_CHECKING

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy.orm import Mapped, mapped_column

from .. import SqlAlchemyBase
from .._model_utils.guid import GUID

if TYPE_CHECKING:
    from .resources import Resources
    from .tags import Tags


class ResourceTags(SqlAlchemyBase):
    """Junction table for the many-to-many relationship between resources and tags."""

    __tablename__ = "resource_tags"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    resource_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True)
    tag_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True)

    resource: Mapped["Resources"] = orm.relationship(
        "Resources",
        foreign_keys=[resource_id],
        overlaps="tags,resources,resource_tags",
    )
    tag: Mapped["Tags"] = orm.relationship(
        "Tags",
        foreign_keys=[tag_id],
        overlaps="tags,resources",
    )

    __table_args__ = (sa.UniqueConstraint("resource_id", "tag_id"),)
