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
        "with slug, name, kind (persona | model), description, and whether you may run each. "
        "Use before run_agent."
    ),
    input_schema={"type": "object", "properties": {}},
    sources=_EXTERNAL_SOURCES,
)
def list_agents(ctx: ToolContext, _args: dict) -> str:
    from marvin.services.ai.agents import list_agents as _list
    from marvin.services.ai.agents import may_talk

    role = caller_role(ctx)
    out = []
    for spec in _list(ctx.session, ctx.group_id):
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
                **({"reason": reason} if not ok else {}),
            }
        )
    return json.dumps({"agents": out, "count": len(out)})


@register_tool(
    name="run_agent",
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


def _run_standalone(ctx: ToolContext, args: dict) -> str:
    """The stateless MCP/API runner: registry tools only, client-supplied history, no thread."""
    from marvin.core.config import get_app_settings
    from marvin.db.models.groups.ai_executions import AIExecutionModel
    from marvin.services.ai.agent import AgentTool, run_agent_loop
    from marvin.services.ai.agents import may_talk, resolve_agent
    from marvin.services.ai.base import CompletionOptions, Message
    from marvin.services.ai.pricing import estimate_cost
    from marvin.services.ai.tools import list_tools

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
    messages = [Message(role="system", content=system), *history, Message(role="user", content=message)]

    tools: list = []
    if spec.kind == "persona":
        from marvin.services.ai.agents import POLICY_ALLOW, resolve_policy
        from marvin.services.ai.tools.categories import category_of

        for s in list_tools():
            if "agent" not in s.sources or role < s.min_role or s.name in ("run_agent", "list_agents"):
                continue  # no recursion from a stateless run; suggest_agent stays so the child can refer
            cat = category_of(s.name, read_only=s.read_only)
            # "ask" counts as blocked here: a run from MCP has no user to approve mid-loop.
            if resolve_policy(spec, s.name, cat, role)[0] != POLICY_ALLOW:
                continue
            tools.append(
                AgentTool(name=s.name, description=s.description, input_schema=s.input_schema, run=(lambda a, s=s: s.handler(ctx, a)), category=cat)
            )

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
        else:
            res = run_agent_loop(provider, model, messages, tools, opts, max_steps=max_steps)
            answer, steps = res.answer, [{"tool": s.tool, "arguments": s.arguments} for s in res.steps]
            p_tok, c_tok, t_tok = res.prompt_tokens, res.completion_tokens, res.total_tokens
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
    execution.estimated_cost_usd = estimate_cost(provider.provider_type, model, p_tok, c_tok)
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
        "question clearly belongs to a different agent. Records the referral for the caller to surface; you still "
        "answer what you can yourself. Call it at most once per answer."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "agent": {"type": "string", "description": "slug of the agent to refer to"},
            "question": {"type": "string", "description": "the question to ask that agent, as the user would phrase it"},
            "reason": {"type": "string", "description": "one short line: why that agent, not you"},
        },
        "required": ["agent", "question"],
    },
    sources=("agent", "mcp", "api"),
)
def suggest_agent(ctx: ToolContext, args: dict) -> str:
    from marvin.services.ai.agents import resolve_agent

    slug = str(args.get("agent") or "").strip().lower()
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
    ctx.referrals.append(referral)
    return json.dumps(
        {
            "recorded": True,
            "agent": spec.slug,
            "name": spec.name,
            "next": (
                f"The referral to {spec.name} is recorded and will be shown to the user. Do NOT call that agent. "
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
