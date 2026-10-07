"""Azure OpenAI provider implementation."""

from collections.abc import Mapping
from typing import Any

from ..base import (
    AIProvider,
    CompletionOptions,
    CompletionResult,
    Credential,
    ImagePart,
    Message,
    ToolCall,
    ToolDefinition,
)
from .openai_api import NeedsResponsesAPI, create_chat_completion, create_response, needs_responses, response_input, response_result, response_tools


class AzureOpenAIProvider(AIProvider):
    provider_type = "azure"
    display_name = "Azure OpenAI"
    supports_vision = True
    supports_structured_output = True
    supports_embeddings = True
    supports_tool_calls = True
    credentials = (
        Credential("api_key", "API key", secret=True, required=True),
        Credential("base_url", "Endpoint", required=True, help="https://<resource>.openai.azure.com"),
        Credential("api_version", "API version", default="2024-02-01"),
    )
    default_embedding_model = "text-embedding-3-small"

    def __init__(self, api_key: str, base_url: str, api_version: str = "2024-02-01") -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._api_version = api_version

    @classmethod
    def from_credentials(cls, values: Mapping[str, Any]) -> "AzureOpenAIProvider":
        return cls(api_key=values.get("api_key") or "", base_url=values.get("base_url") or "", api_version=values.get("api_version") or "2024-02-01")

    def _client(self):
        try:
            from openai import AzureOpenAI
        except ImportError:
            raise ImportError("OpenAI SDK not installed. Run: uv sync --extra openai (or pip install 'marvin[openai]')") from None
        return AzureOpenAI(api_key=self._api_key, azure_endpoint=self._base_url, api_version=self._api_version)

    def _render_content(self, content):
        """Translate agnostic content into Azure OpenAI's chat format (str or multimodal parts)."""
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
        """Render messages for the tool-calling path (identical shape to the OpenAI provider)."""
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
        choice = {"auto": "auto", "required": "required", "none": "none"}.get(tool_choice, "auto")
        api_tools = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}} for t in tools]
        try:
            if needs_responses(model):
                raise NeedsResponsesAPI(model)
            resp = create_chat_completion(client, model, opts, messages=self._to_api_tool_messages(messages), tools=api_tools, tool_choice=choice)
        except NeedsResponsesAPI:
            # A deployment that refuses tools while reasoning; needs an api_version that has the Responses API.
            return response_result(
                create_response(client, model, opts, input=response_input(messages), tools=response_tools(tools), tool_choice=choice)
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

    def complete(self, messages: list[Message], model: str, options: CompletionOptions | None = None) -> CompletionResult:
        opts = options or CompletionOptions()
        resp = create_chat_completion(self._client(), model, opts, messages=self._to_api_messages(messages))
        choice = resp.choices[0]
        return CompletionResult(
            content=choice.message.content or "",
            prompt_tokens=resp.usage.prompt_tokens,
            completion_tokens=resp.usage.completion_tokens,
            total_tokens=resp.usage.total_tokens,
            model=resp.model,
            raw=resp.model_dump(),
        )

    def complete_structured(self, messages: list[Message], model: str, output_schema: dict, options: CompletionOptions | None = None) -> dict:
        import json

        opts = options or CompletionOptions()
        resp = create_chat_completion(
            self._client(),
            model,
            opts,
            messages=self._to_api_messages(messages),
            response_format={"type": "json_schema", "json_schema": {"name": "output", "schema": output_schema}},
        )
        return json.loads(resp.choices[0].message.content or "{}")

    def list_models(self) -> list[str]:
        try:
            models = self._client().models.list()
            return [m.id for m in models.data]
        except Exception:
            return []

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        resp = self._client().embeddings.create(model=model, input=texts)
        return [d.embedding for d in resp.data]

    def test_connection(self) -> tuple[bool, str]:
        try:
            self.list_models()
            return True, "Connected to Azure OpenAI"
        except Exception as e:
            return False, str(e)
