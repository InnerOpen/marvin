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
