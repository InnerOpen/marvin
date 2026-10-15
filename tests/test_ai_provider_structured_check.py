"""Test connection also asks the workspace's own model for a structured answer (providers_controller._check_structured):
a model can take plain text and still refuse what structured output needs (claude-sonnet-5-5 and a forced tool choice
on marvin-ai-anthropic 0.2.0), which broke every AI operation without the key test noticing."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from marvin.routes.ai import providers_controller as pc


class _Provider:
    supports_structured_output = True

    def __init__(self, error=None):
        self.error, self.calls = error, []

    def complete_structured(self, messages, model, schema):
        self.calls.append(model)
        if self.error:
            raise self.error
        return {"ok": True}


@pytest.fixture
def workspace(monkeypatch):
    monkeypatch.setattr("marvin.services.ai.authoring.default_authoring_model", lambda session, group_id, provider=None: "claude-sonnet-5-5")
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = SimpleNamespace(provider="anthropic")
    return session


def test_a_model_that_gives_structured_answers_passes(workspace):
    provider = _Provider()
    ok, message = pc._check_structured(workspace, "g", SimpleNamespace(is_default=True, provider_type="anthropic"), provider, "Connected")
    assert ok and provider.calls == ["claude-sonnet-5-5"] and "claude-sonnet-5-5 gives structured answers" in message


def test_a_model_that_refuses_them_fails_the_test_and_says_why(workspace):
    provider = _Provider(RuntimeError('tool_choice: type "tool" and "any" are not supported for this model.'))
    ok, message = pc._check_structured(workspace, "g", SimpleNamespace(is_default=True, provider_type="anthropic"), provider, "Connected")
    assert not ok and message.startswith("Connected. But claude-sonnet-5-5 can't give structured answers") and "tool_choice" in message


def test_a_provider_the_workspace_does_not_use_is_not_asked(workspace):
    provider = _Provider()
    ok, message = pc._check_structured(workspace, "g", SimpleNamespace(is_default=False, provider_type="openai"), provider, "Connected")
    assert ok and message == "Connected" and provider.calls == []
