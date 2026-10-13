"""Resources model - reusable objects referenced by entries."""

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
    from .entries import Entries
    from .entry_resources import EntryResources
    from .tags import Tags


class Resources(SqlAlchemyBase, BaseMixins):
    """
    SQLAlchemy model representing a resource.

    Resources are reusable objects like fabrics, tools, suppliers, books, etc.
    """

    __tablename__ = "resources"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(sa.String, nullable=False)
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    resource_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    url: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    external_id: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    # Pending AI-proposed changes staged for human review (write-back) — mirrors Entries.suggestion_json.
    suggestion_json: Mapped[dict | None] = mapped_column(sa.JSON(none_as_null=True), nullable=True)
    created_by: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=False)
    # The Trash (services/trash.py): set while the row is in it — hidden from every listing, the publishing API and
    # the AI until restored (both cleared) or the Trash is emptied. trashed_by: who moved it there (no FK, like an
    # entry's metadata_json.trash record).
    trashed_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True, index=True)
    trashed_by: Mapped[GUID | None] = mapped_column(GUID, nullable=True)

    # Relationships
    entries: Mapped[list["Entries"]] = orm.relationship(
        "Entries",
        secondary="entry_resources",
        back_populates="resources",
        doc="Entries that reference this resource",
    )
    entry_resources: Mapped[list["EntryResources"]] = orm.relationship(
        "EntryResources",
        foreign_keys="EntryResources.resource_id",
        back_populates="resource",
        cascade="all, delete-orphan",
        overlaps="entries,resources",
        doc="Junction records for entries using this resource",
    )
    tags: Mapped[list["Tags"]] = orm.relationship(
        "Tags",
        secondary="resource_tags",
        back_populates="resources",
        doc="Tags applied to this resource (shared vocabulary)",
    )

    __table_args__ = (sa.UniqueConstraint("group_id", "slug"),)

    @property
    def tag_names(self) -> list[str]:
        """Tag slugs on this resource — the stable identity a rule/filter matches (see Entries.tag_names)."""
        return [t.slug for t in self.tags]

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        """Initialize via Marvin's auto-init model helper."""
        pass
