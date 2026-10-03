"""Anthropic provider implementation."""

from ..base import (
    AIProvider,
    CompletionOptions,
    CompletionResult,
    ImagePart,
    Message,
    ToolCall,
    ToolDefinition,
)


def _sampling(opts: CompletionOptions) -> dict:
    """A temperature only when one is configured; otherwise the model's default."""
    return {"temperature": opts.temperature} if opts.temperature is not None else {}


class AnthropicProvider(AIProvider):
    provider_type = "anthropic"
    display_name = "Anthropic"
    supports_vision = True
    supports_structured_output = True
    supports_tool_calls = True

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def _client(self):
        try:
            import anthropic
        except ImportError:
            raise ImportError("Anthropic SDK not installed. Run: uv sync --extra anthropic (or pip install 'marvin[anthropic]')") from None
        return anthropic.Anthropic(api_key=self._api_key)

    def _render_content(self, content):
        """Translate agnostic content into Anthropic's content format (str or content blocks)."""
        if isinstance(content, str):
            return content
        blocks = []
        for p in content:
            if isinstance(p, ImagePart):
                blocks.append({"type": "image", "source": {"type": "base64", "media_type": p.mime_type, "data": p.data}})
            else:
                blocks.append({"type": "text", "text": str(p)})
        return blocks

    def _split_messages(self, messages: list[Message]):
        system = " ".join(m.content for m in messages if m.role == "system" and isinstance(m.content, str))
        chat = [{"role": m.role, "content": self._render_content(m.content)} for m in messages if m.role != "system"]
        return system or None, chat

    def _split_tool_messages(self, messages: list[Message]):
        """Like _split_messages, but renders the tool-calling round-trip into Anthropic's blocks.

        assistant tool calls become `tool_use` blocks; role="tool" results become `tool_result`
        blocks in a user message (consecutive results are merged into one user turn, as Anthropic
        expects the results immediately following the assistant's tool_use).
        """
        system = " ".join(m.content for m in messages if m.role == "system" and isinstance(m.content, str))
        chat: list[dict] = []
        pending_results: list[dict] = []

        def flush_results() -> None:
            if pending_results:
                chat.append({"role": "user", "content": list(pending_results)})
                pending_results.clear()

        for m in messages:
            if m.role == "system":
                continue
            if m.role == "tool":
                content = m.content if isinstance(m.content, str) else self._render_content(m.content)
                pending_results.append({"type": "tool_result", "tool_use_id": m.tool_call_id, "content": content})
                continue
            flush_results()
            if m.role == "assistant" and m.tool_calls:
                blocks: list[dict] = []
                if isinstance(m.content, str) and m.content.strip():
                    blocks.append({"type": "text", "text": m.content})
                elif isinstance(m.content, list):
                    blocks.extend(self._render_content(m.content))
                for tc in m.tool_calls:
                    blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
                chat.append({"role": "assistant", "content": blocks})
            else:
                chat.append({"role": m.role, "content": self._render_content(m.content)})
        flush_results()
        return system or None, chat

    def complete(self, messages: list[Message], model: str, options: CompletionOptions | None = None) -> CompletionResult:
        opts = options or CompletionOptions()
        system, chat = self._split_messages(messages)
        client = self._client()
        kwargs = {"model": model, "messages": chat, "max_tokens": opts.max_tokens or 4096, **_sampling(opts)}
        if system:
            kwargs["system"] = system
        resp = client.messages.create(**kwargs)
        content = resp.content[0].text if resp.content else ""
        return CompletionResult(
            content=content,
            prompt_tokens=resp.usage.input_tokens,
            completion_tokens=resp.usage.output_tokens,
            total_tokens=resp.usage.input_tokens + resp.usage.output_tokens,
            model=resp.model,
            raw=resp.model_dump(),
        )

    def complete_with_tools(
        self,
        messages: list[Message],
        model: str,
        tools: list[ToolDefinition],
        options: CompletionOptions | None = None,
        tool_choice: str = "auto",
    ) -> CompletionResult:
        opts = options or CompletionOptions()
        system, chat = self._split_tool_messages(messages)
        client = self._client()
        api_tools = [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools]
        choice_map = {"auto": {"type": "auto"}, "required": {"type": "any"}, "none": {"type": "none"}}
        kwargs = {
            "model": model,
            "messages": chat,
            "max_tokens": opts.max_tokens or 4096,
            **_sampling(opts),
            "tools": api_tools,
            "tool_choice": choice_map.get(tool_choice, {"type": "auto"}),
        }
        if system:
            kwargs["system"] = system
        resp = client.messages.create(**kwargs)

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(block.text)
            elif btype == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input or {})))
        return CompletionResult(
            content="".join(text_parts),
            prompt_tokens=resp.usage.input_tokens,
            completion_tokens=resp.usage.output_tokens,
            total_tokens=resp.usage.input_tokens + resp.usage.output_tokens,
            model=resp.model,
            raw=resp.model_dump(),
            tool_calls=tool_calls,
            stop_reason=resp.stop_reason,
        )

    def complete_structured(self, messages: list[Message], model: str, output_schema: dict, options: CompletionOptions | None = None) -> dict:
        import json

        opts = options or CompletionOptions()
        system, chat = self._split_messages(messages)
        client = self._client()
        tool = {"name": "structured_output", "description": "Return structured output", "input_schema": output_schema}
        kwargs = {
            "model": model,
            "messages": chat,
            "max_tokens": opts.max_tokens or 4096,
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": "structured_output"},
        }
        if system:
            kwargs["system"] = system
        resp = client.messages.create(**kwargs)
        for block in resp.content:
            if hasattr(block, "input"):
                return block.input
        return json.loads(resp.content[0].text if resp.content else "{}")

    def execute_operation(self, messages, model, output_schema, options=None):
        opts = options or CompletionOptions()
        system, chat = self._split_messages(messages)
        client = self._client()
        tool = {"name": "structured_output", "description": "Return structured output", "input_schema": output_schema}
        kwargs = {
            "model": model,
            "messages": chat,
            "max_tokens": opts.max_tokens or 4096,
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": "structured_output"},
        }
        if system:
            kwargs["system"] = system
        resp = client.messages.create(**kwargs)
        parsed = {}
        for block in resp.content:
            if hasattr(block, "input"):
                parsed = block.input
                break
        result = CompletionResult(
            content=str(parsed),
            prompt_tokens=resp.usage.input_tokens,
            completion_tokens=resp.usage.output_tokens,
            total_tokens=resp.usage.input_tokens + resp.usage.output_tokens,
            model=resp.model,
        )
        return parsed, result

    def list_models(self) -> list[str]:
        return ["claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5-20251001"]

    def test_connection(self) -> tuple[bool, str]:
        try:
            client = self._client()
            client.messages.create(model="claude-haiku-4-5-20251001", messages=[{"role": "user", "content": "hi"}], max_tokens=1)
            return True, "Connected"
        except Exception as e:
            return False, str(e)
