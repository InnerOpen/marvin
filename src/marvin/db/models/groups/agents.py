"""
Workspace agents — user-definable AI agents the agent loop executes.

A row is a *definition*: what the agent is called, which model it uses, its system prompt, and which
tools it may reach for. Execution is the existing tool loop (services/ai/agent.py); the three system
agents (`marvin`, `ask`, `chat`) are code, not rows — see services/ai/agents.py.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.guid import GUID

__all__ = ["WorkspaceAgentModel"]


class WorkspaceAgentModel(SqlAlchemyBase, BaseMixins):
    __tablename__ = "workspace_agents"
    __table_args__ = (sa.UniqueConstraint("group_id", "slug", name="uq_workspace_agents_group_slug"),)

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, ForeignKey("groups.id"), index=True, nullable=False)

    slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # "persona" = system prompt + tool allowlist run through the tool loop; "model" = plain completion.
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="persona")
    system_prompt: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    model_override: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # None = every tool the caller's role allows; a list = only those names (registry tools, AI
    # operations by slug-with-underscores, or external MCP tools as mcp__<server>__<tool>).
    tool_allowlist: Mapped[list | None] = mapped_column(sa.JSON, nullable=True)
    default_register: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Minimum workspace role that may talk to this agent (ROLE_* in services/ai/operations/base.py).
    min_role: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Invocation surfaces allowed (editor | api | mcp | agent); None = all.
    sources: Mapped[list | None] = mapped_column(sa.JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Whether non-read-only tools (authoring, links, AI ops, external MCP) may be bound; the caller still
    # needs AUTHOR+ for them to actually bind. Default off: a new agent is read-only until you say otherwise.
    allow_writes: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[GUID | None] = mapped_column(GUID, nullable=True)

    @auto_init()
    def __init__(self, session: Session, **_) -> None:
        pass
