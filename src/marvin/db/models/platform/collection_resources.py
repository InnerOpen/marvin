"""Collection-Resources junction — membership of resources in a (resource-target) smart collection."""

from typing import TYPE_CHECKING

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy.orm import Mapped, mapped_column

from .. import SqlAlchemyBase
from .._model_utils.guid import GUID

if TYPE_CHECKING:
    from .collections import Collections
    from .resources import Resources


class CollectionResources(SqlAlchemyBase):
    """Junction table for the many-to-many relationship between collections and resources."""

    __tablename__ = "collection_resources"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    collection_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("collections.id", ondelete="CASCADE"), nullable=False, index=True)
    resource_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0, server_default="0")

    collection: Mapped["Collections"] = orm.relationship("Collections", overlaps="resources")
    resource: Mapped["Resources"] = orm.relationship("Resources", overlaps="resource_collections")

    __table_args__ = (sa.UniqueConstraint("collection_id", "resource_id"),)
