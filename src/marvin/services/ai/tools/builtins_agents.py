"""
Agent tools: discover and converse with the workspace's agents.

- From MCP / API (MarvinMCP → Claude / n8n / ChatGPT) `run_agent` is the v1 interop surface: any
  agent, one message, its answer — the standalone runner below, registry tools only (AI operations
  and external MCP tools reach an agent through the HTTP endpoint, a documented v1 limit).
- From the "agent" source (slice D, "Marvin as router") agent-calls-agent is allowed at depth 0 only:
  the controller sets `ctx.delegate`, and `run_agent` hands the call to it so the child runs through
  the real `_run_agent_core` (its own matrix, a child thread, live steps). A delegated run (depth 1)
  never gets `run_agent` bound; it *refers* with `suggest_agent`, which runs nothing.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

from marvin.services.ai.operations.base import ROLE_EDITOR

from .base import ToolContext, caller_role, register_tool

_EXTERNAL_SOURCES = ("mcp", "api", "editor", "agent")
_RUN_SOURCES = ("mcp", "api", "agent")
# How much of a referral is kept: enough to pre-fill the next question, never a transcript.
REFERRAL_QUESTION_MAX = 500
REFERRAL_REASON_MAX = 300


@register_tool(
    name="list_agents",
    description=(
        "List this workspace's AI agents — the built-ins (marvin, ask, chat) and any user-defined ones — "
        "with slug, name, kind (persona | model), description, whether you may run each, and canWrite: whether "
        "it may change things for this user (create, edit, attach). Use before run_agent, and before suggest_agent "
        "to find an agent that can do what you can't. Pass `tool` (e.g. attach_asset) to also get, per agent, "
        "canUseTool: whether its permissions let it run that tool for this user."
    ),
    input_schema={
        "type": "object",
        "properties": {"tool": {"type": "string", "description": "a tool name; each agent then says whether it may run it (canUseTool)"}},
    },
    sources=_EXTERNAL_SOURCES,
)
def list_agents(ctx: ToolContext, args: dict) -> str:
    from marvin.services.ai.agents import agents_that_can, may_talk
    from marvin.services.ai.agents import list_agents as _list

    role = caller_role(ctx)
    specs = _list(ctx.session, ctx.group_id)
    tool = str(args.get("tool") or "").strip()
    capable = {}
    if tool:
        found, error = _tool_category(tool)
        if error:
            return json.dumps({"error": error})
        capable = {s.slug: d for s, d in agents_that_can(specs, tool, found, role, ctx.source or "mcp")}
    out = []
    for spec in specs:
        ok, reason = may_talk(spec, role, ctx.source or "mcp")
        out.append(
            {
                "slug": spec.slug,
                "name": spec.name,
                "kind": spec.kind,
                "description": spec.description,
                "isSystem": spec.is_system,
                "enabled": spec.enabled,
                "canRun": ok,
                # Writes need both: the agent binds write tools, and the user may write (Editor or above).
                "canWrite": bool(spec.allow_writes) and role >= ROLE_EDITOR,
                **({"reason": reason} if not ok else {}),
                **({"canUseTool": spec.slug in capable, **({"toolPolicy": capable[spec.slug]} if spec.slug in capable else {})} if tool else {}),
            }
        )
    return json.dumps({"agents": out, "count": len(out)})


def _tool_category(tool: str) -> tuple[str, str | None]:
    """(category id, None) for a registry tool an agent can bind, else ("", the error to answer with)."""
    from marvin.services.ai.tools import list_tools
    from marvin.services.ai.tools.categories import category_of

    spec = next((s for s in list_tools() if s.name == tool), None)
    if spec is None or "agent" not in spec.sources:
        writers = sorted(s.name for s in list_tools() if "agent" in s.sources and not s.read_only)
        return "", f"unknown tool '{tool}' — use the name of a tool, one of: {', '.join(writers)}"
    return category_of(spec.name, read_only=spec.read_only), None


@register_tool(
    name="run_agent",
    uses_ai=True,
    description=(
        "Hand a question to another workspace agent (see list_agents / the roster in your instructions) and get "
        "its answer back. Use it when the question belongs to that agent or the user asks for that agent's "
        "voice. From an external client it is how you converse with a Marvin agent; optional history (prior "
        "turns, oldest first) gives it memory of the conversation."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "agent": {"type": "string", "description": "agent slug, e.g. 'marvin', 'ask', 'workshop'"},
            "message": {"type": "string", "description": "the user's message / goal"},
            "history": {
                "type": "array",
                "description": "prior turns, oldest first, excluding this message",
                "items": {
                    "type": "object",
                    "properties": {"role": {"type": "string", "enum": ["user", "assistant"]}, "content": {"type": "string"}},
                    "required": ["role", "content"],
                },
            },
            "max_steps": {"type": "integer", "description": "tool-call budget (default 6, max 12)"},
            "tone": {
                "type": "string",
                "description": (
                    "how the answer reads: a tone slug such as 'professional' (plain, no character), 'auto' or 'playful' "
                    "(in the agent's character), or one of the workspace's own. Default: the agent's own default tone, "
                    "else professional"
                ),
            },
        },
        "required": ["agent", "message"],
    },
    sources=_RUN_SOURCES,
    read_only=False,
)
def run_agent(ctx: ToolContext, args: dict) -> str:
    if ctx.delegate is not None:
        # A router run: the controller's delegate runs the specialist for real (matrix, child thread,
        # live steps) and returns the result dict; it never raises.
        return json.dumps(ctx.delegate(str(args.get("agent") or ""), str(args.get("message") or "").strip(), args.get("max_steps")))
    return _run_standalone(ctx, args)


def standalone_tools(spec, ctx: ToolContext, role: int) -> list:
    """The registry tools a stateless run binds: the agent's Allow tools at the caller's role.

    "ask" counts as blocked — a run from MCP has no user to approve mid-loop — and for the same reason each
    tool runs unattended: a call the agent loop would park (a big bulk write, an ask-first call) is refused.
    """
    from marvin.services.ai.agent import AgentTool
    from marvin.services.ai.agents import POLICY_ALLOW, resolve_policy
    from marvin.services.ai.tools import bulk_writes, list_tools
    from marvin.services.ai.tools.categories import category_of

    tools: list = []
    for s in list_tools():
        if "agent" not in s.sources or role < s.min_role or s.name in ("run_agent", "list_agents"):
            continue  # no recursion from a stateless run; suggest_agent stays so the child can refer
        cat = category_of(s.name, read_only=s.read_only)
        if resolve_policy(spec, s.name, cat, role)[0] != POLICY_ALLOW:
            continue
        tools.append(AgentTool(name=s.name, description=s.description, input_schema=s.input_schema, run=bulk_writes.unattended(s, ctx), category=cat))
    return tools


def _character_section(ctx: ToolContext, spec, tone: str | None) -> str:
    """The Character / tone section an external client's run of `spec` ends its system prompt with: the caller's
    `tone`, else the agent's own default tone, else professional — which drops the character — so over MCP an
    agent answers plainly unless its owner or the caller chose otherwise. A tone that lets the character in uses
    the agent's own Character, else the workspace's."""
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.services.ai.agents import agent_persona
    from marvin.services.ai.tones import PROFESSIONAL, tone_clause, workspace_tones

    _, persona = agent_persona(ctx.session, ctx.group_id, spec)
    row = ctx.session.query(WorkspaceAISettingsModel).filter_by(group_id=ctx.group_id).first()
    requested = str(tone).strip().lower() if tone else None
    return tone_clause(workspace_tones(row).resolve(requested, spec.default_register, PROFESSIONAL), persona)


def _run_standalone(ctx: ToolContext, args: dict) -> str:
    """The stateless MCP/API runner: registry tools only, client-supplied history, no thread."""
    from marvin.core.config import get_app_settings
    from marvin.db.models.groups.ai_executions import AIExecutionModel
    from marvin.services.ai.agent import run_agent_loop
    from marvin.services.ai.agents import may_talk, resolve_agent
    from marvin.services.ai.base import CompletionOptions, Message
    from marvin.services.ai.pricing import estimate_cost

    spec = resolve_agent(ctx.session, ctx.group_id, str(args.get("agent") or ""))
    if spec is None:
        return json.dumps({"error": f"unknown agent '{args.get('agent')}' — call list_agents"})
    role = caller_role(ctx)
    ok, reason = may_talk(spec, role, "mcp")
    if not ok:
        return json.dumps({"error": reason})
    message = str(args.get("message") or "").strip()
    if not message:
        return json.dumps({"error": "message is required"})

    provider = ctx.provider
    if provider is None:
        return json.dumps({"error": "no AI provider configured for this workspace"})
    model = spec.model_override or _default_model(ctx)
    if not model:
        return json.dumps({"error": "no model configured — set a default model on the provider"})

    history = [
        Message(role=h["role"], content=str(h.get("content") or ""))
        for h in (args.get("history") or [])[-12:]
        if isinstance(h, dict) and h.get("role") in ("user", "assistant")
    ]
    system = spec.system_prompt or (
        f"You are {spec.name}, an assistant for this headless-CMS workspace. Use the provided tools to search, "
        "browse, and (only when asked) author content. Prefer tools over guessing and ground your answer in "
        "what they return. Authoring creates a DRAFT for human review — never claim anything is published. Be concise."
    )
    system += _character_section(ctx, spec, args.get("tone"))
    messages = [Message(role="system", content=system), *history, Message(role="user", content=message)]

    tools = standalone_tools(spec, ctx, role) if spec.kind == "persona" else []

    _app = get_app_settings()
    opts = CompletionOptions(temperature=_app.AI_DEFAULT_TEMPERATURE, max_tokens=None)
    max_steps = max(1, min(int(args.get("max_steps") or 6), 12))

    execution = AIExecutionModel(
        session=ctx.session,
        group_id=ctx.group_id,
        operation_slug=f"agent:{spec.slug}",
        provider_type=provider.provider_type,
        model_id=model,
        status="running",
        triggered_by=getattr(ctx.user, "id", None),
        trigger_type="mcp",
        input_json={"message": message},
    )
    execution.started_at = datetime.now(UTC)
    ctx.session.add(execution)
    ctx.session.commit()
    start = time.monotonic()
    referrals_mark = len(ctx.referrals)
    try:
        if spec.kind == "model" or not tools:
            res = provider.complete(messages, model, opts)
            answer, steps = res.content if hasattr(res, "content") else str(res), []
            p_tok, c_tok, t_tok = getattr(res, "prompt_tokens", 0), getattr(res, "completion_tokens", 0), getattr(res, "total_tokens", 0)
            cached_tok, written_tok = getattr(res, "cached_prompt_tokens", 0) or 0, getattr(res, "cache_write_tokens", 0) or 0
        else:
            res = run_agent_loop(provider, model, messages, tools, opts, max_steps=max_steps)
            answer, steps = res.answer, [{"tool": s.tool, "arguments": s.arguments} for s in res.steps]
            p_tok, c_tok, t_tok = res.prompt_tokens, res.completion_tokens, res.total_tokens
            cached_tok, written_tok = getattr(res, "cached_prompt_tokens", 0) or 0, getattr(res, "cache_write_tokens", 0) or 0
    except Exception as e:  # noqa: BLE001 — surface to the caller, never raise into a tool
        execution.status = "failed"
        execution.error_message = str(e)[:2000]
        execution.completed_at = datetime.now(UTC)
        execution.duration_ms = int((time.monotonic() - start) * 1000)
        ctx.session.commit()
        return json.dumps({"error": f"agent '{spec.slug}' failed: {e}", "executionId": str(execution.id)})

    execution.status = "completed"
    execution.completed_at = datetime.now(UTC)
    execution.duration_ms = int((time.monotonic() - start) * 1000)
    execution.prompt_tokens, execution.completion_tokens, execution.total_tokens = p_tok, c_tok, t_tok
    execution.cached_prompt_tokens, execution.cache_write_tokens = cached_tok, written_tok
    execution.estimated_cost_usd = estimate_cost(provider.provider_type, model, p_tok, c_tok, cached_tok, written_tok)
    execution.output_json = {"answer": answer, "steps": steps}
    ctx.session.commit()
    return json.dumps(
        {
            "agent": spec.slug,
            "answer": answer,
            "steps": steps,
            "referrals": ctx.referrals[referrals_mark:],
            "executionId": str(execution.id),
            "totalTokens": t_tok,
        }
    )


@register_tool(
    name="suggest_agent",
    description=(
        "Refer the user to another workspace agent (see list_agents) WITHOUT running it. Use when part of the "
        "question clearly belongs to a different agent, or asks for something you can't do. For a change you can't "
        "make (create, edit, attach), set `tool` to the tool it needs (attach_asset, attach_tag, create_draft, "
        "update_draft, revise_entry…): the workspace then picks the agent whose permissions let it run THAT tool for "
        "this user, the main agent (marvin) first, and `agent` becomes optional. Put what you found in `context` "
        "(entry slug, asset ids, short summary) so that agent need not ask again; it still checks permissions "
        "itself. If no agent may run the tool you get back which setting would allow one: tell the user that, in "
        "one line. The user gets a button that sends the request there. Records the referral for the caller to "
        "surface; you still answer what you can yourself. Call it at most once per answer."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "agent": {"type": "string", "description": "slug of the agent to refer to (optional with `tool`: marvin unless told otherwise)"},
            "question": {"type": "string", "description": "the question to ask that agent, as the user would phrase it"},
            "reason": {"type": "string", "description": "one short line: why that agent, not you"},
            "tool": {"type": "string", "description": "the tool the change needs, e.g. attach_asset; the workspace finds an agent that may run it"},
            "context": {
                "type": "object",
                "description": "what you found, for the agent to act on without asking again — ids and slugs only, plus a short note",
                "properties": {
                    "entry": {"type": "string", "description": "the entry's slug or id"},
                    "assetIds": {"type": "array", "items": {"type": "string"}, "description": "asset ids you chose (up to 20)"},
                    "summary": {"type": "string", "description": "one or two lines: what you found or decided"},
                },
            },
        },
        "required": ["question"],
    },
    sources=("agent", "mcp", "api"),
)
def suggest_agent(ctx: ToolContext, args: dict) -> str:
    from marvin.services.ai.agents import (
        AGENT_SETTINGS_PATH,
        AGENT_SETTINGS_URL,
        agents_that_can,
        clean_handoff_context,
        how_to_allow,
        list_agents,
        resolve_agent,
    )

    slug = str(args.get("agent") or "").strip().lower()
    tool = str(args.get("tool") or "").strip()
    decision = None
    if tool:
        category, error = _tool_category(tool)
        if error:
            return json.dumps({"error": error})
        specs = list_agents(ctx.session, ctx.group_id)
        role, source = caller_role(ctx), ctx.source or "mcp"
        capable = agents_that_can(specs, tool, category, role, source)
        if not capable:
            how = how_to_allow(specs, tool, category, role, source)
            return json.dumps(
                {
                    "recorded": False,
                    "tool": tool,
                    "blocked": f"No agent may run {tool} for this user right now. {how}",
                    "settingsUrl": AGENT_SETTINGS_URL,
                    "next": (
                        "Nothing was handed off. Finish your own answer and tell the user in one line that no agent may do "
                        f"this yet: {how} (link: [{AGENT_SETTINGS_PATH}]({AGENT_SETTINGS_URL}))."
                    ),
                }
            )
        # The named agent when it may run the tool, else the best that may (marvin first).
        chosen = next(((s, d) for s, d in capable if s.slug == slug), capable[0])
        spec, decision = chosen
    else:
        spec = resolve_agent(ctx.session, ctx.group_id, slug)
        if spec is None:
            return json.dumps({"error": f"unknown agent '{slug}' — call list_agents"})
        if not spec.enabled:
            return json.dumps({"error": f"agent '{spec.slug}' is disabled"})
    referral = {
        "agent": spec.slug,
        "name": spec.name,
        "question": str(args.get("question") or "").strip()[:REFERRAL_QUESTION_MAX],
        "reason": str(args.get("reason") or "").strip()[:REFERRAL_REASON_MAX],
    }
    if tool:
        referral["tool"] = tool
        if context := clean_handoff_context(args.get("context")):
            referral["context"] = context
        if not referral["reason"]:
            referral["reason"] = f"{spec.name} may run {tool} for you" + (" (it asks you first)" if decision == "ask" else "")
    ctx.referrals.append(referral)
    redirected = bool(tool and slug and slug != spec.slug)
    return json.dumps(
        {
            "recorded": True,
            "agent": spec.slug,
            "name": spec.name,
            **({"context": referral["context"]} if "context" in referral else {}),
            "next": (
                (f"{slug} may not run {tool} for this user, so the referral went to {spec.name} instead. " if redirected else "")
                + f"The referral to {spec.name} is recorded and will be shown to the user. Do NOT call that agent. "
                "Finish your own answer now and mention in one line that this part is for "
                f"{spec.name}."
            ),
        }
    )


def _default_model(ctx: ToolContext) -> str | None:
    """The workspace's default model, mirroring the controller's `_default_model` (settings row, then provider)."""
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    row = ctx.session.query(WorkspaceAISettingsModel).filter_by(group_id=ctx.group_id).first()
    for attr in ("default_model", "model", "model_id"):
        v = getattr(row, attr, None) if row else None
        if v:
            return str(v)
    for attr in ("default_model", "model"):
        v = getattr(ctx.provider, attr, None)
        if v:
            return str(v)
    return None
