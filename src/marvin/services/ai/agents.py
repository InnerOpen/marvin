"""
Agents: the built-in system agents plus workspace-defined ones, and the small pure helpers the
controller and the MCP tools share.

An agent is a *definition* (kind, prompt, model, tool allowlist, who may talk to it). Execution is the
existing tool loop (`run_agent_loop`) for `persona` agents and a plain completion for `model` agents.
System agents are code so every workspace has them without seeding:

- `marvin` — the default: every tool the caller's role allows, the workspace persona.
- `ask`    — grounded answers only: `search_content`, no writes.
- `chat`   — plain conversation with the model, no tools.
"""

from __future__ import annotations

from dataclasses import dataclass

from marvin.schemas.group.agent import SYSTEM_AGENT_SLUGS
from marvin.services.ai.operations.base import INVOCATION_SOURCES, ROLE_VIEWER

ASK_SYSTEM_PROMPT = (
    "You answer questions about this workspace using ONLY what the search_content tool returns. "
    "Search first, then answer from the results and name the entries you drew on. If the results "
    "don't contain the answer, say so plainly rather than guessing. Never invent content."
)


@dataclass(frozen=True)
class AgentSpec:
    slug: str
    name: str
    kind: str = "persona"
    description: str | None = None
    system_prompt: str | None = None
    model_override: str | None = None
    tool_allowlist: tuple[str, ...] | None = None  # None = everything the role allows
    default_register: str | None = None
    min_role: int = ROLE_VIEWER
    sources: tuple[str, ...] = INVOCATION_SOURCES
    enabled: bool = True
    allow_writes: bool = False  # bind non-read-only tools? (caller still needs AUTHOR+)
    is_system: bool = False
    id: str | None = None


SYSTEM_AGENTS: dict[str, AgentSpec] = {
    "marvin": AgentSpec(
        slug="marvin",
        name="Marvin",
        description="The workspace's own agent — every tool your role allows, in the workspace persona.",
        allow_writes=True,
        is_system=True,
    ),
    "ask": AgentSpec(
        slug="ask",
        name="Ask",
        description="Grounded answers from your content only (semantic search; no writes).",
        system_prompt=ASK_SYSTEM_PROMPT,
        tool_allowlist=("search_content",),
        is_system=True,
    ),
    "chat": AgentSpec(
        slug="chat",
        name="Chat",
        kind="model",
        description="Plain conversation with the model — no tools, no retrieval.",
        is_system=True,
    ),
}
assert tuple(SYSTEM_AGENTS) == SYSTEM_AGENT_SLUGS


def spec_from_row(row) -> AgentSpec:
    """A stored agent as a spec (the controller and tools only ever read specs)."""
    allow = row.tool_allowlist
    srcs = row.sources
    return AgentSpec(
        slug=row.slug,
        name=row.name,
        kind=row.kind or "persona",
        description=row.description,
        system_prompt=row.system_prompt,
        model_override=row.model_override,
        tool_allowlist=tuple(allow) if allow is not None else None,
        default_register=row.default_register,
        min_role=int(row.min_role or ROLE_VIEWER),
        sources=tuple(srcs) if srcs else INVOCATION_SOURCES,
        enabled=bool(row.enabled),
        allow_writes=bool(getattr(row, "allow_writes", False)),
        is_system=False,
        id=str(row.id),
    )


def list_agents(session, group_id) -> list[AgentSpec]:
    """System agents first, then the workspace's rows by slug."""
    from marvin.db.models.groups.agents import WorkspaceAgentModel

    rows = session.query(WorkspaceAgentModel).filter_by(group_id=group_id).order_by(WorkspaceAgentModel.slug).all()
    return [*SYSTEM_AGENTS.values(), *(spec_from_row(r) for r in rows)]


def resolve_agent(session, group_id, slug: str) -> AgentSpec | None:
    slug = (slug or "").strip().lower()
    if slug in SYSTEM_AGENTS:
        return SYSTEM_AGENTS[slug]
    from marvin.db.models.groups.agents import WorkspaceAgentModel

    row = session.query(WorkspaceAgentModel).filter_by(group_id=group_id, slug=slug).first()
    return spec_from_row(row) if row else None


def filter_tools(tools: list, allowlist: tuple[str, ...] | list[str] | None) -> list:
    """Keep only the bound tools an agent may use. None = no restriction."""
    if allowlist is None:
        return list(tools)
    allowed = set(allowlist)
    return [t for t in tools if t.name in allowed]


def may_talk(spec: AgentSpec, role: int, source: str) -> tuple[bool, str]:
    """Gate a run: enabled, caller's role, invocation surface. Returns (ok, reason)."""
    if not spec.enabled:
        return False, f"agent '{spec.slug}' is disabled"
    if role < spec.min_role:
        return False, f"agent '{spec.slug}' requires workspace role level {spec.min_role} or higher"
    if source not in spec.sources:
        return False, f"agent '{spec.slug}' is not callable from source '{source}'"
    return True, ""
