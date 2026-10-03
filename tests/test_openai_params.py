"""OpenAI-style chat parameters: guessed from the model name, corrected by the API's 400, remembered.

Regression: `gpt-6.1-sol` matched none of the reasoning-model prefixes, was sent `max_tokens`, and every
call failed with "Unsupported parameter: 'max_tokens' ... Use 'max_completion_tokens' instead."
"""

import pytest

from marvin.services.ai.base import CompletionOptions
from marvin.services.ai.providers import openai_params
from marvin.services.ai.providers.openai_params import create_chat_completion, sampling_kwargs

OPTS = CompletionOptions(temperature=0.7, max_tokens=500)


class _BadRequest(Exception):
    status_code = 400

    def __init__(self, param, message):
        super().__init__(message)
        self.body = {"message": message, "type": "invalid_request_error", "param": param, "code": "unsupported_parameter"}


class _Client:
    """Refuses any request carrying one of `refuse` (a parameter name → the API's message)."""

    def __init__(self, refuse: dict[str, str]):
        self.refuse = refuse
        self.sent: list[dict] = []
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.sent.append(kwargs)
        for param, message in self.refuse.items():
            if param in kwargs:
                raise _BadRequest(param, message)
        return "ok"


@pytest.fixture(autouse=True)
def _forget():
    openai_params._learned.clear()
    yield
    openai_params._learned.clear()


NEW_MODEL_REFUSAL = {"max_tokens": "Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead."}


def test_a_new_model_that_wants_max_completion_tokens_is_retried_and_remembered():
    client = _Client(NEW_MODEL_REFUSAL)

    assert create_chat_completion(client, "gpt-7-preview", OPTS, messages=[]) == "ok"  # a name no prefix covers
    assert create_chat_completion(client, "gpt-7-preview", OPTS, messages=[]) == "ok"

    assert [("max_tokens" in s, s.get("max_completion_tokens")) for s in client.sent] == [(True, None), (False, 500), (False, 500)]


def test_a_model_that_only_knows_max_tokens_is_corrected_the_other_way():
    client = _Client({"max_completion_tokens": "Unrecognized request argument supplied: max_completion_tokens"})

    create_chat_completion(client, "o4-compatible-server", OPTS, messages=[])

    assert client.sent[-1]["max_tokens"] == 500 and "max_completion_tokens" not in client.sent[-1]


def test_a_model_that_refuses_temperature_gets_the_default_sampling():
    client = _Client({**NEW_MODEL_REFUSAL, "temperature": "Unsupported value: 'temperature' does not support 0.7 with this model."})

    create_chat_completion(client, "brand-new", OPTS, include_top_p=True, messages=[])

    assert client.sent[-1] == {"model": "brand-new", "messages": [], "max_completion_tokens": 500}


def test_an_unrelated_400_is_raised_without_a_retry():
    client = _Client({"messages": "Invalid 'messages'"})

    with pytest.raises(_BadRequest):
        create_chat_completion(client, "gpt-4o", OPTS, messages=[])
    assert len(client.sent) == 1


def test_a_refusal_already_corrected_is_raised_not_looped():
    client = _Client({"max_tokens": NEW_MODEL_REFUSAL["max_tokens"], "max_completion_tokens": "Unrecognized: max_completion_tokens"})

    with pytest.raises(_BadRequest):
        create_chat_completion(client, "confused", OPTS, messages=[])
    assert len(client.sent) <= 3


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-4o-mini", {"max_tokens": 500, "temperature": 0.7}),
        ("gpt-5.4-mini", {"max_completion_tokens": 500}),
        ("o3", {"max_completion_tokens": 500}),
        ("gpt-6.1-sol", {"max_completion_tokens": 500}),
    ],
)
def test_the_first_guess_comes_from_the_model_name(model, expected):
    assert sampling_kwargs(model, OPTS) == expected


def test_an_unset_limit_is_left_out():
    assert sampling_kwargs("gpt-5", CompletionOptions(max_tokens=None)) == {}


# --- tools on a model that refuses them on Chat Completions while it reasons -------------------------

from types import SimpleNamespace  # noqa: E402

from marvin.services.ai.base import Message, ToolCall, ToolDefinition  # noqa: E402
from marvin.services.ai.providers.openai import OpenAIProvider  # noqa: E402
from marvin.services.ai.providers.openai_params import NeedsResponsesAPI, needs_responses  # noqa: E402

TOOLS_REFUSAL = (
    "Function tools with reasoning_effort are not supported for gpt-6.1-sol in /v1/chat/completions. "
    "To use function tools, use /v1/responses or set reasoning_effort to 'none'."
)


class _ToolsClient:
    """Chat Completions refuses tools (like gpt-6.1-sol); the Responses API answers with one tool call."""

    def __init__(self):
        self.chat_calls = 0
        self.responses_sent: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.responses = SimpleNamespace(create=self._respond)

    def _chat(self, **kwargs):
        self.chat_calls += 1
        raise _BadRequest("reasoning_effort", TOOLS_REFUSAL)

    def _respond(self, **kwargs):
        self.responses_sent.append(kwargs)
        call = SimpleNamespace(type="function_call", call_id="call_1", name="search_content", arguments='{"query": "brain"}')
        return SimpleNamespace(
            output=[SimpleNamespace(type="reasoning"), call],
            output_text="",
            usage=SimpleNamespace(input_tokens=100, output_tokens=20, total_tokens=120),
            model="gpt-6.1-sol",
            incomplete_details=None,
            model_dump=lambda: {},
        )


def _provider(client):
    provider = OpenAIProvider(api_key="k")
    provider._client = lambda: client
    return provider


TRANSCRIPT = [
    Message(role="system", content="You are Marvin."),
    Message(role="user", content="check the brain"),
    Message(role="assistant", content="", tool_calls=[ToolCall(id="call_0", name="list_tags", arguments={})]),
    Message(role="tool", content='{"tags": []}', tool_call_id="call_0"),
]
TOOL = ToolDefinition(name="search_content", description="Search", input_schema={"type": "object", "properties": {}})


def test_the_tools_refusal_is_learned_as_a_switch_to_the_responses_api():
    with pytest.raises(NeedsResponsesAPI):
        create_chat_completion(_ToolsClient(), "gpt-6.1-sol", OPTS, messages=[], tools=[{}])

    assert needs_responses("gpt-6.1-sol")


def test_a_refused_tool_call_is_answered_through_the_responses_api_with_its_reasoning_kept():
    client = _ToolsClient()

    result = _provider(client).complete_with_tools(TRANSCRIPT, "gpt-6.1-sol", [TOOL], OPTS)

    assert [(c.id, c.name, c.arguments) for c in result.tool_calls] == [("call_1", "search_content", {"query": "brain"})]
    assert (result.prompt_tokens, result.completion_tokens, result.stop_reason) == (100, 20, "tool_calls")
    sent = client.responses_sent[0]
    assert "reasoning" not in sent and sent["max_output_tokens"] == 500 and sent["store"] is False
    assert sent["tools"] == [
        {"type": "function", "name": "search_content", "description": "Search", "parameters": TOOL.input_schema, "strict": False}
    ]
    assert sent["input"][2:] == [
        {"type": "function_call", "call_id": "call_0", "name": "list_tags", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "call_0", "output": '{"tags": []}'},
    ]


def test_once_learned_the_model_goes_straight_to_the_responses_api():
    client = _ToolsClient()
    provider = _provider(client)

    provider.complete_with_tools(TRANSCRIPT, "gpt-6.1-sol", [TOOL], OPTS)
    provider.complete_with_tools(TRANSCRIPT, "gpt-6.1-sol", [TOOL], OPTS)

    assert client.chat_calls == 1 and len(client.responses_sent) == 2
