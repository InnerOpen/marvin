"""Workspace secrets database model."""

from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.guid import GUID

if TYPE_CHECKING:
    from .groups import Groups


class WorkspaceSecret(SqlAlchemyBase, BaseMixins):
    """
    Workspace-scoped secret.

    Values are encrypted at rest by the configured secret backend.
    Slugs are the reference handle used in {{SLUG}} interpolation.
    """

    __tablename__ = "workspace_secrets"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    group: Mapped[Optional["Groups"]] = relationship("Groups", back_populates="secrets", single_parent=True)

    name: Mapped[str] = mapped_column(String, nullable=False)
    """Human-readable label."""

    slug: Mapped[str] = mapped_column(String, nullable=False, index=True)
    """URL-safe identifier used in {{SLUG}} references. Uppercase by convention."""

    description: Mapped[str | None] = mapped_column(String, nullable=True)

    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    """Fernet-encrypted secret value. Never returned in API responses."""

    __table_args__ = (UniqueConstraint("group_id", "slug", name="uq_workspace_secrets_group_slug"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
