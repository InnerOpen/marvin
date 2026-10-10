"""API Clients model - read-only API identities for applications."""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import NaiveDateTime
from .._model_utils.guid import GUID


class APIClients(SqlAlchemyBase, BaseMixins):
    """
    SQLAlchemy model representing an API client.

    API clients are read-only API identities for applications consuming published content.
    These may be Astro sites, staging sites, n8n workflows, AI agents, search indexers,
    newsletter tools, mobile apps, or future integrations.
    """

    __tablename__ = "api_clients"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    slug: Mapped[str] = mapped_column(sa.String, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    token_hash: Mapped[str] = mapped_column(sa.String, nullable=False, unique=True, index=True)
    token_lookup: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, unique=True, index=True)
    """SHA-256 of the token (core/security/hasher.py: token_lookup); null for an older token until its next use."""
    permissions: Mapped[dict] = mapped_column(sa.JSON, nullable=False)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)
    created_by: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)

    __table_args__ = (sa.UniqueConstraint("group_id", "slug"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        """Initialize via Marvin's auto-init model helper."""
        pass
