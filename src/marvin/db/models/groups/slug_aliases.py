"""Slugs a workspace had before it was renamed.

A workspace's slug appears in URLs other systems keep — the Publishing API
(``/api/publish/{workspace_slug}/...``, e.g. a site's ``MARVIN_WORKSPACE_SLUG``), CLI arguments and
backup file names. When a super admin changes it, the old slug is kept here so those keep resolving
to the same workspace (services.group.workspace_rename.find_group_by_slug). A current slug always wins
over an alias, and an old slug can't be taken by another workspace while it is someone's alias.
"""

from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.guid import GUID

if TYPE_CHECKING:
    from .groups import Groups


class GroupSlugAlias(SqlAlchemyBase, BaseMixins):
    __tablename__ = "group_slug_aliases"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    group: Mapped[Optional["Groups"]] = relationship("Groups", back_populates="slug_aliases")
    slug: Mapped[str] = mapped_column(sa.String, nullable=False, unique=True)
    """The old slug."""

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
