"""Talking to OpenAI-style APIs without per-model code.

The official OpenAI API is called through the **Responses API**, OpenAI's current interface: every model
takes the same length limit (`max_output_tokens`) and function tools work while the model reasons — the
two things the older Chat Completions endpoint made model-specific. Chat Completions stays for what still
needs it: OpenAI-compatible servers (a custom base URL) and Azure OpenAI deployments.

No model names are listed anywhere. A request carries only what the caller asked for — a length limit
when one is set, a temperature only when one is configured (otherwise the model's own default). If a
server still refuses a parameter, its 400 names it; the call is retried with the fix, and the fix is
remembered for that model for the life of the process. A Chat Completions server that refuses tools while
the model reasons ("use /v1/responses") moves that model's tool calls to the Responses API.
"""

import json
import logging

from ..base import CompletionOptions, CompletionResult, ImagePart, Message, ToolCall, ToolDefinition

logger = logging.getLogger(__name__)

FIX_COMPLETION_TOKENS = "max_completion_tokens"  # Chat Completions: the model wants max_completion_tokens
FIX_NO_SAMPLING = "no_sampling"  # the model accepts only its default temperature / top_p
FIX_RESPONSES_FOR_TOOLS = "responses_for_tools"  # Chat Completions: function tools only work on /v1/responses
MAX_FIXES = 2  # a length fix and a sampling fix

_learned: dict[str, set[str]] = {}


class NeedsResponsesAPI(Exception):
    """Chat Completions refused this model's tool call; send it through the Responses API."""


def needs_responses(model: str) -> bool:
    return FIX_RESPONSES_FOR_TOOLS in _learned.get(model, set())


def _sampling(model: str, opts: CompletionOptions) -> dict:
    """Temperature / top_p — only the ones configured, and none for a model that refused them."""
    if FIX_NO_SAMPLING in _learned.get(model, set()):
        return {}
    return {k: v for k, v in (("temperature", opts.temperature), ("top_p", opts.top_p)) if v is not None}


def chat_kwargs(model: str, opts: CompletionOptions) -> dict:
    """Chat Completions length and sampling parameters; an unset limit is left out."""
    kwargs = _sampling(model, opts)
    if opts.max_tokens is not None:
        kwargs["max_completion_tokens" if FIX_COMPLETION_TOKENS in _learned.get(model, set()) else "max_tokens"] = opts.max_tokens
    return kwargs


def response_kwargs(model: str, opts: CompletionOptions) -> dict:
    """Responses API length and sampling parameters; an unset limit is left out."""
    kwargs = _sampling(model, opts)
    if opts.max_tokens is not None:
        kwargs["max_output_tokens"] = opts.max_tokens
    return kwargs


def fix_for(error: Exception) -> str | None:
    """The parameter fix a 400 asks for, or None when the error is about something else."""
    if getattr(error, "status_code", None) != 400:
        return None
    body = getattr(error, "body", None)
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        body = body["error"]
    if not isinstance(body, dict):
        return None
    param = body.get("param")
    message = str(body.get("message") or "")
    if param == "max_tokens" and "max_completion_tokens" in message:
        return FIX_COMPLETION_TOKENS
    if param in ("temperature", "top_p"):
        return FIX_NO_SAMPLING
    if param == "reasoning_effort" and "/v1/responses" in message:
        return FIX_RESPONSES_FOR_TOOLS
    return None


def _with_fixes(call, model: str, build_kwargs, opts: CompletionOptions, request: dict):
    """Run `call`, applying (and remembering) each parameter fix a 400 asks for."""
    for _ in range(MAX_FIXES):
        try:
            return call(model=model, **request, **build_kwargs(model, opts))
        except Exception as e:
            fix = fix_for(e)
            if fix is None or fix in _learned.get(model, set()):
                raise
            _learned.setdefault(model, set()).add(fix)
            if fix == FIX_RESPONSES_FOR_TOOLS:
                raise NeedsResponsesAPI(str(e)) from e
            logger.info("model %s: retrying with %s after: %s", model, fix, e)
    return call(model=model, **request, **build_kwargs(model, opts))


def create_chat_completion(client, model: str, opts: CompletionOptions, **request):
    return _with_fixes(client.chat.completions.create, model, chat_kwargs, opts, request)


def create_response(client, model: str, opts: CompletionOptions, **request):
    # store=False: stateless like Chat Completions — the transcript is resent each turn, nothing kept at OpenAI.
    return _with_fixes(client.responses.create, model, response_kwargs, opts, {"store": False, **request})


# ── Responses API shapes ─────────────────────────────────────────────────────


def _input_content(content):
    """Agnostic content in the Responses input shape (str, or input_text / input_image parts)."""
    if isinstance(content, str):
        return content
    return [
        {"type": "input_image", "image_url": f"data:{p.mime_type};base64,{p.data}"}
        if isinstance(p, ImagePart)
        else {"type": "input_text", "text": str(p)}
        for p in content
    ]


def response_input(messages: list[Message]) -> list[dict]:
    """The transcript as Responses input items: tool calls and their results are items of their own."""
    items: list[dict] = []
    for m in messages:
        if m.role == "tool":
            items.append(
                {"type": "function_call_output", "call_id": m.tool_call_id, "output": m.content if isinstance(m.content, str) else str(m.content)}
            )
        elif m.role == "assistant" and m.tool_calls:
            if isinstance(m.content, str) and m.content:
                items.append({"role": "assistant", "content": m.content})
            items.extend({"type": "function_call", "call_id": tc.id, "name": tc.name, "arguments": json.dumps(tc.arguments)} for tc in m.tool_calls)
        else:
            items.append({"role": m.role, "content": _input_content(m.content)})
    return items


def response_tools(tools: list[ToolDefinition]) -> list[dict]:
    return [{"type": "function", "name": t.name, "description": t.description, "parameters": t.input_schema, "strict": False} for t in tools]


def json_schema_format(output_schema: dict) -> dict:
    """`text=` for a structured (JSON-schema) answer."""
    return {"format": {"type": "json_schema", "name": "output", "schema": output_schema, "strict": False}}


def response_result(resp) -> CompletionResult:
    """A Responses API answer as Marvin's CompletionResult (text, tool calls, usage, why it stopped)."""
    tool_calls: list[ToolCall] = []
    for item in resp.output or []:
        if getattr(item, "type", None) != "function_call":
            continue
        try:
            args = json.loads(item.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        tool_calls.append(ToolCall(id=item.call_id, name=item.name, arguments=args))
    incomplete = getattr(getattr(resp, "incomplete_details", None), "reason", None)
    return CompletionResult(
        content=resp.output_text or "",
        prompt_tokens=resp.usage.input_tokens,
        completion_tokens=resp.usage.output_tokens,
        total_tokens=resp.usage.total_tokens,
        model=resp.model,
        raw=resp.model_dump(),
        tool_calls=tool_calls,
        stop_reason="tool_calls" if tool_calls else (incomplete or "stop"),
    )
