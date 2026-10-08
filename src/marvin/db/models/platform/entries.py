"""Entry model."""

from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import NaiveDateTime
from .._model_utils.guid import GUID

if TYPE_CHECKING:
    from ..users import Users
    from .assets import Assets
    from .collections import Collections
    from .entry_assets import EntryAssets
    from .entry_collections import EntryCollections
    from .entry_resources import EntryResources
    from .entry_types import EntryTypes
    from .resources import Resources
    from .tags import Tags


class Entries(SqlAlchemyBase, BaseMixins):
    """Workspace-scoped publishable content entry.

    Entries are schema-driven content objects. The entry_type.schema_json
    defines what fields exist, and this entry's data_json contains the
    actual content structured according to that schema.

    The metadata_json field is for custom non-schema metadata (API keys,
    external IDs, CMS-specific config) that isn't part of the content model.
    """

    __tablename__ = "entries"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    entry_type_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("entry_types.id", ondelete="RESTRICT"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(sa.String, nullable=False)
    slug: Mapped[str] = mapped_column(sa.String, nullable=False)
    summary: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    description: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    data_json: Mapped[dict] = mapped_column("data_json", sa.JSON, nullable=False, default=dict, server_default="{}")
    """Schema-driven content data structured according to entry_type.schema_json."""
    status: Mapped[str] = mapped_column(sa.String, nullable=False, default="inbox", server_default="inbox")
    published_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)
    publish_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)
    """Scheduled publish datetime - when this entry should be published."""
    expire_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)
    """Expiration datetime - when this entry should be hidden/archived."""
    metadata_json: Mapped[dict | None] = mapped_column("metadata_json", sa.JSON, nullable=True)
    # Pending AI-proposed changes staged for human review (write-back). Keyed by target field,
    # e.g. {"summary": "…", "_meta": {"operation": "generate-summary", "executionId": "…"}}.
    # none_as_null: store Python None as SQL NULL, not the JSON literal `null` (which `IS NOT NULL`
    # would otherwise count as a pending suggestion). See clear_suggestion / dashboard attention count.
    suggestion_json: Mapped[dict | None] = mapped_column("suggestion_json", sa.JSON(none_as_null=True), nullable=True)
    """Custom non-schema metadata (API keys, external IDs, CMS config, etc.)."""
    # Why the Publish Scheduled Entries task is holding this due entry back — {waiting_for:
    # "requirements" | "approval", reason, issues, at, notified}. System-managed: written by the task,
    # cleared when the entry publishes, is archived or its publish_at changes. Kept out of
    # metadata_json, which the editor round-trips and the API exposes as the entry's own data.
    scheduled_publish_blocked: Mapped[dict | None] = mapped_column(sa.JSON(none_as_null=True), nullable=True)
    created_by: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    entry_type: Mapped["EntryTypes"] = orm.relationship("EntryTypes", back_populates="entries")
    author: Mapped["Users"] = orm.relationship("Users", foreign_keys=[created_by])
    collections: Mapped[list["Collections"]] = orm.relationship(
        "Collections",
        secondary="entry_collections",
        back_populates="entries",
        doc="Collections this entry belongs to",
    )
    entry_collections: Mapped[list["EntryCollections"]] = orm.relationship(
        "EntryCollections",
        foreign_keys="EntryCollections.entry_id",
        overlaps="collections,entries",
        cascade="all, delete-orphan",
        doc="Direct access to entry-collection associations",
    )

    resources: Mapped[list["Resources"]] = orm.relationship(
        "Resources",
        secondary="entry_resources",
        back_populates="entries",
        doc="Resources referenced by this entry",
    )

    entry_resources: Mapped[list["EntryResources"]] = orm.relationship(
        "EntryResources",
        foreign_keys="EntryResources.entry_id",
        overlaps="entries,resources",
        cascade="all, delete-orphan",
        # In placement order: unordered, Postgres may hand a site the gallery before the hero.
        order_by="EntryResources.position",
        doc="Direct access to entry-resource associations with placement info",
    )

    assets: Mapped[list["Assets"]] = orm.relationship(
        "Assets",
        secondary="entry_assets",
        back_populates="entries",
        overlaps="entry_assets",
        doc="Assets included in this entry",
    )

    entry_assets: Mapped[list["EntryAssets"]] = orm.relationship(
        "EntryAssets",
        foreign_keys="EntryAssets.entry_id",
        overlaps="assets,entries",
        cascade="all, delete-orphan",
        # In placement order: unordered, Postgres may hand a site the gallery before the hero.
        order_by="EntryAssets.position",
        doc="Direct access to entry-asset associations with placement info",
    )

    tags: Mapped[list["Tags"]] = orm.relationship(
        "Tags",
        secondary="entry_tags",
        back_populates="entries",
        doc="Tags applied to this entry (shared vocabulary)",
    )

    @property
    def tag_names(self) -> list[str]:
        """Tag slugs on this entry — what smart-collection rules match against.

        `smart_collections.py` intersects a rule's `tags` against `entry.tags`; expose slugs
        (the stable identity, what a rule stores) so tag-based smart collections work with no
        matcher change. Kept a plain property (not a column) so it always reflects the junction.
        """
        return [t.slug for t in self.tags]

    __table_args__ = (
        sa.UniqueConstraint("group_id", "slug"),
        sa.Index("ix_entries_group_status", "group_id", "status"),
    )

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        """Initialize via Marvin's auto-init model helper."""
        pass
