"""The `request` step (Call a web API) and template filters (2026-10-19; tasks/workflow-request-and-filters-plan.md)."""

import base64
import hashlib
import json
import uuid

import pytest
from pytest import fixture

from marvin.db.models.groups import Groups
from marvin.services.automation.actions.base import AutomationActionError
from marvin.services.automation.actions.request import run_request
from marvin.services.automation.authz import ROLE_ADMIN, ROLE_EDITOR
from marvin.services.automation.matcher import interpolate
from marvin.services.integrations import http_client
from marvin.services.integrations.http_client import MarvinHttpHelper

CONTEXT = {
    "entry": {
        "id": "e1",
        "title": "Hello, World of Leather",
        "published_at": "2026-10-19T21:30:00Z",
        "tags": ["leather", "repair"],
        "body": "**Bold** and <b>tags</b> &amp; more",
        "price": 12.3456,
        "empty": "",
        "email": "  Grace@Example.com ",
    }
}


# ── filters ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("${entry.title|slug}", "hello-world-of-leather"),
        ("${entry.title|upper}", "HELLO, WORLD OF LEATHER"),
        ("${entry.title|lower}", "hello, world of leather"),
        ("${entry.empty|default:'none'}", "none"),
        ("${entry.missing|default:'—'}", "—"),
        ("${entry.title|default:'unused'}", "Hello, World of Leather"),
        ("${entry.title|truncate:12}", "Hello…"),
        ("${entry.title|truncate:100}", "Hello, World of Leather"),
        ("${entry.title|replace:'World','Earth'}", "Hello, Earth of Leather"),
        ("${entry.tags|join:' · '}", "leather · repair"),
        ("${entry.tags|join}", "leather, repair"),
        ("${entry.tags|first}", "leather"),
        ("${entry.tags|last}", "repair"),
        ("${entry.tags|length}", 2),
        ("${entry.published_at|date}", "2026-10-19"),
        ("${entry.published_at|date:'%d %b %Y'}", "19 Oct 2026"),
        ("${entry.published_at|date:'%H:%M',Europe/Madrid}", "23:30"),
        ("${entry.price|round:2}", 12.35),
        ("${entry.price|round}", 12),
        ("${entry.body|strip_html}", "**Bold** and tags & more"),
        ("${entry.title|escape}", "Hello, World of Leather"),
        ("${entry.tags|json}", '["leather", "repair"]'),
        ("${entry.title|url}", "Hello%2C%20World%20of%20Leather"),
        ("${entry.email|trim|lower|md5}", hashlib.md5(b"grace@example.com", usedforsecurity=False).hexdigest()),
    ],
)
def test_filters(template, expected):
    assert interpolate(template, CONTEXT) == expected


def test_a_chain_runs_left_to_right_and_a_quoted_argument_keeps_its_bar_and_comma():
    assert interpolate("${entry.title|upper|replace:'WORLD','A|B, C'}", CONTEXT) == "HELLO, A|B, C OF LEATHER"


def test_filters_inside_text_are_stringified():
    assert interpolate("Tags: ${entry.tags|length} — ${entry.published_at|date:'%Y'}", CONTEXT) == "Tags: 2 — 2026"


def test_an_unknown_filter_gives_nothing_at_run_time():
    assert interpolate("${entry.title|nope}", CONTEXT) is None
    assert interpolate("[${entry.title|nope}]", CONTEXT) == "[]"


def test_a_filter_never_fails_on_odd_input():
    assert interpolate("${entry.title|date:'%Y'}", CONTEXT) == "Hello, World of Leather"
    assert interpolate("${entry.title|round:2}", CONTEXT) == "Hello, World of Leather"


def test_markdown_uses_the_email_converter():
    assert "<strong>Bold</strong>" in interpolate("${entry.body|markdown}", CONTEXT)


def test_base64_and_sha256():
    assert interpolate("${entry.tags|first|base64}", CONTEXT) == base64.b64encode(b"leather").decode()
    assert len(interpolate("${entry.title|sha256}", CONTEXT)) == 64


# ── the save check ───────────────────────────────────────────────────────────


@fixture
def group(db_session):
    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"req-{gid.hex[:8]}", slug=f"req-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.commit()
    yield gid
    from marvin.db.models.groups.secrets import WorkspaceSecret

    db_session.rollback()
    db_session.query(WorkspaceSecret).filter(WorkspaceSecret.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _issues(db_session, gid, step) -> list[tuple[str, str]]:
    from marvin.services.automation.authoring import reference_issues

    definition = {"trigger": {"type": "manual"}, "actions": [step]}
    return [(i["path"], i["message"]) for i in reference_issues(db_session, gid, definition)]


def test_a_mistyped_filter_is_refused_when_saved(db_session, group):
    [(path, message)] = _issues(db_session, group, {"kind": "request", "url": "https://x.example.com", "query": {"t": "${entry.title|tuncate:40}"}})
    assert path == "actions[0].query" and "no “tuncate” filter" in message


@pytest.mark.parametrize(
    ("template", "wording"),
    [
        ("${entry.title|truncate}", "takes 1 to 2 arguments"),
        ("${entry.title|truncate:many}", "needs a whole number"),
        ("${entry.published_at|date:'%Y',Mars/Olympus}", "isn't a timezone"),
    ],
)
def test_bad_filter_arguments_are_refused_when_saved(db_session, group, template, wording):
    issues = _issues(db_session, group, {"kind": "request", "url": "https://api.example.com/x", "query": {"q": template}})
    assert any(wording in m for _, m in issues), issues


def test_good_filters_save(db_session, group):
    step = {
        "kind": "request",
        "url": "https://api.example.com/x",
        "query": {"d": "${entry.published_at|date:'%d %b',Europe/Madrid}", "t": "${entry.title|truncate:60|default:'x'}"},
    }
    assert _issues(db_session, group, step) == []


def test_a_request_step_refuses_a_typed_in_key_and_a_bad_address(db_session, group):
    issues = dict(_issues(db_session, group, {"kind": "request", "url": "ftp://x", "headers": {"X-Api-Key": "abc123"}}))
    assert "isn't a web address" in issues["actions[0].url"]
    assert "workspace secret" in issues["actions[0].headers"]
    assert _issues(db_session, group, {"kind": "request", "url": "https://x.example.com", "headers": {"X-Api-Key": "{{MY_KEY}}"}}) == []


def test_the_schema_refuses_a_body_on_get():
    from pydantic import ValidationError

    from marvin.schemas.group.automation_definition import ACTION_MODELS

    with pytest.raises(ValidationError, match="sends no body"):
        ACTION_MODELS["request"](kind="request", url="https://x.example.com", body={"a": 1})


# ── the request step ─────────────────────────────────────────────────────────


class _Recorder:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, method, url, *, data=None, headers=None, timeout=15):
        self.calls.append({"method": method, "url": url, "data": data, "headers": dict(headers or {}), "timeout": timeout})
        nxt = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt


def _answer(status=200, body=None, content_type="application/json"):
    content = json.dumps(body).encode() if content_type == "application/json" else (body or "").encode()
    return http_client.Response(status_code=status, headers={"Content-Type": content_type, "X-Request-Id": "r1"}, content=content)


@fixture
def send(monkeypatch):
    def install(*responses):
        recorder = _Recorder(*responses)
        monkeypatch.setattr(MarvinHttpHelper, "request", lambda _self, *a, **k: recorder(*a, **k))
        monkeypatch.setattr("marvin.services.automation.actions.request.time.sleep", lambda s: None)
        return recorder

    return install


def _run(db_session, gid, action, *, role=ROLE_ADMIN, dry_run=False):
    return run_request(db_session, gid, {"kind": "request", **action}, CONTEXT, authorizer_role=role, dry_run=dry_run)


def test_a_post_sends_json_with_the_query_and_a_secret_and_hands_back_the_answer(db_session, group, send):
    from marvin.services.secrets import get_secret_backend

    get_secret_backend().set("API_TOKEN", "tok-123", group, db_session)
    get_secret_backend().set("API_KEY", "key-456", group, db_session)
    db_session.commit()
    recorder = send(_answer(201, {"id": "rec9"}))
    out = _run(
        db_session,
        group,
        {
            "method": "POST",
            "url": "https://api.example.com/v0/rows",
            "query": {"view": "${entry.title|slug}"},
            "headers": {"X-Api-Key": "{{API_KEY}}"},
            "secret_ref": "API_TOKEN",
            "body": {"fields": {"Title": "${entry.title}", "Date": "${entry.published_at|date}"}},
        },
    )
    [call] = recorder.calls
    assert call["method"] == "POST" and call["url"] == "https://api.example.com/v0/rows?view=hello-world-of-leather"
    assert json.loads(call["data"]) == {"fields": {"Title": "Hello, World of Leather", "Date": "2026-10-19"}}
    assert call["headers"]["Authorization"] == "Bearer tok-123" and call["headers"]["X-Api-Key"] == "key-456"
    assert call["headers"]["Content-Type"] == "application/json"
    assert out["status"] == 201 and out["ok"] and out["json"] == {"id": "rec9"} and out["headers"]["x-request-id"] == "r1"


def test_a_form_body_and_basic_auth(db_session, group, send):
    from marvin.services.secrets import get_secret_backend

    get_secret_backend().set("SHORTENER", "me:pa55", group, db_session)
    db_session.commit()
    recorder = send(_answer(200, "ok", "text/plain"))
    out = _run(
        db_session,
        group,
        {
            "method": "POST",
            "url": "https://s.example.com/new",
            "body_type": "form",
            "body": {"u": "${entry.title}"},
            "secret_ref": "SHORTENER",
            "auth_scheme": "Basic",
        },
    )
    [call] = recorder.calls
    assert call["data"] == b"u=Hello%2C+World+of+Leather" and call["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert call["headers"]["Authorization"] == "Basic " + base64.b64encode(b"me:pa55").decode()
    assert out["text"] == "ok" and "json" not in out


def test_a_get_sends_no_body(db_session, group, send):
    recorder = send(_answer(200, {"items": []}))
    _run(db_session, group, {"url": "https://api.example.com/items"})
    assert recorder.calls[0]["method"] == "GET" and recorder.calls[0]["data"] is None


def test_a_non_2xx_fails_the_step_with_what_the_server_said(db_session, group, send):
    send(_answer(422, {"error": "bad field"}))
    with pytest.raises(AutomationActionError, match="422.*bad field"):
        _run(db_session, group, {"method": "POST", "url": "https://api.example.com/rows", "body": {}})


def test_fail_on_error_false_makes_the_answer_output(db_session, group, send):
    send(_answer(404, {"error": "missing"}))
    out = _run(db_session, group, {"url": "https://api.example.com/rows/1", "fail_on_error": False})
    assert out["ok"] is False and out["status"] == 404 and out["json"] == {"error": "missing"}


def test_retries_repeat_a_5xx_and_a_network_blip_then_succeed(db_session, group, send):
    recorder = send(_answer(503, {}), TimeoutError("slow"), _answer(200, {"ok": 1}))
    out = _run(db_session, group, {"method": "POST", "url": "https://api.example.com/rows", "body": {}, "retries": 2})
    assert len(recorder.calls) == 3 and out["json"] == {"ok": 1}


def test_without_retries_a_5xx_fails_at_once(db_session, group, send):
    recorder = send(_answer(503, {}), _answer(200, {}))
    with pytest.raises(AutomationActionError, match="503"):
        _run(db_session, group, {"method": "POST", "url": "https://api.example.com/rows", "body": {}})
    assert len(recorder.calls) == 1


def test_a_private_address_is_refused(db_session, group):
    with pytest.raises(AutomationActionError, match="refused"):
        _run(db_session, group, {"url": "http://127.0.0.1:8080/admin"})


def test_an_editor_cannot_run_it(db_session, group, send):
    send(_answer(200, {}))
    with pytest.raises(Exception, match="request step"):
        _run(db_session, group, {"url": "https://api.example.com/x"}, role=ROLE_EDITOR)


def test_a_dry_run_shows_the_request_masked_and_sends_nothing(db_session, group, send):
    recorder = send(_answer(200, {}))
    out = _run(
        db_session,
        group,
        {
            "method": "POST",
            "url": "https://api.example.com/rows",
            "headers": {"X-Api-Key": "literal-key", "X-Ref": "{{API_KEY}}"},
            "secret_ref": "API_TOKEN",
            "body": {"t": "${entry.title}"},
        },
        dry_run=True,
    )
    assert recorder.calls == []
    assert out["dry_run"] and out["body"] == {"t": "Hello, World of Leather"}
    assert out["headers"]["X-Api-Key"] == "••••••" and out["headers"]["X-Ref"] == "{{API_KEY}}"
    assert out["headers"]["Authorization"] == "Bearer {{API_TOKEN}}"


def test_an_idempotency_key_makes_the_call_once(db_session, group, send):
    recorder = send(_answer(200, {"id": 1}))
    action = {"method": "POST", "url": "https://api.example.com/rows", "body": {}, "idempotency_key": "row-${entry.id}"}
    first = _run(db_session, group, action)
    second = _run(db_session, group, action)
    assert len(recorder.calls) == 1 and first["json"] == second["json"] == {"id": 1} and second["idempotency"]["duplicate"]
