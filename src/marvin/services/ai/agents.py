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
    "content by meaning, workspace_overview for what the workspace contains overall, search_docs and read_doc "
    "for how Marvin itself works (cite the manual page's url). Search first, then "
    "answer from the results and name the entries you drew on. If the results don't contain the answer, "
    "say so plainly rather than guessing. Never invent content. If part of a question clearly belongs to "
    "another agent listed below, refer it with suggest_agent (once) and still answer what you can."
)

# Users call the indexed workspace content "the RAG", "the knowledge base", "the index" or "what you know".
# Every persona run gets this preamble so no agent mistakes the vocabulary (Chat once answered a "summary of
# the RAG" with Red/Amber/Green) and knows which tool answers which kind of question. Only tools actually
# bound for the run are mentioned.
CONTENT_SYNONYMS = '"the RAG", "the knowledge base", "the index", "your content" or "what you know"'
# A hand-off once asked Ask (workspace search only) to "answer from the Brain vault"; it searched the workspace
# and reported the results as the vault's. An agent without a source's tools must say so instead.
SOURCE_HONESTY_RULE = (
    "You can only see this workspace's content. If asked about a source outside it — a vault, a notebook, another "
    "app or system — say you cannot reach it from here; never present workspace results as coming from it."
)
# Tool results carry workspace paths (`editUrl`: /workspace/entries/<id>); the backend does not know the UI's
# public host, and the chat renders on that host, so a relative link is the one that always works.
LINKS_RULE = (
    "Links: tool results give ready-made links (reviewLink) and paths such as /workspace/entries/<id> (editUrl). "
    "Use them exactly as given — a bare /workspace/... path is complete. Never prepend a hostname, real or "
    "placeholder (no 'https://yourworkspaceurl/'), even if an earlier turn in this conversation did."
)

# Marvin can't know a site's routes, so an agent once drafted a newsletter listing six works as `[Title](#)`.
# Entry rows carry `url` only when the workspace has told Marvin where entries live (entry type page URL
# pattern + site Canonical URL); without one, the honest output is the bare title and a note, never a fake link.
ENTRY_URL_TOOLS = ("find_entries", "get_entry", "search_content")


def entry_links_rule(tool_names: Iterable[str]) -> str:
    """The entry-linking rule, naming only the bound tools that return an entry `url`."""
    names = set(tool_names)
    sources = " or ".join(t for t in ENTRY_URL_TOOLS if t in names) or "your tools"
    return (
        f"Linking to entries in content you write: use the entry's `url` from {sources} exactly as given — it is "
        "the entry's page on the workspace's site (editUrl is the admin screen, not a public link). Prefer an "
        "absolute https url in content that may be emailed; a url starting with / only works on the site itself. "
        "Never write placeholder links such as [Title](#) or [Title](). If an entry has no `url`, write its title "
        "unlinked and say in your reply that it couldn't be linked. An entry that isn't published yet has a url "
        "that won't be live until it is."
    )


# Asked how to do something in Marvin, an agent without the manual guesses at screens and labels. The manual
# bundled with the running version is the answer, so how-to questions go there first and cite it.
DOCS_RULE = (
    "Questions about Marvin itself — 'how do I…', 'what does … do', its settings, workflows, agents, integrations — "
    "are answered from Marvin's manual: call search_docs before answering, read_doc for the full section, and cite "
    "the page by its url. Use the manual's exact screen and button labels; never guess a label or a setting that the "
    "manual does not show. If the manual does not cover it, say so."
)

# An agent asked to "generate tags for the untagged images" once attached the whole tag vocabulary —
# every colour, portrait and landscape — to each of 19 assets without looking at one. Tags describe
# the item they sit on, so they are chosen per item, from that item.
TAGGING_RULE = (
    "Tagging: choose each item's tags from what THAT item is — never apply the tag vocabulary or a list of "
    "options wholesale, and never give one item contradictory tags. For images, look first: run generate_tags "
    "on each asset (it sees the image) or view_image, then attach only what fits that asset."
)

# Asked to delete test inbox entries, an agent with no remove tool staged no-op revise suggestions ("Deleted test
# inbox entry.") on seven real entries. Archive is the reversible delete; there is no AI hard delete.
REMOVING_RULE = (
    "Deleting or removing entries: call archive_entries — Marvin's reversible delete — and tell the user they were "
    "archived, not deleted, and how to restore them. Never use revise_entry or compose_entry to 'delete' or blank an entry."
)
NO_REMOVE_RULE = (
    "You cannot delete or archive entries here: if asked to, say so and point the user to the entry page. Never use "
    "revise_entry or compose_entry to 'delete' or blank an entry."
)


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
    if "search_docs" in names:
        lines.append(DOCS_RULE)
    servers = external_servers(names)
    if servers:
        listed = ", ".join(f"{slug} ({n} tools, named mcp__{slug}__*)" for slug, n in sorted(servers.items()))
        lines.append(
            f"Connected external sources (MCP servers): {listed}. When the user names one of these — "
            "'check the brain', 'in my vault' — answer from that server's tools yourself, not from workspace "
            "content, and do not hand the question to another agent unless the user names that agent: the "
            "others may not see these sources."
        )
    elif names:
        lines.append(SOURCE_HONESTY_RULE)
    if "attach_tag" in names:
        lines.append(TAGGING_RULE)
    if "archive_entries" in names:
        lines.append(REMOVING_RULE)
    elif names.intersection(("revise_entry", "compose_entry")):
        lines.append(NO_REMOVE_RULE)
    if names.intersection(ENTRY_URL_TOOLS):
        lines.append(entry_links_rule(names))
    if names:
        lines.append(
            "Act, don't announce: when a question needs a tool, call it in this same turn. Never reply with "
            "'let me check' or 'give me a moment' — there is no later turn."
        )
        lines.append(LINKS_RULE)
    return "\n".join(lines)


def model_agent_system_prompt(name: str, *, gloomy: bool = False, router_name: str = "Marvin") -> str:
    """System prompt for a `model` agent (plain conversation, no tools): says what it cannot see and where to go.
    `router_name` is the workspace's main agent as users know it (its assistant name)."""
    mood = " (if faintly gloomy)" if gloomy else ""
    return (
        f"You are {name}, a helpful{mood} assistant for this Marvin workspace. Answer conversationally and concisely. "
        "You have NO tools and NO access to the workspace's content here — the entries, collections, assets and "
        f"resources users may call {CONTENT_SYNONYMS}. If a question needs that content (what is in it, a summary "
        "of it, anything grounded in their entries), say you cannot see it and point them to the Ask agent "
        f"(grounded answers with citations) or the {router_name} agent (full tools) instead of guessing."
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
    # One line for the router's roster: when Marvin should hand a question to this agent.
    handoff_hint: str | None = None
    is_system: bool = False
    id: str | None = None
    # The bubble's character while this agent talks, as stored (an own pack or {"library": id}); None →
    # the workspace's. System agents have none: they're code, and `marvin` *is* the workspace's character.
    character: dict | None = None
    # A built-in agent whose matrix this workspace changed (Settings → AI → Agents): `tool_policy` is then
    # the code default with the workspace's override merged over it (see `_system_agent`).
    tool_policy_overridden: bool = False


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
        # suggest_agent runs nothing: Ask can point the user at a specialist but never calls one.
        tool_allowlist=("search_content", "workspace_overview", "search_docs", "read_doc", "suggest_agent"),
        handoff_hint="the user wants a grounded answer from the workspace content, with citations",
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
# Built-ins whose permission matrix a workspace admin may change (and nothing else about them). `chat` is a
# model agent: it binds no tools, so it has no matrix to change.
BUILTIN_POLICY_SLUGS = tuple(slug for slug, spec in SYSTEM_AGENTS.items() if spec.kind == "persona")


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
        handoff_hint=getattr(row, "handoff_hint", None) or None,
        is_system=False,
        id=str(row.id),
        character=getattr(row, "character", None) or None,
    )


def unsaved_spec(values: dict, slug: str) -> AgentSpec:
    """An agent definition not saved yet (a create payload's fields), read as `spec_from_row` reads it once saved."""
    from dataclasses import replace
    from types import SimpleNamespace

    return replace(spec_from_row(SimpleNamespace(**values, slug=slug, id=None, character=None)), id=None)


def _ai_settings(session, group_id):
    """The workspace's AI settings row (assistant name, built-in matrix overrides), or None."""
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    return session.query(WorkspaceAISettingsModel).filter_by(group_id=group_id).first() if session is not None else None


def _clean_policy(policy) -> dict[str, str] | None:
    """A matrix with only well-formed entries: a value other than allow/ask/block is dropped, never trusted."""
    if not isinstance(policy, dict):
        return None
    clean = {k: v for k, v in policy.items() if isinstance(k, str) and v in POLICY_VALUES}
    return clean or None


def clean_builtin_policies(value) -> dict | None:
    """An `agent_tool_policies` value (stored or imported) with only the editable built-ins' well-formed matrices."""
    if not isinstance(value, dict):
        return None
    out = {slug: p for slug in BUILTIN_POLICY_SLUGS if (p := _clean_policy(value.get(slug)))}
    return out or None


def builtin_policy_override(settings, slug: str) -> dict[str, str] | None:
    """This workspace's stored matrix override of built-in `slug` (from its AI settings row), or None."""
    return (clean_builtin_policies(getattr(settings, "agent_tool_policies", None)) or {}).get(slug)


def with_builtin_override(settings, slug: str, policy: dict | None) -> dict | None:
    """The settings row's new `agent_tool_policies` with `slug`'s override replaced — or removed when
    `policy` is empty or None (back to the code default). A new dict, so the JSON column sees the change."""
    stored = getattr(settings, "agent_tool_policies", None)
    out = {k: v for k, v in stored.items() if k != slug} if isinstance(stored, dict) else {}
    if policy:
        out[slug] = dict(policy)
    return out or None


def _system_agent(settings, spec: AgentSpec) -> AgentSpec:
    """A system agent as this workspace knows it — the one place a built-in is resolved, so every consumer
    (bubble, Ask page, hand-offs, MCP `run_agent`, direct invoke and its tool listing) sees the same agent:

    - the main agent (`marvin`) carries the workspace's assistant name (AI settings → Persona);
    - a workspace override of its permission matrix (Settings → AI → Agents) is merged over the code
      default. Only the matrix: the prompt, model, allowlist and the rest stay as defined in code, and
      `resolve_policy`'s floors (allowlist, EDITOR for writes) apply to the merged matrix as to any other.
    """
    from dataclasses import replace

    changes: dict = {}
    if spec.slug == ROUTER_SLUG:
        from marvin.services.ai.persona import resolve_persona

        name, _persona = resolve_persona(getattr(settings, "assistant_name", None), getattr(settings, "persona_prompt", None))
        if isinstance(name, str) and name != spec.name:
            changes["name"] = name
    override = builtin_policy_override(settings, spec.slug)
    if override:
        changes["tool_policy"] = {**(spec.tool_policy or {}), **override}
        changes["tool_policy_overridden"] = True
    return replace(spec, **changes) if changes else spec


def list_agents(session, group_id) -> list[AgentSpec]:
    """System agents first, then the workspace's rows by slug."""
    from marvin.db.models.groups.agents import WorkspaceAgentModel

    settings = _ai_settings(session, group_id)
    rows = session.query(WorkspaceAgentModel).filter_by(group_id=group_id).order_by(WorkspaceAgentModel.slug).all()
    return [*(_system_agent(settings, s) for s in SYSTEM_AGENTS.values()), *(spec_from_row(r) for r in rows)]


def agent_names(session, group_id) -> dict[str, str]:
    """`{slug: name}` for every agent, the main agent under the workspace's assistant name."""
    return {s.slug: s.name for s in list_agents(session, group_id)}


def operation_label(operation_slug: str, names: dict[str, str]) -> str:
    """How an execution's operation reads: an agent run shows the agent's current name, so renaming the
    assistant renames its history too. The stored `agent:<slug>` stays stable for filtering."""
    if operation_slug == "agent":  # the bubble's main-agent runs were stored without the slug
        operation_slug = f"agent:{ROUTER_SLUG}"
    if not operation_slug.startswith("agent:"):
        return operation_slug
    slug = operation_slug.split(":", 1)[1]
    return f"agent:{names.get(slug, slug)}"


def resolve_agent(session, group_id, slug: str) -> AgentSpec | None:
    slug = (slug or "").strip().lower()
    if slug in SYSTEM_AGENTS:
        return _system_agent(_ai_settings(session, group_id), SYSTEM_AGENTS[slug])
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


# ── Router roster (hand-offs + referrals) ────────────────────────────────────

# Agents never listed on a roster: the router itself and the tool-less base model.
ROSTER_EXCLUDED = ("marvin", "chat")

HANDOFF_RULES = (
    "Hand-off rules: when the user names one of these agents, asks for its voice or its kind of answer, or "
    "the question matches an agent's 'Hand off when' line, hand it off — do NOT imitate that agent yourself, "
    "even if you have the tools to look the facts up. Otherwise answer with your own tools. To hand off, call "
    "run_agent with the user's question verbatim plus any context from this conversation the agent needs, "
    'then answer the user in your OWN voice, naming the agent you asked ("I checked with Materials: …"): restate '
    "what it said faithfully, never paste its reply verbatim. If a request needs a specialist's voice AND an "
    "action only you can do (authoring a draft, attaching, running a workflow), ask the specialist for the text "
    "first, then do the action yourself with what it gave you. If a run_agent result carries `referrals`, do NOT "
    "call the referred agent — tell the user in one line who to ask and why."
)
REFERRAL_RULES = (
    "Referral rules: you cannot hand questions off. Answer what you can with your own tools. If part of the "
    "question clearly belongs to one of these agents, call suggest_agent ONCE with that part and finish your "
    "own answer — never claim you asked them."
)


def roster_block(specs: Iterable[AgentSpec], running_slug: str, role: int, source: str = "agent", *, can_handoff: bool = True) -> str:
    """The roster a persona run sees: the agents the caller may talk to, and the hand-off or referral rules.

    Lists every agent the caller `may_talk` to from `source`, excluding the running agent, the router and
    the base model. Empty when there is nobody to list — rules about agents that are not there are noise.
    """
    lines = []
    for spec in specs:
        if spec.slug == running_slug or spec.slug in ROSTER_EXCLUDED:
            continue
        if not may_talk(spec, role, source)[0]:
            continue
        what = (spec.description or spec.name).rstrip(". ")
        when = (spec.handoff_hint or what).rstrip(". ")
        lines.append(f"- {spec.slug} — {spec.name}: {what}. Hand off when: {when}.")
    if not lines:
        return ""
    rules = HANDOFF_RULES if can_handoff else REFERRAL_RULES
    return "\n".join(["## Other agents in this workspace", *lines, "", rules])


# ── Permission matrix ────────────────────────────────────────────────────────

POLICY_ALLOW = "allow"
POLICY_BLOCK = "block"
# "Ask first": the tool is bound, but each call pauses the run for the user's approval (needs a
# thread to park on — Ask threads; from MCP an ask-first tool is simply not bound).
POLICY_ASK = "ask"
POLICY_VALUES = (POLICY_ALLOW, POLICY_ASK, POLICY_BLOCK)


ROUTER_SLUG = "marvin"
HANDOFF_CATEGORY = "agents_run"
# The router's outward-reaching writes: not undoable from the inbox, so Marvin asks before each one.
# Its in-workspace writes (authoring, links, AI ops) are already soft-gated by drafts/staging.
ROUTER_ASK_CATEGORIES = ("automation_run", "mcp", "mcp_destructive")


def default_policy(spec: AgentSpec, category_id: str) -> str:
    """What a category does when the matrix says nothing.

    Reads allow. Hand-offs (`agents_run`) are the exception: only the system router `marvin`
    delegates by default; any other agent must be allowed explicitly in its matrix. Writes:

    - a custom agent with `allow_writes` *asks first* for every write category (turn it off per
      category/tool in the matrix); without `allow_writes` writes are blocked;
    - the router `marvin` allows its in-workspace writes and asks first for `ROUTER_ASK_CATEGORIES`.

    "Ask first" needs a thread to park on. From a run with no thread (MCP `run_agent`, a delegated
    child, an API call without a thread id) ask means *not bound*.
    """
    from marvin.services.ai.tools.categories import category_writes

    is_router = spec.is_system and spec.slug == ROUTER_SLUG
    if category_id == HANDOFF_CATEGORY:
        return POLICY_ALLOW if is_router else POLICY_BLOCK
    if not category_writes(category_id):
        return POLICY_ALLOW
    if is_router:
        return POLICY_ASK if category_id in ROUTER_ASK_CATEGORIES else POLICY_ALLOW
    return POLICY_ASK if spec.allow_writes else POLICY_BLOCK


def resolve_policy(spec: AgentSpec, tool_name: str, category_id: str, role: int) -> tuple[str, str]:
    """Decide allow|ask|block for one tool and say why.

    Order: the hard allowlist, then a tool-level entry, then a category-level entry, then the
    category default. A write is never allowed to a caller below EDITOR — an agent cannot do more
    than the user it works for, whatever the matrix says; that holds for "ask" too, since approving
    a write is doing it. EDITOR, not AUTHOR: agent writes (links, revisions, AI write-back, external
    MCP writes) reach any entry, and an AUTHOR may change only their own drafts.
    """
    from marvin.services.ai.operations.base import ROLE_EDITOR
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
        if category_id == HANDOFF_CATEGORY:
            reason = "router default" if decision == POLICY_ALLOW else "hand-offs are off unless allowed"
        elif not category_writes(category_id):
            reason = "read access"
        elif decision == POLICY_ASK:
            reason = "ask first (default)"
        elif decision == POLICY_ALLOW:
            reason = "router default" if (spec.is_system and spec.slug == ROUTER_SLUG) else "category default"
        else:
            reason = "agent is read-only" if not spec.allow_writes else "category default"
    if decision in (POLICY_ALLOW, POLICY_ASK) and category_writes(category_id) and role < ROLE_EDITOR:
        return POLICY_BLOCK, "caller role is below EDITOR"
    return decision, reason


def unattended_refusal(spec: AgentSpec, tool_name: str, category_id: str, role: int) -> dict | None:
    """`resolve_policy` for a call nobody can approve (MarvinMCP's direct invoke): None when the matrix
    allows the tool, else the refusal to answer with. "Ask first" refuses too — the call cannot pause."""
    from marvin.services.ai.tools.categories import CATEGORY_BY_ID

    decision, reason = resolve_policy(spec, tool_name, category_id, role)
    if decision == POLICY_ALLOW:
        return None
    cat = CATEGORY_BY_ID.get(category_id)
    label = f"“{cat.label if cat else category_id}”"
    where = "Settings → AI → Agents"
    if decision == POLICY_ASK:
        error = (
            f"Not done: {tool_name} is in {label}, which is set to Ask first for {spec.name} in this workspace, and this call "
            "cannot pause for approval. Run it from the Ask page or an agent conversation, where it can be approved"
        )
        # Every agent a direct call can stand in for has an editable matrix (built-ins: Settings → AI → Agents).
        error += f", or set {label} to Allow for {spec.name} ({where})."
    elif reason == "caller role is below EDITOR":
        error = f"Not done: {tool_name} writes, and {spec.name} writes only for an EDITOR or above."
    else:
        error = f"Not done: {tool_name} is in {label}, which is switched off for {spec.name} in this workspace ({where})."
    return {"error": error, "tool": tool_name, "category": category_id, "policy": decision, "reason": reason}


def permission_matrix(spec: AgentSpec, role: int, catalog: list[dict]) -> list[dict]:
    """Rows for the UI: every category with its default and each known tool's effective decision.

    `catalog` items are {name, category, description, kind} (see catalog_tools). External MCP tools
    are discovered at run time, so their category appears with no tools listed.
    """
    from marvin.services.ai.tools.categories import CATEGORIES, MCP_CATEGORIES

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
        if not tools and cat.id not in MCP_CATEGORIES:
            continue  # nothing to show for an empty category (keep the MCP rows: discovered at run time)
        rows.append(
            {
                "id": cat.id,
                "label": cat.label,
                "writes": cat.writes,
                "description": cat.description,
                "default": policy.get(cat.id) or default_policy(spec, cat.id),
                "override": policy.get(cat.id),
                # What the row does with no entry in the matrix (the editor's "Default (…)" choice).
                "inherited": default_policy(spec, cat.id),
                "tools": tools,
            }
        )
    return rows


def catalog_tools() -> list[dict]:
    """Everything an agent could bind, minus run-time MCP tools (the controller adds those): registry tools + AI operations."""
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
