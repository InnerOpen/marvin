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


def test_patch_sends_json_body_with_patch_method(helper):
    helper.patch("https://api.example.com/x/1", json={"status": "enabled"})
    req = _sent(helper)
    assert req.get_method() == "PATCH"
    assert json.loads(req.data) == {"status": "enabled"}
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


@pytest.mark.parametrize("verb", ["put", "patch", "delete"])
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


class _BigResponse(_FakeResponse):
    def __init__(self, size):
        self._body = b"x" * size


def test_response_cap_comes_from_settings(monkeypatch):
    from types import SimpleNamespace

    import marvin.services.integrations.http_client as http_client

    monkeypatch.setattr(http_client, "get_app_settings", lambda: SimpleNamespace(INTEGRATION_HTTP_MAX_BYTES=10))
    monkeypatch.setattr(http_client, "_host_is_public", lambda host: True)
    h = MarvinHttpHelper()
    h._opener = MagicMock()
    h._opener.open.return_value = _BigResponse(11)

    with pytest.raises(ValueError, match="size cap"):
        h.get("https://cms.example/picture.jpg")


def test_response_within_the_cap_is_returned(monkeypatch):
    monkeypatch.setattr("marvin.services.integrations.http_client._host_is_public", lambda host: True)
    h = MarvinHttpHelper(max_bytes=11)
    h._opener = MagicMock()
    h._opener.open.return_value = _BigResponse(11)

    assert len(h.get("https://cms.example/picture.jpg").content) == 11


# ── One retry on a network blip ───────────────────────────────────────────────


def test_a_get_that_times_out_is_retried_once(helper, monkeypatch):
    monkeypatch.setattr("marvin.services.integrations.http_client.RETRY_PAUSE_SECONDS", 0)
    helper._opener.open.side_effect = [TimeoutError("The read operation timed out"), _FakeResponse()]
    assert helper.get("https://api.example.com/media").status_code == 200
    assert helper._opener.open.call_count == 2


def test_a_second_timeout_is_raised_and_a_refused_connection_is_not_retried(helper, monkeypatch):
    import urllib.error

    monkeypatch.setattr("marvin.services.integrations.http_client.RETRY_PAUSE_SECONDS", 0)
    helper._opener.open.side_effect = [TimeoutError("slow"), TimeoutError("slow again")]
    with pytest.raises(TimeoutError):
        helper.get("https://api.example.com/media")
    helper._opener.open.reset_mock()
    helper._opener.open.side_effect = urllib.error.URLError(ConnectionRefusedError("refused"))
    with pytest.raises(urllib.error.URLError):
        helper.get("https://api.example.com/media")
    assert helper._opener.open.call_count == 1


def test_posts_are_never_retried(helper, monkeypatch):
    monkeypatch.setattr("marvin.services.integrations.http_client.RETRY_PAUSE_SECONDS", 0)
    helper._opener.open.side_effect = TimeoutError("slow")
    with pytest.raises(TimeoutError):
        helper.post("https://api.example.com/reply", json={"text": "hi"})
    assert helper._opener.open.call_count == 1


def test_what_counts_as_a_network_blip():
    import http.client
    import socket
    import urllib.error

    from marvin.services.integrations.http_client import is_transient_network_error as blip

    try:
        try:
            raise TimeoutError("read timed out")
        except TimeoutError as e:
            raise ValueError("Instagram API error") from e
    except ValueError as wrapped:
        assert blip(wrapped)  # a provider's own error, caused by a timeout
    assert blip(TimeoutError()) and blip(ConnectionResetError()) and blip(http.client.RemoteDisconnected())
    assert blip(urllib.error.URLError(TimeoutError()))
    assert not blip(ConnectionRefusedError()) and not blip(urllib.error.URLError(socket.gaierror())) and not blip(ValueError("HTTP 401"))
    assert not blip(None)
