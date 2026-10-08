"""Unit tests for provider tool-calling (complete_with_tools) — message translation + parsing.

Pure unit tests: the provider SDK clients are mocked, so no network/keys are needed. Covers the
agnostic → provider message translation (assistant tool_calls, role="tool" results) and the
parsing of provider responses back into CompletionResult.tool_calls.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from marvin.services.ai.base import (
    Message,
    ToolCall,
    ToolDefinition,
)
from marvin.services.ai.providers.anthropic import AnthropicProvider
from marvin.services.ai.providers.ollama import OllamaProvider

TOOLS = [ToolDefinition(name="get_entry", description="Fetch an entry", input_schema={"type": "object"})]


def test_tool_calling_capability_flags():
    assert AnthropicProvider.supports_tool_calls is True
    assert OllamaProvider.supports_tool_calls is True
    # Google intentionally not implemented yet.
    from marvin.services.ai.providers.google import GoogleProvider

    assert GoogleProvider.supports_tool_calls is False


# ── Anthropic message translation ───────────────────────────────────────────


def test_anthropic_splits_tool_roundtrip():
    provider = AnthropicProvider(api_key="x")
    messages = [
        Message(role="system", content="You are Marvin."),
        Message(role="user", content="fetch about"),
        Message(
            role="assistant",
            content="Let me look.",
            tool_calls=[ToolCall(id="tu_1", name="get_entry", arguments={"slug": "about"})],
        ),
        Message(role="tool", content='{"title":"About"}', tool_call_id="tu_1"),
    ]
    system, chat = provider._split_tool_messages(messages)

    assert system == "You are Marvin."
    # assistant turn carries a text block + a tool_use block
    assistant = chat[1]
    assert assistant["role"] == "assistant"
    types = [b["type"] for b in assistant["content"]]
    assert types == ["text", "tool_use"]
    assert assistant["content"][1] == {"type": "tool_use", "id": "tu_1", "name": "get_entry", "input": {"slug": "about"}}
    # tool result becomes a user message with a tool_result block
    result_turn = chat[2]
    assert result_turn["role"] == "user"
    assert result_turn["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "tu_1",
        "content": '{"title":"About"}',
    }


def test_anthropic_merges_consecutive_tool_results():
    provider = AnthropicProvider(api_key="x")
    messages = [
        Message(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(id="a", name="t", arguments={}),
                ToolCall(id="b", name="t", arguments={}),
            ],
        ),
        Message(role="tool", content="ra", tool_call_id="a"),
        Message(role="tool", content="rb", tool_call_id="b"),
    ]
    _system, chat = provider._split_tool_messages(messages)
    # both results collapse into a single user turn with two tool_result blocks
    result_turn = chat[1]
    assert result_turn["role"] == "user"
    assert [b["tool_use_id"] for b in result_turn["content"]] == ["a", "b"]


def test_anthropic_complete_with_tools_parses_tool_use():
    provider = AnthropicProvider(api_key="x")
    resp = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="Looking… "),
            SimpleNamespace(type="tool_use", id="tu_9", name="get_entry", input={"slug": "home"}),
        ],
        usage=SimpleNamespace(input_tokens=12, output_tokens=6),
        model="claude-sonnet-5",
        stop_reason="tool_use",
        model_dump=lambda: {},
    )
    fake_client = MagicMock()
    fake_client.messages.create.return_value = resp
    provider._client = MagicMock(return_value=fake_client)

    result = provider.complete_with_tools([Message(role="user", content="hi")], "claude-sonnet-5", TOOLS)

    assert result.content == "Looking… "
    assert result.stop_reason == "tool_use"
    assert result.tool_calls == [ToolCall(id="tu_9", name="get_entry", arguments={"slug": "home"})]
    sent = fake_client.messages.create.call_args.kwargs
    assert sent["tools"][0]["name"] == "get_entry"
    assert sent["tool_choice"] == {"type": "auto"}


# ── Ollama (native /api/chat) ───────────────────────────────────────────────


def test_ollama_translates_tool_roundtrip():
    provider = OllamaProvider()
    messages = [
        Message(role="assistant", content="", tool_calls=[ToolCall(id="call_0", name="get_entry", arguments={"slug": "about"})]),
        Message(role="tool", content='{"title":"About"}', tool_call_id="call_0"),
    ]
    api = provider._to_api_tool_messages(messages)
    # Ollama assistant tool_calls: function.arguments is an OBJECT (not a JSON string), no id
    assert api[0]["tool_calls"][0] == {"function": {"name": "get_entry", "arguments": {"slug": "about"}}}
    # tool result is a plain role="tool" message, no tool_call_id
    assert api[1] == {"role": "tool", "content": '{"title":"About"}'}


def test_ollama_complete_with_tools_synthesizes_ids():
    provider = OllamaProvider()
    data = {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "get_entry", "arguments": {"slug": "home"}}}],
        },
        "prompt_eval_count": 20,
        "eval_count": 7,
    }
    import httpx

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = data
    fake_resp.raise_for_status.return_value = None
    provider_post = MagicMock(return_value=fake_resp)
    orig = httpx.post
    httpx.post = provider_post
    try:
        result = provider.complete_with_tools([Message(role="user", content="hi")], "llama3.1", TOOLS)
    finally:
        httpx.post = orig

    assert result.tool_calls == [ToolCall(id="call_0", name="get_entry", arguments={"slug": "home"})]
    assert result.stop_reason == "tool_calls"
    assert result.total_tokens == 27
    # tools were forwarded in the payload
    sent_payload = provider_post.call_args.kwargs["json"]
    assert sent_payload["tools"][0]["function"]["name"] == "get_entry"


def test_tool_choice_required_maps_for_anthropic():
    """OpenAI's mapping is tested in the marvin-ai-openai plugin."""
    anthropic = AnthropicProvider(api_key="x")

    ant_resp = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="x")],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        model="claude-sonnet-5",
        stop_reason="end_turn",
        model_dump=lambda: {},
    )
    ant_client = MagicMock()
    ant_client.messages.create.return_value = ant_resp
    anthropic._client = MagicMock(return_value=ant_client)
    anthropic.complete_with_tools([Message(role="user", content="hi")], "claude-sonnet-5", TOOLS, tool_choice="required")
    assert ant_client.messages.create.call_args.kwargs["tool_choice"] == {"type": "any"}
