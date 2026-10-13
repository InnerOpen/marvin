"""Workspace variables — plain-text key-value config scoped to a workspace."""

from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.guid import GUID

if TYPE_CHECKING:
    from .groups import Groups


class WorkspaceVariable(SqlAlchemyBase, BaseMixins):
    """
    Workspace-scoped plain-text variable.

    Unlike WorkspaceSecret, the value is stored and returned in plaintext.
    Use for non-sensitive config: URLs, names, feature flags, etc.
    Referenced in webhook headers, email templates, and other configs
    via {{SLUG}} syntax — Secrets take priority on slug collision.
    """

    __tablename__ = "workspace_variables"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    group: Mapped[Optional["Groups"]] = relationship("Groups", back_populates="variables", single_parent=True)

    name: Mapped[str] = mapped_column(String, nullable=False)
    """Human-readable label."""

    slug: Mapped[str] = mapped_column(String, nullable=False, index=True)
    """Uppercase slug used in {{SLUG}} references."""

    description: Mapped[str | None] = mapped_column(String, nullable=True)

    value: Mapped[str] = mapped_column(Text, nullable=False)
    """Plain-text value — readable in API responses."""

    __table_args__ = (UniqueConstraint("group_id", "slug", name="uq_workspace_variables_group_slug"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
