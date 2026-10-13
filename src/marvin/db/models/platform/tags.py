"""Tags model — a shared, group-scoped vocabulary applied across entries (and, later,
assets and resources).

Mirrors Collections: group-scoped, unique per (group_id, slug), created on the fly as users
type them (find-or-create by slug). Distinct from Collections in intent — a collection is a
curated placement, a tag is a lightweight label many things share and that smart-collection
rules match against.
"""

from typing import TYPE_CHECKING

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.guid import GUID

if TYPE_CHECKING:
    from .assets import Assets
    from .entries import Entries
    from .resources import Resources


class Tags(SqlAlchemyBase, BaseMixins):
    """A single tag in a workspace's shared vocabulary."""

    __tablename__ = "tags"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    # Display form as first typed ("Chore Coat"); slug is the identity ("chore-coat").
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    slug: Mapped[str] = mapped_column(sa.String, nullable=False)
    color: Mapped[str | None] = mapped_column(sa.String, nullable=True)

    entries: Mapped[list["Entries"]] = orm.relationship(
        "Entries",
        secondary="entry_tags",
        back_populates="tags",
        doc="Entries carrying this tag",
    )
    assets: Mapped[list["Assets"]] = orm.relationship(
        "Assets",
        secondary="asset_tags",
        back_populates="tags",
        doc="Assets carrying this tag",
    )
    resources: Mapped[list["Resources"]] = orm.relationship(
        "Resources",
        secondary="resource_tags",
        back_populates="tags",
        doc="Resources carrying this tag",
    )

    __table_args__ = (sa.UniqueConstraint("group_id", "slug"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
