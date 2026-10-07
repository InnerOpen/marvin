"""Base types and registry for core AI tools (direct-handler capabilities).

Mirrors ``operations/base.py``. Where an :class:`AIOperation` is a prompt-building LLM
capability, a :class:`ToolSpec` is a direct-handler read/query/action capability: a name,
a description, a JSON input schema, a role/source gate, and a ``handler(ctx, args) -> str``.

The registry is the single source of truth. The internal agent binds each spec **in-process**
(no MCP hop); MarvinMCP **projects** the specs outward via ``GET /api/ai/tools`` +
``POST /api/ai/tools/{name}/invoke`` — the same way it already auto-projects AI operations.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ..operations.base import INVOCATION_SOURCES, ROLE_VIEWER


@dataclass
class ToolContext:
    """What a tool handler needs to run.

    Assembled by the caller (the controller for the agent + the invoke endpoint) so handlers
    stay free of controller/request coupling.
    """

    session: Session
    group_id: object
    user: Any = None
    provider: Any = None  # optional — only tools that embed/generate need one
    logger: Any = None
    # Agent hand-offs (agents v2 slice D). `depth` 0 = a run the user started; a delegated child run
    # is 1 and may not delegate further. `source` is the invocation surface the handlers gate on
    # (e.g. may_talk) — None keeps the pre-slice-D "mcp" fallback. `delegate(slug, message,
    # max_steps) -> dict` is the controller's child runner, set only at depth 0 when run_agent is
    # bound; `referrals` collects suggest_agent calls for the parent to surface.
    depth: int = 0
    source: str | None = None
    # The agent execution this tool call belongs to (set by the controller once its row exists), so
    # executions a tool spawns — compose/revise, AI operations, hand-offs — can point back at it.
    execution_id: str | None = None
    delegate: Callable[[str, str, int | None], dict] | None = None
    referrals: list[dict] = field(default_factory=list)
    # The run's tone (a tone slug), so drafts the authoring tools write match the conversation's tone
    # rather than the workspace default. None → the workspace default.
    tone_register: str | None = None


# handler(ctx, args) -> str : returns a JSON string fed back to the model / returned to callers.
ToolHandler = Callable[[ToolContext, dict], str]


@dataclass
class ToolSpec:
    """A named, gated, direct-handler capability."""

    name: str
    description: str
    handler: ToolHandler
    input_schema: dict = field(default_factory=dict)
    min_role: int = ROLE_VIEWER
    # Surfaces this tool may be invoked from (default: all). Intersected with the workspace's
    # invocation_sources policy at execute time, à la AIOperation.invocation_sources.
    sources: tuple[str, ...] = INVOCATION_SOURCES
    read_only: bool = True
    # Bulk-write tools: size one call without writing (`bulk_writes.BulkWrite`), so a big call asks
    # the user first instead of running — see tools/bulk_writes.py. None = never bulk.
    bulk_write: Callable[[ToolContext, dict], Any] | None = None
    # Ask-first tools: look at one call without writing and return a `bulk_writes.AskFirst` when *this*
    # call needs the user's go-ahead (archive_entries or trash_entries on a published entry), else None.
    ask_first: Callable[[ToolContext, dict], Any] | None = None

    def info(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "min_role": self.min_role,
            "sources": list(self.sources),
            "read_only": self.read_only,
        }


TOOL_REGISTRY: dict[str, ToolSpec] = {}


def register_tool(
    *,
    name: str,
    description: str,
    input_schema: dict | None = None,
    min_role: int = ROLE_VIEWER,
    sources: tuple[str, ...] = INVOCATION_SOURCES,
    read_only: bool = True,
    bulk_write: Callable[[ToolContext, dict], Any] | None = None,
    ask_first: Callable[[ToolContext, dict], Any] | None = None,
):
    """Decorator: register the decorated ``handler(ctx, args) -> str`` as a :class:`ToolSpec`."""

    def deco(handler: ToolHandler) -> ToolHandler:
        TOOL_REGISTRY[name] = ToolSpec(
            name=name,
            description=description,
            handler=handler,
            input_schema=input_schema or {},
            min_role=min_role,
            sources=sources,
            read_only=read_only,
            bulk_write=bulk_write,
            ask_first=ask_first,
        )
        return handler

    return deco


def caller_role(ctx: ToolContext) -> int:
    """The calling user's numeric workspace role in ctx.group_id (legacy admins → OWNER; no user →
    VIEWER, the floor every tool already meets; not a member → 0)."""
    from marvin.db.models.users.roles import WORKSPACE_ROLE_HIERARCHY

    from ..operations.base import ROLE_OWNER

    user = ctx.user
    if user is None:
        return ROLE_VIEWER
    if getattr(user, "admin", False):
        return ROLE_OWNER
    for m in getattr(user, "workspace_memberships", []) or []:
        if str(m.group_id) == str(ctx.group_id):
            return WORKSPACE_ROLE_HIERARCHY.get(m.workspace_role, 0)
    return 0


def get_tool(name: str) -> ToolSpec:
    if name not in TOOL_REGISTRY:
        raise KeyError(f"AI tool '{name}' not found. Available: {list(TOOL_REGISTRY)}")
    return TOOL_REGISTRY[name]


def list_tools() -> list[ToolSpec]:
    return list(TOOL_REGISTRY.values())
