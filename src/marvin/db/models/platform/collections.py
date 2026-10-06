"""Collections model - curated groupings of entries."""

from typing import TYPE_CHECKING

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.guid import GUID
from .._model_utils.installed_by import InstalledByMixin

if TYPE_CHECKING:
    from .assets import Assets
    from .entries import Entries
    from .resources import Resources


class Collections(SqlAlchemyBase, BaseMixins, InstalledByMixin):
    """
    SQLAlchemy model representing a collection.

    Collections are curated groupings of entries. They can be manual or smart.
    """

    __tablename__ = "collections"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    slug: Mapped[str] = mapped_column(sa.String, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    sort_order: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0, server_default="0")
    icon: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    color: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    is_smart: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    smart_rules: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    # Which entity type this collection groups: "entry" (default), "asset", or "resource".
    # A smart collection materializes membership of this type; manual collections are entry-only.
    target_type: Mapped[str] = mapped_column(sa.String, nullable=False, default="entry", server_default="entry")
    # System workflow collections (Inbox/Drafts/…) are seeded, locked from edit/delete, and
    # internal-only (not exposed via the publish API).
    is_system: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False, server_default=sa.false())
    is_public: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True, server_default=sa.true())
    metadata_json: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)

    # Relationships
    entries: Mapped[list["Entries"]] = orm.relationship(
        "Entries",
        secondary="entry_collections",
        back_populates="collections",
        doc="Entries in this collection",
    )
    # Read-only convenience views. Membership rows are always written through the
    # association models (CollectionAssets / CollectionResources) — see
    # services/collections/smart_collections.sync_item — never by mutating these
    # collections. Marking them viewonly tells SQLAlchemy they never participate in a
    # flush, which resolves the overlapping-FK-write warning at its source rather than
    # silencing it with `overlaps=` (which would leave two relationships both able to
    # write collection_assets.asset_id / collection_resources.resource_id).
    assets: Mapped[list["Assets"]] = orm.relationship(
        "Assets",
        secondary="collection_assets",
        viewonly=True,
        doc="Assets in this (asset-target smart) collection (read-only view)",
    )
    resources: Mapped[list["Resources"]] = orm.relationship(
        "Resources",
        secondary="collection_resources",
        viewonly=True,
        doc="Resources in this (resource-target smart) collection (read-only view)",
    )

    __table_args__ = (sa.UniqueConstraint("group_id", "slug"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        """Initialize via Marvin's auto-init model helper."""
        pass
