"""Abstract base class and shared data types for AI providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ImagePart:
    """
    Provider-agnostic inline image for multimodal messages.

    `data` is base64-encoded image bytes; `mime_type` is e.g. "image/png".
    A multimodal Message carries content = list mixing str (text) and ImagePart;
    each provider translates ImagePart into its own SDK format.
    """

    data: str
    mime_type: str


@dataclass
class ToolDefinition:
    """A tool the model may call, in provider-agnostic form.

    `input_schema` is a JSON schema describing the tool's arguments. Each provider translates
    this into its own tool/function format in complete_with_tools().
    """

    name: str
    description: str
    input_schema: dict


@dataclass
class ToolCall:
    """A model's request to call a tool, normalized across providers.

    `id` correlates the call with its result (echoed back on the role="tool" Message);
    `arguments` is the decoded argument object.
    """

    id: str
    name: str
    arguments: dict


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str | list  # str, or list mixing str (text) and ImagePart (image) for multimodal
    # Tool-calling round-trip (both optional; only used on the complete_with_tools path):
    tool_calls: list[ToolCall] | None = None  # role="assistant": tool calls the model requested
    tool_call_id: str | None = None  # role="tool": the ToolCall.id this message answers


def serialize_messages(messages: list[Message]) -> list[dict]:
    """Messages → JSON-safe dicts, so a paused run's transcript can be parked in the database.

    str content stays a str; list content becomes `[{"type": "text", "text"} | {"type": "image",
    "data", "mime_type"}]`; tool calls and tool_call_id ride along. `deserialize_messages` inverts it.
    """
    out: list[dict] = []
    for m in messages:
        if isinstance(m.content, str):
            content: str | list = m.content
        else:
            content = [
                {"type": "image", "data": part.data, "mime_type": part.mime_type} if isinstance(part, ImagePart) else {"type": "text", "text": str(part)}
                for part in m.content
            ]
        d: dict = {"role": m.role, "content": content}
        if m.tool_calls:
            d["tool_calls"] = [{"id": c.id, "name": c.name, "arguments": dict(c.arguments or {})} for c in m.tool_calls]
        if m.tool_call_id:
            d["tool_call_id"] = m.tool_call_id
        out.append(d)
    return out


def deserialize_messages(data) -> list[Message]:
    out: list[Message] = []
    for d in data or []:
        if not isinstance(d, dict):
            continue
        raw = d.get("content", "")
        if isinstance(raw, list):
            content: str | list = [
                ImagePart(data=str(part.get("data") or ""), mime_type=str(part.get("mime_type") or "image/png"))
                if isinstance(part, dict) and part.get("type") == "image"
                else str(part.get("text", "") if isinstance(part, dict) else part)
                for part in raw
            ]
        else:
            content = "" if raw is None else str(raw)
        calls = d.get("tool_calls") or None
        out.append(
            Message(
                role=str(d.get("role") or "user"),
                content=content,
                tool_calls=[ToolCall(id=str(c.get("id")), name=str(c.get("name")), arguments=dict(c.get("arguments") or {})) for c in calls]
                if calls
                else None,
                tool_call_id=d.get("tool_call_id") or None,
            )
        )
    return out


@dataclass
class CompletionOptions:
    max_tokens: int | None = None
    temperature: float = 0.7
    top_p: float = 1.0
    extra: dict = field(default_factory=dict)


@dataclass
class CompletionResult:
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: str
    raw: dict = field(default_factory=dict)
    # Populated by complete_with_tools when the model asks to call tools instead of answering:
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str | None = None


class AIProvider(ABC):
    """
    Abstract base for all AI provider implementations.

    Follows the same pattern as SecretBackend and BaseStorageProvider —
    selected and instantiated by get_ai_provider() in factory.py.
    """

    provider_type: str
    display_name: str
    supports_vision: bool = False
    supports_structured_output: bool = False
    supports_embeddings: bool = False
    supports_tool_calls: bool = False
    # Can this provider download models on demand (e.g. Ollama's /api/pull)? Hosted APIs can't.
    supports_model_pull: bool = False

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        """Return one embedding vector per input text. Providers with embeddings override."""
        raise NotImplementedError(f"{self.provider_type} does not support embeddings")

    def pull_model(self, name: str, on_progress=None) -> None:
        """Download a model into the provider, reporting progress.

        `on_progress` is called with a dict ``{status, completed, total}`` per update. Only local
        providers that host their own weights (Ollama) override this.
        """
        raise NotImplementedError(f"{self.provider_type} does not support pulling models")

    def complete_with_tools(
        self,
        messages: list[Message],
        model: str,
        tools: list[ToolDefinition],
        options: CompletionOptions | None = None,
        tool_choice: str = "auto",
    ) -> CompletionResult:
        """Run one tool-calling turn.

        The model either answers (result.content, result.tool_calls empty) or requests tool
        calls (result.tool_calls populated). The caller — the agent loop — runs each requested
        tool, appends an assistant Message carrying result.tool_calls, then one role="tool"
        Message per result (echoing ToolCall.id via tool_call_id), and calls again until no tool
        calls remain. `tool_choice` is "auto" (model decides), "required" (must call a tool), or
        "none". Providers with function/tool calling override this.
        """
        raise NotImplementedError(f"{self.provider_type} does not support tool calling")

    @abstractmethod
    def complete(
        self,
        messages: list[Message],
        model: str,
        options: CompletionOptions | None = None,
    ) -> CompletionResult:
        """Send a chat completion request and return the result."""
        ...

    @abstractmethod
    def complete_structured(
        self,
        messages: list[Message],
        model: str,
        output_schema: dict,
        options: CompletionOptions | None = None,
    ) -> dict:
        """Request structured (JSON) output conforming to output_schema."""
        ...

    @abstractmethod
    def list_models(self) -> list[str]:
        """Return model IDs available from this provider."""
        ...

    @abstractmethod
    def test_connection(self) -> tuple[bool, str]:
        """
        Validate the connection and credentials.
        Returns (success, message).
        """
        ...

    def execute_operation(
        self,
        messages: list[Message],
        model: str,
        output_schema: dict,
        options: CompletionOptions | None = None,
    ) -> tuple[dict, CompletionResult]:
        """
        Execute a structured-output operation and return (parsed_dict, result_with_usage).

        Default implementation: call complete() then parse JSON from content.
        Providers with native structured output (OpenAI, Anthropic) override this
        to use their native mechanisms while still returning token usage.
        """
        import json
        import re

        result = self.complete(messages, model, options)
        # Strip markdown code fences if the model wrapped JSON in ```json ... ```
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", result.content.strip())
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = {"raw": result.content}
        return parsed, result
