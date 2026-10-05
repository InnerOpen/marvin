"""Workspace integrations — credentialed connections to external services."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import DateTime
from .._model_utils.guid import GUID

if TYPE_CHECKING:
    from .groups import Groups


class IntegrationModel(SqlAlchemyBase, BaseMixins):
    """
    One configured connection to an external service, scoped to a workspace.

    Credentials are never stored on this row — only `secret_ref`, a slug the
    configured secret backend resolves via `resolve_secret()`. `provider` keys
    into INTEGRATION_REGISTRY (code); the `config` shape is validated by that
    provider's `config_schema`.
    """

    __tablename__ = "integrations"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    group: Mapped[Optional["Groups"]] = relationship("Groups", back_populates="integrations", single_parent=True)

    provider: Mapped[str] = mapped_column(String, nullable=False, index=True)
    """Registry key, e.g. 'vercel_deploy'."""

    name: Mapped[str] = mapped_column(String, nullable=False)
    """User-facing label, e.g. 'Prod site'."""

    slug: Mapped[str] = mapped_column(String, nullable=False, index=True)
    """Stable per-workspace reference used by automations."""

    enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True, server_default=sa.true())

    config: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    """Non-secret instance settings; shape validated by the provider's config_schema."""

    secret_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    """Slug the secret backend resolves for this instance's credential."""

    status: Mapped[str] = mapped_column(String, nullable=False, default="unconfigured", server_default="unconfigured")
    """Health: ok | error | unconfigured. Written by the provider's check()."""

    last_checked_at: Mapped[datetime | None] = mapped_column(sa.DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """When a provider action through this connection last succeeded (any caller; see errors.connection_succeeded)."""

    error_overrides: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    """An admin's adjustments to the provider's error policy for this connection: {code: {review?, notify?}}.
    Only those immediate flags — retries, backoff and `then` stay as the provider declared them. Kept
    apart from `config` (the provider's own settings, which the provider sees)."""

    __table_args__ = (UniqueConstraint("group_id", "slug", name="uq_integrations_group_slug"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
