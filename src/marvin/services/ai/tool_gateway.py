"""The gate every unattended registry-tool call goes through.

An unattended call is one nobody can be asked about: MarvinMCP's `POST /api/ai/tools/{name}/invoke` today, the
remote MCP server next (tasks/mcp-oauth-plan.md). Each call stands in for the workspace's main agent, `marvin`, so
it passes, in order:

1. the tool's role floor (`min_role`);
2. the invocation source: the tool's declared sources ∩ the workspace's `invocation_sources` policy;
3. Marvin's permission matrix (`agents.unattended_refusal`): Block and Ask first both refuse, and a write is
   refused below EDITOR;
4. the connection's scope: a read-only connection (`allow_writes=False`) runs only read tools;
5. the AI budget, for a tool that calls the workspace's AI provider (`ToolSpec.uses_ai`);
6. the bulk-write / ask-first gate (`bulk_writes.unattended`): a call the agent loop would park answers with its
   refusal instead of running;
7. the Playbook limit, when Playbooks are in effect (`playbook_tool_limit`): a Playbook that lists `allowed-tools`
   narrows the call to those tools, never beyond gates 1-6. The agent loop applies the same limit (`run_agent_loop`'s
   `tool_limit`); an MCP call has no Playbook in effect unless its caller passes `playbooks`.

`visible_tools` applies the same filter to the tool list, so what a caller can't run isn't advertised. Gates 1, 2
and 5 answer with an HTTPException (the REST route returns it as is); gates 3, 4 and 6 answer with an
`{"error": …}` result, as a tool the model called would.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException, status

from marvin.core.root_logger import get_logger
from marvin.services.ai.tools.base import ToolContext, ToolSpec, user_role
from marvin.services.playbooks import LIST_TOOL, LOAD_TOOL, READ_FILE_TOOL

_logger = get_logger(__name__)

READ_ONLY_REFUSAL = "This connection is read-only."


def router_agent(session, group_id):
    """The workspace's main agent, whose permission matrix an unattended call follows."""
    from marvin.services.ai.agents import ROUTER_SLUG, resolve_agent

    spec = resolve_agent(session, group_id, ROUTER_SLUG)
    if spec is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No agent '{ROUTER_SLUG}'.")
    return spec


def check_invocation_source(session, group_id, source: str, declared_sources) -> str:
    """Gate a call by its invocation surface; returns the source it runs under.

    Effective allow-list = the capability's declared sources ∩ the workspace's invocation_sources policy.
    `source` is set by the calling infrastructure (the admin editor sends "editor", the bubble "bubble", the Ask
    page "ask_page", MarvinMCP "mcp", …), so this is surface/feature gating — the per-user authorization wall is
    min_role. The workspace policy is an override map: a source is enabled unless explicitly set false, so an
    unset/None policy allows everything (back-compat). The Ask surfaces are agent chat: a capability declaring
    `agent` takes them, and past the gate they run as `agent`.
    """
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.services.ai.operations.base import INVOCATION_SOURCES, execution_source, source_allowed

    if source not in INVOCATION_SOURCES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown invocation source '{source}'. Valid: {', '.join(INVOCATION_SOURCES)}.",
        )
    runs_as = execution_source(source)
    if runs_as not in declared_sources:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This operation cannot be invoked from the '{source}' source.",
        )
    settings = session.query(WorkspaceAISettingsModel).filter_by(group_id=group_id).first()
    if not source_allowed(settings.invocation_sources if settings else None, source):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This workspace has disabled AI from the '{source}' source.",
        )
    return runs_as


# ── The Playbook limit ───────────────────────────────────────────────────────

# Playbook tools stay available so the agent can keep reading; `load_tools` only brings in tools the limit still judges.
ALWAYS_ALLOWED = (LOAD_TOOL, LIST_TOOL, READ_FILE_TOOL, "load_tools")


def resolve_tool_name(token: str, known) -> str | None:
    """The Marvin tool a Playbook's `allowed-tools` token names, or None when it names nothing this workspace has.

    The standard's tokens are Claude Code's (`Bash(git:*)`, `Read`, `mcp__server__tool`): the qualifier in brackets and an
    `mcp__<server>__` prefix are dropped, and `marvin_find_entries` (MarvinMCP's spelling) matches `find_entries`. Claude
    Code's own tools (`Bash`, `Read`, `Edit`) are not mapped to Marvin tools: a guess would grant or deny the wrong thing."""
    name = token.split("(", 1)[0].strip()
    if name.startswith("mcp__"):
        name = name.split("__", 2)[-1]
    for candidate in (name, name.removeprefix("marvin_")):
        if candidate in known:
            return candidate
    return None


def playbook_tool_limit(playbooks, known) -> frozenset[str] | None:
    """The tool names the Playbooks in effect allow, or None when none of them narrows.

    `known` is every tool name the run could have (the registry plus the run's own); a token naming none of them is
    ignored. A Playbook narrows when it names at least one known tool; one that lists nothing, or nothing Marvin
    knows (a Claude Code Playbook's `Bash(git:*) Read`), says nothing about Marvin's tools and does not narrow, rather
    than locking the agent out of everything.

    Several narrowing Playbooks: the UNION of their lists. Playbooks loaded together each need their own tools, so
    taking the intersection would let loading a second Playbook silently break the first; a union keeps each
    working, and it still never goes beyond the agent's own tools, because the caller intersects the result with them.
    An unrestricted Playbook loaded later does not lift an earlier limit. The Playbook tools are always allowed."""
    from marvin.services.playbooks import parse_allowed_tools

    allowed: set[str] = set()
    for playbook in playbooks:
        names = {n for t in parse_allowed_tools(playbook.allowed_tools) if (n := resolve_tool_name(t, known))}
        allowed |= names
    return frozenset(allowed | set(ALWAYS_ALLOWED)) if allowed else None


def playbook_refusal(name: str, limit: frozenset[str] | None) -> dict | None:
    """The refusal for a call to `name` under `limit` (from `playbook_tool_limit`), or None when it may run."""
    if limit is None or name in limit:
        return None
    allowed = ", ".join(sorted(limit - set(ALWAYS_ALLOWED)))
    return {
        "error": f"The Playbook you loaded limits this task to: {allowed}. '{name}' is not one of them; continue with those or answer without it.",
        "tool": name,
    }


def run_tool_limit(session, group_id, thread=None, scope=None):
    """The `tool_limit` an agent run hands `run_agent_loop`: asked with the run's transcript and tool names, it reads the
    Playbooks in effect (`playbooks_in_effect`: the thread's and the run's, plus the agent's always-load ones, all within
    its chosen set: `scope`) and answers None, or a function refusing the tools they don't allow."""
    from marvin.services.playbooks import playbooks_in_effect

    def limit(convo, known):
        allowed = playbook_tool_limit(playbooks_in_effect(session, group_id, convo, thread, scope), known)
        if allowed is None:
            return None
        return lambda name: json.dumps(refusal) if (refusal := playbook_refusal(name, allowed)) else None

    return limit


def is_read_tool(spec: ToolSpec) -> bool:
    """A tool a read-only connection may see and run: read-only itself, and not in a write category (which leaves
    out `run_agent`, whose child run could write with the user's role rather than the connection's scope)."""
    from marvin.services.ai.tools.categories import category_of, category_writes

    return spec.read_only is True and not category_writes(category_of(spec.name, read_only=spec.read_only))


def visible_tools(session, group_id, user, *, allow_writes: bool = True, extra: tuple[str, ...] = (), playbooks=()) -> list[ToolSpec]:
    """The registry tools an MCP caller is shown: declared for `mcp` (or named in `extra`, tools a caller projects
    itself although they withhold `mcp`), within its role, not blocked by Marvin's matrix, and (on a read-only
    connection) read tools only. An "Ask first" tool stays listed: calling it says where it can run. `playbooks` (the
    ones in effect, default none) narrow the list to what they allow."""
    from marvin.services.ai.agents import POLICY_BLOCK, resolve_policy
    from marvin.services.ai.tools import list_tools
    from marvin.services.ai.tools.categories import category_of

    role = user_role(user, group_id)
    marvin = router_agent(session, group_id)
    registry = list_tools()
    limit = playbook_tool_limit(playbooks, {t.name for t in registry})
    return [
        t
        for t in registry
        if playbook_refusal(t.name, limit) is None
        and ("mcp" in t.sources or t.name in extra)
        and role >= t.min_role
        and resolve_policy(marvin, t.name, category_of(t.name, read_only=t.read_only), role)[0] != POLICY_BLOCK
        and (allow_writes or is_read_tool(t))
    ]


def invoke_unattended(
    session,
    group_id,
    user,
    name: str,
    args: dict | None,
    *,
    source: str = "mcp",
    allow_writes: bool = True,
    extra: tuple[str, ...] = (),
    logger: Any = None,
    playbooks=(),
) -> dict:
    """Run one registry tool for a caller nobody can be asked on behalf of, through every gate (module docstring).

    Returns the tool's JSON result as a dict (`{"result": raw}` when it isn't JSON), or `{"error": …}` when the
    matrix, the scope or the bulk-write gate refuses or the handler raises.
    """
    from marvin.services.ai.agents import unattended_refusal
    from marvin.services.ai.factory import get_workspace_ai_provider
    from marvin.services.ai.tools import bulk_writes, get_tool
    from marvin.services.ai.tools.categories import category_of

    log = logger or _logger
    try:
        spec = get_tool(name)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tool '{name}' not found.") from None

    role = user_role(user, group_id)
    if role < spec.min_role:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role for this tool.")

    # A tool named in `extra` runs from `source` although it withholds it (the remote MCP server's compose_entry).
    check_invocation_source(session, group_id, source, (*spec.sources, source) if spec.name in extra else spec.sources)

    refusal = unattended_refusal(router_agent(session, group_id), spec.name, category_of(spec.name, read_only=spec.read_only), role)
    if refusal is not None:
        return refusal

    if not allow_writes and not is_read_tool(spec):
        return {"error": READ_ONLY_REFUSAL, "tool": spec.name}

    if playbooks:
        from marvin.services.ai.tools import list_tools

        if (refusal := playbook_refusal(spec.name, playbook_tool_limit(playbooks, {t.name for t in list_tools()}))) is not None:
            return refusal

    if spec.uses_ai:
        from marvin.services.ai.budget import blocked_reason

        reason = blocked_reason(session, group_id)
        if reason:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=reason)

    try:
        provider = get_workspace_ai_provider(session, group_id)
    except Exception:
        provider = None  # read tools work without a provider; search reports it's unavailable

    ctx = ToolContext(session=session, group_id=group_id, user=user, provider=provider, logger=log)
    # A handler raising is not fatal (mirrors the agent loop, which surfaces tool errors to the model): roll back
    # any poisoned transaction and return a structured error.
    try:
        raw = bulk_writes.unattended(spec, ctx)(args or {})
    except Exception as e:
        session.rollback()
        log.warning("AI tool '%s' handler failed: %s", name, e)
        return {"error": str(e)}
    # Handlers return a JSON string; hand back a JSON object to the caller.
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {"result": raw}
