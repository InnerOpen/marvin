"""Entry type model."""

from typing import TYPE_CHECKING

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.guid import GUID

if TYPE_CHECKING:
    from .entries import Entries


class EntryTypes(SqlAlchemyBase, BaseMixins):
    """Workspace-defined or system-level entry type.

    Entry Types define schema-driven content models that specify:
    - What fields exist (via schema_json)
    - Field types and validation rules
    - Default values
    - UI configuration

    The schema_json field stores an EntryTypeSchemaDefinition that is used
    to validate entries.data_json when creating/updating entries.

    System entry types (is_system=True, group_id=NULL) are globally available
    to all workspaces and cannot be modified or deleted.
    """

    __tablename__ = "entry_types"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    slug: Mapped[str] = mapped_column(sa.String, nullable=False)
    icon: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    color: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    description: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    sort_order: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0, server_default="0")
    is_system: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False, server_default="false")
    is_rendered: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False, server_default=sa.false())
    schema_json: Mapped[dict] = mapped_column("schema_json", sa.JSON, nullable=False, default=dict, server_default="{}")
    """Schema definition for this entry type (EntryTypeSchemaDefinition)."""

    rendering_json: Mapped[dict | None] = mapped_column("rendering_json", sa.JSON, nullable=True)
    """Rendering configuration for this entry type (RenderingDefinition)."""

    capabilities_json: Mapped[dict | None] = mapped_column("capabilities_json", sa.JSON, nullable=True)
    """Behavioral capabilities for this entry type (CapabilitiesDefinition)."""

    recipe_json: Mapped[dict | None] = mapped_column("recipe_json", sa.JSON, nullable=True)
    """Authoring recipe: what to gather/derive to build an entry of this type
    (assets contract, resource extraction, enrichment steps) — EntryTypeRecipe."""

    page_url_pattern: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """Where the workspace's site renders an entry of this type, e.g. ``/works/{slug}``.
    Optional; resolved by ``marvin.services.entry_urls.entry_url``."""

    entries: Mapped[list["Entries"]] = orm.relationship("Entries", back_populates="entry_type")

    __table_args__ = (sa.UniqueConstraint("group_id", "slug"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        """Initialize via Marvin's auto-init model helper."""
        pass
