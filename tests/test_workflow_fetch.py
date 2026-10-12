"""The fetch step: read a web address, or check the links in a text, through core's guarded HTTP client. A dead link
or server is the step's output (for a `when`), never a failed step; private addresses are refused; a dry run doesn't
fetch. The web is faked at the client's get/head, so the step's own logic (HEAD refused → GET) is what's tested."""

# ruff: noqa: F811 — `ws` is a fixture, not a redefinition
import urllib.error

import pytest

from marvin.services.automation.actions.fetch import check_links, extract_links, fetch
from marvin.services.automation.authoring import draft_issues
from tests.test_workflow_authoring import workspace, ws  # noqa: F401 — fixtures


def _web(monkeypatch, pages: dict) -> list:
    """Answer GET/HEAD from ``pages`` {url: (status | {method: status}, content type, body)}; any other address gives
    no answer. Returns the (method, url) calls made."""
    from marvin.services.integrations import http_client

    calls: list[tuple[str, str]] = []

    def answering(method):
        def send(self, url, *, headers=None, timeout=15):
            calls.append((method, url))
            if url not in pages:
                raise urllib.error.URLError(ConnectionRefusedError("connection refused"))
            status, content_type, body = pages[url]
            status = status[method] if isinstance(status, dict) else status
            return http_client.Response(status_code=status, headers={"Content-Type": content_type}, content=body.encode())

        return send

    monkeypatch.setattr(http_client.MarvinHttpHelper, "get", answering("GET"))
    monkeypatch.setattr(http_client.MarvinHttpHelper, "head", answering("HEAD"))
    return calls


def test_links_are_found_in_markdown_html_and_prose_once_each():
    text = (
        "See [the shop](https://shop.example/coat) and <a href='/articles/wax'>wax</a>.\n"
        "Bare: https://maker.example/notes, again https://shop.example/coat#sizes. "
        "Not links: and/or, 24/7, //cdn.example/x, mailto:me@example.com."
    )
    assert extract_links(text, "https://site.example") == [
        "https://shop.example/coat",
        "https://site.example/articles/wax",
        "https://maker.example/notes",
    ]
    assert extract_links(text) == ["https://shop.example/coat", "https://maker.example/notes"]  # no base: relative links skipped


def test_only_dead_links_are_broken(monkeypatch):
    calls = _web(
        monkeypatch,
        {
            "https://a.example/ok": (200, "text/html", ""),
            "https://a.example/gone": (404, "text/html", ""),
            "https://a.example/down": (503, "text/html", ""),
            "https://a.example/no-head": ({"HEAD": 405, "GET": 200}, "text/html", ""),
            "https://a.example/robots-unwelcome": (403, "text/html", ""),
            "https://a.example/busy": (429, "text/html", ""),
        },
    )
    links = [*(f"https://a.example/{p}" for p in ("ok", "gone", "down", "no-head", "robots-unwelcome", "busy")), "https://nowhere.example/"]

    out = check_links(links)

    assert (out["checked"], out["broken_count"]) == (7, 3)
    assert [(b["url"], b["status"]) for b in out["broken"]] == [
        ("https://a.example/gone", 404),
        ("https://a.example/down", 503),
        ("https://nowhere.example/", 0),
    ]
    assert "no answer" in out["broken"][2]["error"] and out["text"].splitlines()[0] == "- https://a.example/gone — 404"
    assert ("GET", "https://a.example/no-head") in calls  # a server refusing HEAD is asked again with GET


def test_a_private_address_is_refused_without_a_request():
    out = check_links(["http://127.0.0.1:8080/admin"])
    assert out["broken_count"] == 1 and out["broken"][0]["error"].startswith("refused:")
    assert fetch("http://localhost/x")["error"].startswith("refused:")


def test_fetch_reads_a_page_or_an_api(monkeypatch):
    _web(
        monkeypatch,
        {
            "https://shop.example/coat": (200, "text/html; charset=utf-8", "<html><title> Chore coat \n</title>Sold out</html>"),
            "https://api.example/stock": (200, "application/json", '{"in_stock": 0}'),
        },
    )
    page = fetch("https://shop.example/coat")
    assert (page["status"], page["ok"], page["title"], page["content_type"]) == (200, True, "Chore coat", "text/html")
    assert "Sold out" in page["text"]
    assert fetch("https://api.example/stock")["json"] == {"in_stock": 0}
    assert fetch("https://gone.example/")["status"] == 0  # no answer: output, not an exception


# ── The step ──────────────────────────────────────────────────────────────────
def _run(ws, actions, *, dry_run=False):
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.services.automation.engine import run_automation_now
    from marvin.services.automation.recorder import ExecutionRecorder

    wf = WorkspaceAutomationModel(
        session=ws.session,
        group_id=ws.gid,
        name="Fetch",
        slug="fetch-wf",
        enabled=True,
        definition={"trigger": {"type": "manual"}, "actions": actions},
    )
    ws.session.add(wf)
    ws.session.commit()
    return run_automation_now(ws.session, ws.gid, wf, user_id=ws.uid, recorder=ExecutionRecorder(ws.session, ws.gid), dry_run=dry_run)


def test_a_dead_page_is_output_for_a_when_not_a_failed_run(ws, monkeypatch):
    _web(monkeypatch, {})
    result = _run(
        ws,
        [
            {"kind": "fetch", "id": "page", "url": "https://gone.example/"},
            {"kind": "collect", "entity": "entry", "query": {}, "when": {"field": "steps.page.output.ok", "op": "eq", "value": False}},
        ],
    )
    assert result["ok"] and "count" in result["result"], result  # the page's failure ran the step gated on it


def test_find_looks_for_words_on_the_page_in_any_case(ws, monkeypatch):
    _web(monkeypatch, {"https://shop.example/coat": (200, "text/html", "<p>Chore coat — SOLD OUT</p>")})
    result = _run(ws, [{"kind": "fetch", "id": "page", "url": "https://shop.example/coat", "find": ["sold out", "discontinued"]}])
    assert result["result"]["found"] == ["sold out"]


def test_a_dry_run_makes_no_request(ws, monkeypatch):
    calls = _web(monkeypatch, {"https://shop.example/": (200, "text/html", "")})
    result = _run(ws, [{"kind": "fetch", "id": "page", "url": "https://shop.example/"}], dry_run=True)
    assert calls == [] and result["plan"][0]["resolved"]["would_fetch"] == "https://shop.example/"


@pytest.mark.parametrize(
    ("step", "path"),
    [
        ({"kind": "fetch"}, "actions[0]"),  # neither url nor links
        ({"kind": "fetch", "url": "https://a.example", "links": "x"}, "actions[0]"),
        ({"kind": "fetch", "url": "ftp://files.example/x"}, "actions[0].url"),
        ({"kind": "fetch", "url": "https://a.example", "method": "POST"}, "actions[0].method"),
    ],
)
def test_the_validator_names_what_a_fetch_step_lacks(ws, step, path):
    issues = draft_issues(ws.session, ws.gid, {"trigger": {"type": "manual"}, "actions": [step]})
    assert any(str(i.get("path", "")).startswith(path) for i in issues), issues
