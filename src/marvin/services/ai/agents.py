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

from collections.abc import Iterable
from dataclasses import dataclass

from marvin.schemas.group.agent import SYSTEM_AGENT_SLUGS
from marvin.services.ai.operations.base import INVOCATION_SOURCES, ROLE_VIEWER

ASK_SYSTEM_PROMPT = (
    "You answer questions about this workspace using ONLY what your tools return: search_content for "
    "content by meaning, workspace_overview for what the workspace contains overall. Search first, then "
    "answer from the results and name the entries you drew on. If the results don't contain the answer, "
    "say so plainly rather than guessing. Never invent content."
)

# Users call the indexed workspace content "the RAG", "the knowledge base", "the index" or "what you know".
# Every persona run gets this preamble so no agent mistakes the vocabulary (Chat once answered a "summary of
# the RAG" with Red/Amber/Green) and knows which tool answers which kind of question. Only tools actually
# bound for the run are mentioned.
CONTENT_SYNONYMS = '"the RAG", "the knowledge base", "the index", "your content" or "what you know"'


def external_servers(tool_names: Iterable[str]) -> dict[str, int]:
    """`{server_prefix: tool_count}` from bound `mcp__<server>__<tool>` names."""
    counts: dict[str, int] = {}
    for name in tool_names:
        if name.startswith("mcp__"):
            parts = name.split("__", 2)
            if len(parts) == 3:
                counts[parts[1]] = counts.get(parts[1], 0) + 1
    return counts


def workspace_preamble(workspace_name: str | None, tool_names: Iterable[str]) -> str:
    names = set(tool_names)
    where = f'the "{workspace_name}" workspace' if workspace_name else "this workspace"
    lines = [
        f"You are working inside {where} of Marvin, a headless CMS. Its content — entries (typed records such as "
        "notes, projects and pages), collections, assets (images and files) and resources (links) — is indexed for "
        f"semantic search. When the user says {CONTENT_SYNONYMS}, they mean this workspace content, never a status "
        "colour scheme or anything outside the workspace."
    ]
    if "workspace_overview" in names:
        lines.append(
            "To say what the workspace CONTAINS overall — a summary of the RAG, what is indexed and how much — call "
            "workspace_overview first, then drill into specifics."
        )
    if "search_content" in names:
        lines.append("To find content by MEANING (a topic, a question, 'anything about X') call search_content.")
    if "find_entries" in names:
        lines.append("find_entries is a keyword/filter lookup: use it for exact titles, statuses or types, not for concepts.")
    servers = external_servers(names)
    if servers:
        listed = ", ".join(f"{slug} ({n} tools, named mcp__{slug}__*)" for slug, n in sorted(servers.items()))
        lines.append(
            f"Connected external sources (MCP servers): {listed}. When the user names one of these — "
            "'check the brain', 'in my vault' — answer from that server's tools, not from workspace content."
        )
    if names:
        lines.append(
            "Act, don't announce: when a question needs a tool, call it in this same turn. Never reply with "
            "'let me check' or 'give me a moment' — there is no later turn."
        )
    return "\n".join(lines)


def model_agent_system_prompt(name: str, *, gloomy: bool = False) -> str:
    """System prompt for a `model` agent (plain conversation, no tools): says what it cannot see and where to go."""
    mood = " (if faintly gloomy)" if gloomy else ""
    return (
        f"You are {name}, a helpful{mood} assistant for this Marvin workspace. Answer conversationally and concisely. "
        "You have NO tools and NO access to the workspace's content here — the entries, collections, assets and "
        f"resources users may call {CONTENT_SYNONYMS}. If a question needs that content (what is in it, a summary "
        "of it, anything grounded in their entries), say you cannot see it and point them to the Ask agent "
        "(grounded answers with citations) or the Marvin agent (full tools) instead of guessing."
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
    tool_policy: dict | None = None  # {category_id | tool_name: allow|block} overrides
    icon: str | None = None
    suggestions: tuple[str, ...] | None = None
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
        tool_allowlist=("search_content", "workspace_overview"),
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
        tool_policy=dict(getattr(row, "tool_policy", None) or {}) or None,
        icon=getattr(row, "icon", None),
        suggestions=tuple(getattr(row, "suggestions", None) or ()) or None,
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


# ── Permission matrix ────────────────────────────────────────────────────────

POLICY_ALLOW = "allow"
POLICY_BLOCK = "block"


def default_policy(spec: AgentSpec, category_id: str) -> str:
    """What a category does when the matrix says nothing: reads allow, writes follow allow_writes."""
    from marvin.services.ai.tools.categories import category_writes

    if not category_writes(category_id):
        return POLICY_ALLOW
    return POLICY_ALLOW if spec.allow_writes else POLICY_BLOCK


def resolve_policy(spec: AgentSpec, tool_name: str, category_id: str, role: int) -> tuple[str, str]:
    """Decide allow|block for one tool and say why.

    Order: the hard allowlist, then a tool-level entry, then a category-level entry, then the
    category default. A write is never allowed to a caller below AUTHOR — an agent cannot do more
    than the user it works for, whatever the matrix says.
    """
    from marvin.services.ai.operations.base import ROLE_AUTHOR
    from marvin.services.ai.tools.categories import category_writes

    if spec.tool_allowlist is not None and tool_name not in spec.tool_allowlist:
        return POLICY_BLOCK, "not in the agent's allowlist"
    policy = spec.tool_policy or {}
    if tool_name in policy:
        decision, reason = policy[tool_name], "tool policy"
    elif category_id in policy:
        decision, reason = policy[category_id], "category policy"
    else:
        decision = default_policy(spec, category_id)
        reason = "category default" if category_writes(category_id) else "read access"
        if category_writes(category_id) and not spec.allow_writes:
            reason = "agent is read-only"
    if decision == POLICY_ALLOW and category_writes(category_id) and role < ROLE_AUTHOR:
        return POLICY_BLOCK, "caller role is below AUTHOR"
    return decision, reason


def permission_matrix(spec: AgentSpec, role: int, catalog: list[dict]) -> list[dict]:
    """Rows for the UI: every category with its default and each known tool's effective decision.

    `catalog` items are {name, category, description, kind} (see catalog_tools). External MCP tools
    are discovered at run time, so their category appears with no tools listed.
    """
    from marvin.services.ai.tools.categories import CATEGORIES

    by_cat: dict[str, list[dict]] = {c.id: [] for c in CATEGORIES}
    for item in catalog:
        by_cat.setdefault(item["category"], []).append(item)
    policy = spec.tool_policy or {}
    rows = []
    for cat in CATEGORIES:
        tools = []
        for item in sorted(by_cat.get(cat.id, []), key=lambda i: i["name"]):
            decision, reason = resolve_policy(spec, item["name"], cat.id, role)
            tools.append({**item, "decision": decision, "reason": reason, "override": policy.get(item["name"])})
        if not tools and cat.id not in ("mcp",):
            continue  # nothing to show for an empty category (keep mcp: it is discovered at run time)
        rows.append(
            {
                "id": cat.id,
                "label": cat.label,
                "writes": cat.writes,
                "description": cat.description,
                "default": policy.get(cat.id) or default_policy(spec, cat.id),
                "override": policy.get(cat.id),
                "tools": tools,
            }
        )
    return rows


def catalog_tools() -> list[dict]:
    """Everything an agent could bind, minus run-time MCP tools: registry tools + AI operations."""
    from marvin.services.ai.operations import list_operations
    from marvin.services.ai.tools import list_tools
    from marvin.services.ai.tools.categories import category_of

    out = [
        {
            "name": t.name,
            "category": category_of(t.name, read_only=t.read_only),
            "description": t.description,
            "kind": "tool",
            "readOnly": t.read_only,
            "minRole": t.min_role,
        }
        for t in list_tools()
        if "agent" in t.sources or t.name in ("list_agents", "run_agent")
    ]
    out += [
        {
            "name": op.slug.replace("-", "_"),
            "category": "ai_ops",
            "description": op.description,
            "kind": "operation",
            "readOnly": False,
            "minRole": op.min_role,
        }
        for op in list_operations()
        if "agent" in op.invocation_sources
    ]
    return out
