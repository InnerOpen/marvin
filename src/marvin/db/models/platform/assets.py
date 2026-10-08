"""Assets model - uploaded files."""

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
    from .entry_assets import EntryAssets
    from .tags import Tags


class Assets(SqlAlchemyBase, BaseMixins):
    """
    SQLAlchemy model representing an asset.

    Assets are uploaded files like images, PDFs, audio, video, etc.
    """

    __tablename__ = "assets"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(sa.String, nullable=False)
    name: Mapped[str] = mapped_column(sa.String, nullable=False)

    original_filename: Mapped[str] = mapped_column(sa.String, nullable=False)
    filename: Mapped[str] = mapped_column(sa.String, nullable=False)
    extension: Mapped[str] = mapped_column(sa.String, nullable=False)

    file_path: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    file_size: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    asset_type: Mapped[str] = mapped_column(sa.String, nullable=False, index=True)
    checksum: Mapped[str] = mapped_column(sa.String, nullable=False)

    width: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    orientation: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    storage_provider: Mapped[str] = mapped_column(sa.String, nullable=False)
    storage_key: Mapped[str] = mapped_column(sa.String, nullable=False, unique=True)
    public_url: Mapped[str | None] = mapped_column(sa.String, nullable=True)

    alt_text: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    description: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    # Pending AI-proposed changes staged for human review (write-back), keyed by target field —
    # mirrors Entries.suggestion_json. e.g. {"tags": [...], "_meta": {"operation": "generate-tags"}}.
    suggestion_json: Mapped[dict | None] = mapped_column(sa.JSON(none_as_null=True), nullable=True)
    uploaded_by: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=False)
    # The Trash (services/trash.py): set while the row is in it — hidden from every listing, the publishing API and
    # the AI until restored (both cleared) or the Trash is emptied. trashed_by: who moved it there (no FK, like an
    # entry's metadata_json.trash record).
    trashed_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True, index=True)
    trashed_by: Mapped[GUID | None] = mapped_column(GUID, nullable=True)
    # 'library' (the Assets library) or 'ask' (a file attached to a chat question, kept out of the library until
    # moved there): services/assets/scope.py.
    scope: Mapped[str] = mapped_column(sa.String, nullable=False, default="library", server_default="library", index=True)

    # Relationships
    entries: Mapped[list["Entries"]] = orm.relationship(
        "Entries",
        secondary="entry_assets",
        back_populates="assets",
        doc="Entries that include this asset",
    )
    entry_assets: Mapped[list["EntryAssets"]] = orm.relationship(
        "EntryAssets",
        foreign_keys="EntryAssets.asset_id",
        back_populates="asset",
        cascade="all, delete-orphan",
        overlaps="entries",
        doc="Junction records for entries using this asset",
    )
    tags: Mapped[list["Tags"]] = orm.relationship(
        "Tags",
        secondary="asset_tags",
        back_populates="assets",
        doc="Tags applied to this asset (shared vocabulary)",
    )

    __table_args__ = (sa.UniqueConstraint("group_id", "slug"),)

    @property
    def tag_names(self) -> list[str]:
        """Tag slugs on this asset — the stable identity a rule/filter matches (see Entries.tag_names)."""
        return [t.slug for t in self.tags]

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        """Initialize via Marvin's auto-init model helper."""
        pass
