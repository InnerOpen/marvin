"""Entry-Tags junction table — many-to-many between entries and the shared tag vocabulary."""

from typing import TYPE_CHECKING

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy.orm import Mapped, mapped_column

from .. import SqlAlchemyBase
from .._model_utils.guid import GUID

if TYPE_CHECKING:
    from .entries import Entries
    from .tags import Tags


class EntryTags(SqlAlchemyBase):
    """Junction table for the many-to-many relationship between entries and tags."""

    __tablename__ = "entry_tags"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    entry_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("entries.id", ondelete="CASCADE"), nullable=False, index=True)
    tag_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True)

    entry: Mapped["Entries"] = orm.relationship(
        "Entries",
        foreign_keys=[entry_id],
        overlaps="tags,entries,entry_tags",
    )
    tag: Mapped["Tags"] = orm.relationship(
        "Tags",
        foreign_keys=[tag_id],
        overlaps="tags,entries",
    )

    __table_args__ = (sa.UniqueConstraint("entry_id", "tag_id"),)
