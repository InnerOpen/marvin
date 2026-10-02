"""The HTTP helper handed to integration providers: every verb goes through the same SSRF guard."""

import json
from unittest.mock import MagicMock

import pytest

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

from marvin.services.integrations.http_client import MarvinHttpHelper, SsrfError  # noqa: E402


class _FakeResponse:
    status = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self):
        self._body = b'{"ok": true}'

    def read(self, _n):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


@pytest.fixture
def helper(monkeypatch):
    """A helper whose opener records the request instead of sending it; public-host check passes."""
    monkeypatch.setattr("marvin.services.integrations.http_client._host_is_public", lambda host: True)
    h = MarvinHttpHelper()
    h._opener = MagicMock()
    h._opener.open.return_value = _FakeResponse()
    return h


def _sent(helper):
    return helper._opener.open.call_args.args[0]


def test_put_sends_json_body_with_put_method(helper):
    helper.put("https://api.example.com/x", json={"a": 1})
    req = _sent(helper)
    assert req.get_method() == "PUT"
    assert json.loads(req.data) == {"a": 1}
    assert req.get_header("Content-type") == "application/json"


def test_delete_sends_delete_without_body(helper):
    response = helper.delete("https://api.example.com/x/1", headers={"Authorization": "Bearer t"})
    req = _sent(helper)
    assert req.get_method() == "DELETE"
    assert req.data is None
    assert req.get_header("Authorization") == "Bearer t"
    assert response.ok


def test_post_still_sends_post(helper):
    helper.post("https://api.example.com/x", json={"b": 2})
    assert _sent(helper).get_method() == "POST"


@pytest.mark.parametrize("verb", ["put", "delete"])
def test_new_verbs_refuse_private_hosts(verb):
    with pytest.raises(SsrfError):
        getattr(MarvinHttpHelper(), verb)("http://127.0.0.1:8080/internal")


def test_requests_carry_a_named_user_agent(helper):
    # Cloudflare refuses urllib's default agent (error 1010) — including this install's own assets.
    helper.get("https://api.example.com/asset.jpg")
    assert _sent(helper).get_header("User-agent") == "marvin-cms/integrations"


def test_a_providers_own_user_agent_is_kept(helper):
    helper.post("https://api.example.com/x", data=b"", headers={"User-Agent": "provider/1"})
    assert _sent(helper).get_header("User-agent") == "provider/1"
