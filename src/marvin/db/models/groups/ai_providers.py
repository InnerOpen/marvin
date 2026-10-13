"""SQLAlchemy models for workspace AI providers and models."""

from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.guid import GUID

if TYPE_CHECKING:
    from .groups import Groups


class AIProviderModel(SqlAlchemyBase, BaseMixins):
    """Per-workspace AI provider configuration."""

    __tablename__ = "ai_providers"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    group: Mapped[Optional["Groups"]] = orm.relationship("Groups", back_populates="ai_providers")

    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    slug: Mapped[str] = mapped_column(sa.String, nullable=False)
    # openai | anthropic | google | azure | ollama | custom
    provider_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    # Slug of a WorkspaceSecret containing the API key
    secret_ref: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    # For Ollama, Azure, or custom base URLs
    base_url: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    # Extra provider-specific config (api_version, org_id, etc.)
    metadata_json: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)

    models: Mapped[list["AIModelModel"]] = orm.relationship(
        "AIModelModel",
        back_populates="provider",
        cascade="all, delete-orphan",
    )

    __table_args__ = (sa.UniqueConstraint("group_id", "slug", name="uq_ai_providers_group_slug"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass


class AIModelModel(SqlAlchemyBase, BaseMixins):
    """A model available under a specific AI provider."""

    __tablename__ = "ai_models"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    provider_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("ai_providers.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped["AIProviderModel"] = orm.relationship("AIProviderModel", back_populates="models")
    # Denormalised for easy workspace-level queries
    group_id: Mapped[GUID] = mapped_column(GUID, nullable=False, index=True)

    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    # Actual API model identifier, e.g. "gpt-4o", "claude-sonnet-5"
    model_id: Mapped[str] = mapped_column(sa.String, nullable=False)
    is_default: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    context_window: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    supports_vision: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    supports_tools: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)

    __table_args__ = (sa.UniqueConstraint("provider_id", "model_id", name="uq_ai_models_provider_model"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
