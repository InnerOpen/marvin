"""OpenAI provider implementation."""

from ..base import (
    AIProvider,
    CompletionOptions,
    CompletionResult,
    ImagePart,
    Message,
    ToolCall,
    ToolDefinition,
)

# Reasoning models reject `max_tokens` outright — even null — in favour of `max_completion_tokens`,
# and accept only the default temperature.
_REASONING_MODEL_PREFIXES = ("o1", "o3", "o4", "gpt-5")


def _sampling_kwargs(model: str, opts: CompletionOptions, *, include_top_p: bool = False) -> dict:
    """The length and sampling parameters this model accepts; unset limits are left out."""
    is_reasoning = model.startswith(_REASONING_MODEL_PREFIXES)
    kwargs: dict = {}
    if opts.max_tokens is not None:
        kwargs["max_completion_tokens" if is_reasoning else "max_tokens"] = opts.max_tokens
    if not is_reasoning:
        kwargs["temperature"] = opts.temperature
        if include_top_p:
            kwargs["top_p"] = opts.top_p
    return kwargs


class OpenAIProvider(AIProvider):
    provider_type = "openai"
    display_name = "OpenAI"
    supports_vision = True
    supports_structured_output = True
    supports_embeddings = True
    supports_tool_calls = True

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        self._api_key = api_key
        self._base_url = base_url

    def _client(self):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("OpenAI SDK not installed. Run: uv sync --extra openai (or pip install 'marvin[openai]')") from None
        return OpenAI(api_key=self._api_key, base_url=self._base_url)

    def _render_content(self, content):
        """Translate agnostic content into OpenAI's chat format (str or multimodal parts)."""
        if isinstance(content, str):
            return content
        parts = []
        for p in content:
            if isinstance(p, ImagePart):
                parts.append({"type": "image_url", "image_url": {"url": f"data:{p.mime_type};base64,{p.data}"}})
            else:
                parts.append({"type": "text", "text": str(p)})
        return parts

    def _to_api_messages(self, messages: list[Message]):
        return [{"role": m.role, "content": self._render_content(m.content)} for m in messages]

    def _to_api_tool_messages(self, messages: list[Message]):
        """Render messages for the tool-calling path: assistant `tool_calls` and role="tool"
        result messages take OpenAI's dedicated shapes."""
        import json

        out: list[dict] = []
        for m in messages:
            if m.role == "tool":
                content = m.content if isinstance(m.content, str) else str(m.content)
                out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": content})
            elif m.role == "assistant" and m.tool_calls:
                out.append(
                    {
                        "role": "assistant",
                        "content": m.content if (isinstance(m.content, str) and m.content) else None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                            }
                            for tc in m.tool_calls
                        ],
                    }
                )
            else:
                out.append({"role": m.role, "content": self._render_content(m.content)})
        return out

    def complete(self, messages: list[Message], model: str, options: CompletionOptions | None = None) -> CompletionResult:
        opts = options or CompletionOptions()
        client = self._client()
        resp = client.chat.completions.create(
            model=model,
            messages=self._to_api_messages(messages),
            **_sampling_kwargs(model, opts, include_top_p=True),
        )
        choice = resp.choices[0]
        return CompletionResult(
            content=choice.message.content or "",
            prompt_tokens=resp.usage.prompt_tokens,
            completion_tokens=resp.usage.completion_tokens,
            total_tokens=resp.usage.total_tokens,
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
        import json

        opts = options or CompletionOptions()
        client = self._client()
        api_tools = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}} for t in tools]
        choice_map = {"auto": "auto", "required": "required", "none": "none"}
        resp = client.chat.completions.create(
            model=model,
            messages=self._to_api_tool_messages(messages),
            tools=api_tools,
            tool_choice=choice_map.get(tool_choice, "auto"),
            **_sampling_kwargs(model, opts),
        )
        choice = resp.choices[0]
        tool_calls: list[ToolCall] = []
        for tc in choice.message.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        return CompletionResult(
            content=choice.message.content or "",
            prompt_tokens=resp.usage.prompt_tokens,
            completion_tokens=resp.usage.completion_tokens,
            total_tokens=resp.usage.total_tokens,
            model=resp.model,
            raw=resp.model_dump(),
            tool_calls=tool_calls,
            stop_reason=choice.finish_reason,
        )

    def complete_structured(self, messages: list[Message], model: str, output_schema: dict, options: CompletionOptions | None = None) -> dict:
        import json

        opts = options or CompletionOptions()
        client = self._client()
        resp = client.chat.completions.create(
            model=model,
            messages=self._to_api_messages(messages),
            response_format={"type": "json_schema", "json_schema": {"name": "output", "schema": output_schema, "strict": False}},
            **_sampling_kwargs(model, opts),
        )
        return json.loads(resp.choices[0].message.content or "{}")

    def list_models(self) -> list[str]:
        client = self._client()
        models = client.models.list()
        return sorted(m.id for m in models.data if "gpt" in m.id or "o1" in m.id or "o3" in m.id)

    def execute_operation(self, messages, model, output_schema, options=None):
        import json

        opts = options or CompletionOptions()
        client = self._client()
        resp = client.chat.completions.create(
            model=model,
            messages=self._to_api_messages(messages),
            response_format={"type": "json_schema", "json_schema": {"name": "output", "schema": output_schema, "strict": False}},
            **_sampling_kwargs(model, opts),
        )
        parsed = json.loads(resp.choices[0].message.content or "{}")
        result = CompletionResult(
            content=resp.choices[0].message.content or "",
            prompt_tokens=resp.usage.prompt_tokens,
            completion_tokens=resp.usage.completion_tokens,
            total_tokens=resp.usage.total_tokens,
            model=resp.model,
        )
        return parsed, result

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        resp = self._client().embeddings.create(model=model, input=texts)
        return [d.embedding for d in resp.data]

    def test_connection(self) -> tuple[bool, str]:
        try:
            models = self.list_models()
            return True, f"Connected — {len(models)} models available"
        except Exception as e:
            return False, str(e)
