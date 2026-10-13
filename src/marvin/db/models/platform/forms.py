"""Form model."""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import NaiveDateTime
from .._model_utils.guid import GUID


class Forms(SqlAlchemyBase, BaseMixins):
    """Workspace-scoped form definition.

    Forms are schema-driven submission endpoints. The schema_json defines
    what fields the form accepts, and settings_json controls behavior like
    notifications, rate limiting, and CAPTCHA.

    Forms emit events on submission that Actions (email, webhooks, Slack)
    subscribe to - Forms are generic and don't embed action logic.
    """

    __tablename__ = "forms"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)

    slug: Mapped[str] = mapped_column(sa.String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.String, nullable=True)

    schema_json: Mapped[dict] = mapped_column("schema_json", sa.JSON, nullable=False, default=dict, server_default="{}")
    """Field definitions for this form."""

    settings_json: Mapped[dict | None] = mapped_column("settings_json", sa.JSON, nullable=True)
    """Form behavior config: notifications, CAPTCHA, rate limits."""

    metadata_json: Mapped[dict | None] = mapped_column("metadata_json", sa.JSON, nullable=True)
    """Custom metadata (API keys, external IDs, integrations)."""

    status: Mapped[str] = mapped_column(sa.String, nullable=False, default="draft", server_default="draft")
    """Form status: draft | published | archived."""

    submissions_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0, server_default="0")
    """Total submissions received (cache)."""

    last_submission_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)
    """Timestamp of most recent submission."""

    __table_args__ = (
        sa.UniqueConstraint("group_id", "slug", name="uq_forms_group_slug"),
        sa.Index("ix_forms_group_status", "group_id", "status"),
        sa.CheckConstraint("status IN ('draft', 'published', 'archived')", name="chk_forms_status"),
    )

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        """Initialize via Marvin's auto-init model helper."""
        pass
