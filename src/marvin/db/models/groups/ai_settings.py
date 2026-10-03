"""SQLAlchemy model for per-workspace AI workflow policy settings."""

from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.guid import GUID

if TYPE_CHECKING:
    from .groups import Groups


class WorkspaceAISettingsModel(SqlAlchemyBase, BaseMixins):
    __tablename__ = "workspace_ai_settings"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True, unique=True)
    group: Mapped[Optional["Groups"]] = orm.relationship("Groups", back_populates="ai_settings")

    enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    # "platform" | "workspace" | "disabled"
    credential_mode: Mapped[str] = mapped_column(sa.String, default="platform", nullable=False)
    # "openai" | "anthropic" | ...
    provider: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    model: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    # slug of a WorkspaceSecret
    secret_ref: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    # "suggest-only" | "allow-draft-update" | "allow-automatic-update"
    approval_mode: Mapped[str] = mapped_column(sa.String, default="suggest-only", nullable=False)

    # {editor, forms, actions, mcp, scheduledJobs} — which subsystems may call AI
    invocation_sources: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    # per-operation {model, approval_mode, ...}
    operation_overrides: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    # {max_tokens_per_request, max_requests_per_day, ...}
    budget_config: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    # {log_inputs, log_outputs, redact_patterns, retention_days}
    logging_config: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    # {enabled, block_on_flag}
    moderation_config: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    # Per-workspace grade preset overrides — {preset_name: {warmth, contrast, saturation, brightness,
    # vignette}}. Merged over the built-in GRADE_PRESETS (override/extend by name). None → built-ins.
    media_presets: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)

    # Master switch for the agent drawing tools from registered external MCP servers (off by default).
    external_mcp_enabled: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False, server_default=sa.false())

    # Per-workspace AI persona. Display name for the assistant (defaults to "Marvin" in code when unset).
    assistant_name: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    # The bubble's icon: an emoji, or an image URL (e.g. an asset's public URL). Unset → 🤖.
    assistant_icon: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    # The bubble's animated character, shown instead of the icon when set: {"states": {state: url},
    # "files": [{name, assetId, url}]}, or a library pack {"library": id} — see services/ai/character.py.
    # Unset → the icon.
    assistant_character: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    # Free-text voice/tone instruction appended to the system prompt.
    persona_prompt: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # Default tone register for agent runs — a SEPARATE axis from persona (axis B). Persona is how
    # the assistant addresses you; register is how work product reads. "professional" suppresses
    # the persona for the run. "auto" | "professional" | "playful". A per-call register overrides it.
    default_register: Mapped[str] = mapped_column(sa.String, default="auto", nullable=False, server_default="auto")

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
