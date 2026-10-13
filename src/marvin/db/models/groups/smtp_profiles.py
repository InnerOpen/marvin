"""Workspace SMTP profile database model.

A workspace may define several named SMTP profiles (e.g. "Transactional",
"Marketing"); at most one is active at a time. The password is not stored on this
row — only `secret_ref`, a slug the configured secret backend resolves (same
pattern as integrations), so every credential lives behind one secrets surface.
"""

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.guid import GUID

if TYPE_CHECKING:
    from .groups import Groups


def smtp_secret_ref(profile_id: "uuid.UUID | str") -> str:
    """Deterministic secret-backend slug holding this profile's SMTP password.

    Derived from the immutable profile id so it is stable across renames and unique per profile.
    Shared by the controller and the migration that moved passwords into the secret backend — keep
    the format in sync with both.
    """
    hexpart = profile_id.hex if isinstance(profile_id, uuid.UUID) else str(profile_id).replace("-", "")
    return f"SMTP_{hexpart.upper()}"


class WorkspaceSMTPProfileModel(SqlAlchemyBase, BaseMixins):
    """A named SMTP server configuration scoped to a workspace."""

    __tablename__ = "workspace_smtp_profiles"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    group: Mapped[Optional["Groups"]] = relationship("Groups", back_populates="smtp_profiles", single_parent=True)

    name: Mapped[str] = mapped_column(String, nullable=False)
    """Human-readable label, e.g. 'Transactional'."""

    host: Mapped[str] = mapped_column(String, nullable=False)
    """SMTP server hostname or IP."""

    port: Mapped[int] = mapped_column(Integer, nullable=False, default=587)
    """SMTP server port."""

    username: Mapped[str | None] = mapped_column(String, nullable=True)
    """Optional SMTP auth username."""

    secret_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    """Slug the secret backend resolves for this profile's SMTP password (see smtp_secret_ref)."""

    from_name: Mapped[str | None] = mapped_column(String, nullable=True)
    """Display name on outgoing mail (falls back to the global SMTP_FROM_NAME)."""

    from_email: Mapped[str | None] = mapped_column(String, nullable=True)
    """From address on outgoing mail (falls back to the global SMTP_FROM_EMAIL)."""

    auth_strategy: Mapped[str] = mapped_column(String, nullable=False, default="TLS")
    """Connection security: 'TLS' (STARTTLS), 'SSL', or 'NONE'."""

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    """Whether this profile is the active one for the workspace (at most one)."""

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
