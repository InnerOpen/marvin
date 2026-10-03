"""OpenAI-style APIs without per-model code.

Regressions (2026-10-03, gpt-6.1-sol): Chat Completions refused `max_tokens` ("use max_completion_tokens"),
then refused function tools while the model reasoned ("use /v1/responses"). Both were model-specific rules
of the older endpoint. Now the official API goes through the Responses API, nothing is sent that the caller
didn't configure, and a server that still refuses a parameter is corrected from its own 400.
"""

from types import SimpleNamespace

import pytest

from marvin.services.ai.base import CompletionOptions, ImagePart, Message, ToolCall, ToolDefinition
from marvin.services.ai.providers import openai_api
from marvin.services.ai.providers.openai import OpenAIProvider
from marvin.services.ai.providers.openai_api import NeedsResponsesAPI, chat_kwargs, create_chat_completion, needs_responses, response_kwargs

LIMIT = CompletionOptions(max_tokens=500)


@pytest.fixture(autouse=True)
def _forget():
    openai_api._learned.clear()
    yield
    openai_api._learned.clear()


class _BadRequest(Exception):
    status_code = 400

    def __init__(self, param, message):
        super().__init__(message)
        self.body = {"message": message, "type": "invalid_request_error", "param": param, "code": "unsupported_parameter"}


def _response(output=(), text="", model="m"):
    return SimpleNamespace(
        output=list(output),
        output_text=text,
        usage=SimpleNamespace(input_tokens=100, output_tokens=20, total_tokens=120),
        model=model,
        incomplete_details=None,
        model_dump=lambda: {},
    )


class _Client:
    """Records requests; `refuse` maps a parameter to the 400 message a server sends when it's present."""

    def __init__(self, refuse: dict[str, str] | None = None, reply=None):
        self.refuse = refuse or {}
        self.reply = reply or _response(text="hi")
        self.chat_sent: list[dict] = []
        self.responses_sent: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.responses = SimpleNamespace(create=self._respond)

    def _refuse(self, kwargs):
        for param, message in self.refuse.items():
            if param in kwargs:
                raise _BadRequest("reasoning_effort" if param == "tools" else param, message)

    def _chat(self, **kwargs):
        self.chat_sent.append(kwargs)
        self._refuse(kwargs)
        msg = SimpleNamespace(content="hi", tool_calls=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=msg, finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model=kwargs["model"],
            model_dump=lambda: {},
        )

    def _respond(self, **kwargs):
        self.responses_sent.append(kwargs)
        self._refuse(kwargs)
        return self.reply


def _provider(client, base_url=None):
    provider = OpenAIProvider(api_key="k", base_url=base_url)
    provider._client = lambda: client
    return provider


TRANSCRIPT = [
    Message(role="system", content="You are Marvin."),
    Message(role="user", content=["what's this?", ImagePart(data="AAA", mime_type="image/png")]),
    Message(role="assistant", content="", tool_calls=[ToolCall(id="call_0", name="list_tags", arguments={})]),
    Message(role="tool", content='{"tags": []}', tool_call_id="call_0"),
]
TOOL = ToolDefinition(name="search_content", description="Search", input_schema={"type": "object", "properties": {}})


# --- the official API: Responses, for every model ------------------------------------------------------


def test_any_model_on_the_official_api_gets_the_same_request():
    client = _Client()

    _provider(client).complete([Message(role="user", content="hi")], "some-future-model", LIMIT)

    assert client.chat_sent == []
    assert client.responses_sent == [
        {"model": "some-future-model", "input": [{"role": "user", "content": "hi"}], "store": False, "max_output_tokens": 500}
    ]


def test_tool_calls_go_through_responses_with_the_transcript_as_items():
    call = SimpleNamespace(type="function_call", call_id="call_1", name="search_content", arguments='{"query": "brain"}')
    client = _Client(reply=_response(output=[SimpleNamespace(type="reasoning"), call]))

    result = _provider(client).complete_with_tools(TRANSCRIPT, "gpt-6.1-sol", [TOOL], LIMIT)

    assert [(c.id, c.name, c.arguments) for c in result.tool_calls] == [("call_1", "search_content", {"query": "brain"})]
    assert (result.prompt_tokens, result.completion_tokens, result.stop_reason) == (100, 20, "tool_calls")
    sent = client.responses_sent[0]
    assert sent["tools"] == [
        {"type": "function", "name": "search_content", "description": "Search", "parameters": TOOL.input_schema, "strict": False}
    ]
    assert sent["input"][1:] == [
        {
            "role": "user",
            "content": [{"type": "input_text", "text": "what's this?"}, {"type": "input_image", "image_url": "data:image/png;base64,AAA"}],
        },
        {"type": "function_call", "call_id": "call_0", "name": "list_tags", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "call_0", "output": '{"tags": []}'},
    ]


def test_a_structured_answer_asks_for_the_json_schema_and_parses_it():
    client = _Client(reply=_response(text='{"summary": "ok"}'))

    parsed, result = _provider(client).execute_operation([Message(role="user", content="sum up")], "m", {"type": "object"}, LIMIT)

    assert parsed == {"summary": "ok"} and result.total_tokens == 120
    assert client.responses_sent[0]["text"] == {"format": {"type": "json_schema", "name": "output", "schema": {"type": "object"}, "strict": False}}


# --- only what was configured is sent -------------------------------------------------------------------


def test_no_temperature_is_sent_unless_one_is_configured():
    assert response_kwargs("m", CompletionOptions()) == {}
    assert response_kwargs("m", CompletionOptions(temperature=0.3)) == {"temperature": 0.3}
    assert chat_kwargs("m", CompletionOptions(max_tokens=10)) == {"max_tokens": 10}


def test_a_model_that_refuses_a_configured_temperature_runs_on_its_default():
    client = _Client(refuse={"temperature": "Unsupported value: 'temperature' does not support 0.3 with this model."})

    _provider(client).complete([Message(role="user", content="hi")], "thinker", CompletionOptions(temperature=0.3))
    _provider(client).complete([Message(role="user", content="hi")], "thinker", CompletionOptions(temperature=0.3))

    assert ["temperature" in s for s in client.responses_sent] == [True, False, False]


# --- OpenAI-compatible servers (a custom base URL): Chat Completions, corrected from their 400s ----------

COMPATIBLE = "http://localhost:8000/v1"


def test_a_compatible_server_gets_chat_completions():
    client = _Client()

    _provider(client, COMPATIBLE).complete([Message(role="user", content="hi")], "llama", LIMIT)

    assert client.responses_sent == [] and client.chat_sent[0]["max_tokens"] == 500


def test_a_server_that_wants_max_completion_tokens_is_retried_and_remembered():
    client = _Client(
        refuse={"max_tokens": "Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead."}
    )

    create_chat_completion(client, "new", LIMIT, messages=[])
    create_chat_completion(client, "new", LIMIT, messages=[])

    assert [("max_tokens" in s, s.get("max_completion_tokens")) for s in client.chat_sent] == [(True, None), (False, 500), (False, 500)]


def test_a_server_that_refuses_tools_while_reasoning_moves_that_models_tools_to_responses():
    refusal = (
        "Function tools with reasoning_effort are not supported for x in /v1/chat/completions. "
        "To use function tools, use /v1/responses or set reasoning_effort to 'none'."
    )
    client = _Client(refuse={"tools": refusal})
    provider = _provider(client, COMPATIBLE)

    with pytest.raises(NeedsResponsesAPI):
        create_chat_completion(client, "x", LIMIT, messages=[], tools=[{}])
    assert needs_responses("x")

    client.refuse = {}
    provider.complete_with_tools(TRANSCRIPT, "x", [TOOL], LIMIT)
    assert len(client.chat_sent) == 1 and len(client.responses_sent) == 1


def test_an_unrelated_400_is_raised_without_a_retry():
    client = _Client(refuse={"messages": "Invalid 'messages'"})

    with pytest.raises(_BadRequest):
        create_chat_completion(client, "m", LIMIT, messages=[])
    assert len(client.chat_sent) == 1


# --- the model list ----------------------------------------------------------------------------------------


def test_the_model_list_leaves_out_models_that_cant_chat():
    ids = ["gpt-6.1-sol", "o4-mini", "text-embedding-3-small", "whisper-1", "tts-1", "dall-e-3", "omni-moderation-latest", "gpt-image-1"]
    client = _Client()
    client.models = SimpleNamespace(list=lambda: SimpleNamespace(data=[SimpleNamespace(id=i) for i in ids]))

    assert _provider(client).list_models() == ["gpt-6.1-sol", "o4-mini"]
