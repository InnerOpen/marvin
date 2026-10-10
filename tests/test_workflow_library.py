"""The Workflow Library (docs/workflow-library), held to the statuses its catalogue claims.

A recipe says it is `verified-current` only because this module configures its JSON against a fixture
workspace, passes it through `draft_issues` (the same gate as draft_workflow and POST /api/automations),
saves it as a real workflow and runs the real engine on deterministic data — every external call
(integration provider, outgoing webhook, AI provider) mocked, the side effects asserted. A
`supported-after-configuration` recipe passes the validator (when it is a workflow) or carries the
configuration it stands for; a `needs-*` / `concept` recipe has no runnable JSON at all.

The catalogue (catalogue.json) and the readable catalogue.md are checked to stay in step: the markdown is
rendered by scripts/render_workflow_library.py and must not drift.
"""

import json
import pathlib
import subprocess
import sys
import uuid
from types import SimpleNamespace

import httpx
import pytest
from pytest import fixture

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

from marvin_integration_sdk import INTEGRATION_REGISTRY, IntegrationProvider, ProviderAction  # noqa: E402
from marvin_integration_sdk.ai.fake import FakeAIProvider, ScriptedTransport  # noqa: E402

from marvin.services.ai.tools import get_tool  # noqa: E402
from marvin.services.automation import recipes  # noqa: E402
from marvin.services.automation.authoring import authoring_guide, draft_issues, guide_size, parse_workflow, workspace_refs  # noqa: E402
from marvin.services.automation.context import event_context  # noqa: E402
from marvin.services.automation.engine import run_automation_now, run_automations_for_event  # noqa: E402
from marvin.services.automation.library import RecipeConfigError, configure, placeholders, unresolved  # noqa: E402
from marvin.services.automation.recorder import ExecutionRecorder  # noqa: E402
from tests.test_workflow_item_targets import _asset, _resource  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "docs" / "workflow-library"
RECIPES_DIR = recipes.DIR
CATALOGUE = recipes.catalogue()
BY_ID = {r["id"]: r for r in CATALOGUE["recipes"]}
STATUSES = ("verified-current", "supported-after-configuration", "needs-adapter", "needs-engine-capability", "concept")
RUNNABLE = {"verified-current", "supported-after-configuration"}
WORKFLOW_RECIPES = sorted(r["id"] for r in CATALOGUE["recipes"] if r["shape"] == "workflow")
VERIFIED = sorted(r["id"] for r in CATALOGUE["recipes"] if r["status"] == "verified-current")


def _recipe(rid: str) -> tuple[dict, dict]:
    doc = json.loads((RECIPES_DIR / f"{rid}.json").read_text())
    vars_ = json.loads((RECIPES_DIR / f"{rid}.vars.json").read_text())["variables"]
    return doc, vars_


# ── Catalogue shape ───────────────────────────────────────────────────────────
def test_catalogue_covers_every_recipe_file_and_every_status_is_honest():
    assert sum(1 for r in CATALOGUE["recipes"] if r["brief"]) == 100, "every idea of the starter brief is catalogued"
    assert len({r["id"] for r in CATALOGUE["recipes"]}) == len(CATALOGUE["recipes"])
    files = {p.name.removesuffix(".json") for p in RECIPES_DIR.glob("*.json") if not p.name.endswith(".vars.json") and p.name != "catalogue.json"}
    assert files == set(WORKFLOW_RECIPES), "every recipe file is catalogued as a workflow, and every workflow recipe has a file"
    for r in CATALOGUE["recipes"]:
        assert r["status"] in STATUSES, r["id"]
        assert r["shape"] in ("workflow", "configuration", "idea"), r["id"]
        runnable = r["status"] in RUNNABLE
        assert r["runnable"] is runnable, f"{r['id']}: runnable must follow its status"
        if r["shape"] == "workflow":
            assert runnable, f"{r['id']}: a recipe file is only shipped for a runnable recipe"
            assert (RECIPES_DIR / f"{r['id']}.vars.json").exists()
            assert r["recipe"] == f"{r['id']}.json"
        else:
            assert r.get("recipe") is None
        if r["shape"] == "configuration":
            assert r["status"] == "supported-after-configuration"
            assert any(o.get("configuration") for o in r["supporting_objects"]), f"{r['id']}: a configuration recipe carries its configuration"
        if r["status"].startswith("needs-"):
            assert r["dependencies"], f"{r['id']}: a needs-* recipe names what it waits for"
            assert all(d.get("capability") and d.get("acceptance") for d in r["dependencies"]), r["id"]
        if r["status"] == "verified-current":
            assert r["verification"]["level"] == "fixture-executed", r["id"]
            assert r["verification"]["test"].startswith("tests/test_workflow_library.py::"), r["id"]
        # Setup variables in the catalogue mirror the vars file exactly, and only workflows have them.
        if r["shape"] == "workflow":
            _, vars_ = _recipe(r["id"])
            assert {v["name"]: v["type"] for v in r["setup_variables"]} == {k: v["type"] for k, v in vars_.items()}, r["id"]


def test_every_verified_recipe_has_an_execution_test_here():
    names = {n for n in globals() if n.startswith("test_")}
    names |= {f"TestExecution::{m}" for m in dir(TestExecution) if m.startswith("test_")}
    for rid in VERIFIED:
        test = BY_ID[rid]["verification"]["test"].split("::", 1)[1]
        assert test in names, f"{rid} claims {test}, which doesn't exist"


def test_catalogue_markdown_is_rendered_from_the_json():
    rendered = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "render_workflow_library.py"), "--stdout"], check=True, capture_output=True, text=True
    ).stdout
    assert rendered == (LIBRARY / "catalogue.md").read_text(), "catalogue.md is stale: run scripts/render_workflow_library.py"


# ── Placeholder substitution ──────────────────────────────────────────────────
class TestConfigure:
    VARS = {
        "flag": {"type": "boolean"},
        "n": {"type": "integer"},
        "obj": {"type": "object"},
        "slug": {"type": "entry_type_slug"},
        "word": {"type": "text"},
    }

    def test_whole_value_placeholders_keep_their_type_and_templates_survive(self):
        recipe = {"a": "{{flag}}", "b": "{{n}}", "c": "{{obj}}", "d": "{{slug}}", "t": "${entry.title}", "s": "{{API_KEY}}"}
        recipe["e"] = "Hi ${entry.title} / {{word}}"
        out = configure(recipe, {"flag": True, "n": 3, "obj": {"k": "v"}, "slug": "recipe", "word": "hello"}, self.VARS)
        assert out == {"a": True, "b": 3, "c": {"k": "v"}, "d": "recipe", "t": "${entry.title}", "s": "{{API_KEY}}", "e": "Hi ${entry.title} / hello"}
        assert recipe["a"] == "{{flag}}"  # the recipe itself is untouched

    def test_a_placeholder_inside_a_template_path_composes_the_path(self):
        out = configure({"v": "${entry.data.{{slug}}}"}, {"slug": "body"}, self.VARS)
        assert out == {"v": "${entry.data.body}"}

    def test_type_mismatches_and_missing_values_are_refused(self):
        with pytest.raises(RecipeConfigError, match="must be a boolean"):
            configure({"a": "{{flag}}"}, {"flag": "yes"}, self.VARS)
        with pytest.raises(RecipeConfigError, match="must be a integer, got a boolean"):
            configure({"a": "{{n}}"}, {"n": True}, self.VARS)
        with pytest.raises(RecipeConfigError, match="missing setup value"):
            configure({"a": "{{slug}}"}, {}, self.VARS)
        with pytest.raises(RecipeConfigError, match="undeclared"):
            configure({"a": "{{nope}}"}, {"nope": 1}, self.VARS)
        with pytest.raises(RecipeConfigError, match="can't be embedded"):
            configure({"a": "x {{obj}}"}, {"obj": {}}, self.VARS)

    def test_secret_references_are_not_placeholders(self):
        assert placeholders({"h": "Token {{API_KEY}}", "p": "{{entry_type}}"}) == {"entry_type"}


# ── Fixture workspace ─────────────────────────────────────────────────────────
class _Buttondown(IntegrationProvider):
    slug = "buttondown"
    name = "Buttondown (fake)"
    actions = (ProviderAction(key="create_issue_email", label="Create issue email"), ProviderAction(key="subscribe", label="Subscribe"))

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def run_action(self, key, args, ctx):
        self.calls.append((key, dict(args)))
        if args.get("subject") == "Boom":
            raise ValueError("Buttondown is down")
        existing = args.get("email_id")
        return {
            "email_id": existing or "em_1",
            "status": "updated" if existing else "created",
            "delivery": "draft",
            "url": "https://buttondown.example/em_1",
        }


class _Apprise(IntegrationProvider):
    slug = "apprise"
    name = "Apprise (fake)"
    actions = (
        ProviderAction(
            key="notify",
            label="Send notification",
            capability="notify",
            input_schema={"type": "object", "properties": {"title": {"type": "string"}, "body": {"type": "string"}}, "required": ["body"]},
        ),
    )

    def __init__(self):
        self.calls: list[dict] = []

    def run_action(self, key, args, ctx):
        self.calls.append(dict(args))
        return {"sent": True, "targets": 1}


class _N8n(IntegrationProvider):
    slug = "n8n"
    name = "n8n (fake)"
    actions = (ProviderAction(key="trigger_workflow", label="Trigger n8n workflow"),)

    def __init__(self):
        self.calls: list[dict] = []

    def run_action(self, key, args, ctx):
        self.calls.append(dict(args))
        return {
            "ok": True,
            "status_code": 200,
            "path": args["path"],
            "response": {"created": 2},
            "execution_id": "ex_1",
            "execution_url": "https://n8n.example/ex/1",
        }


def _field(key, type_="text", required=False):
    return {"key": key, "label": key.replace("_", " ").title(), "type": type_, "required": required}


@fixture
def ws(db_session, monkeypatch):
    """A workspace with everything the library's setup variables can name: entry types, a collection,
    the three integration connections (fake providers), outgoing webhooks and AI on (fake provider)."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.db.models.groups.webhooks import GroupWebhooksModel, Method
    from marvin.db.models.platform import EntryTypes
    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.users.users import Users
    from marvin.services.ai import factory
    from marvin.services.event_bus_service.event_types import WebhookMode

    providers = {"buttondown": _Buttondown(), "apprise": _Apprise(), "n8n": _N8n()}
    for slug, provider in providers.items():
        monkeypatch.setitem(INTEGRATION_REGISTRY, slug, provider)
    monkeypatch.setattr("marvin.services.secrets.resolver.resolve_secret", lambda ref, gid=None: "tok")
    transport = ScriptedTransport()
    monkeypatch.setattr(factory, "get_workspace_ai_provider", lambda *a, **k: FakeAIProvider(transport))

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"library-{marker}", slug=f"library-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    # A real user: run rows (triggered_by) and the event log (user_id) hold foreign keys to users.
    uid = uuid.uuid4()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid, group_id=gid, username=f"u-{marker}", email=f"u-{marker}@t.test", full_name="U", password="x",
            is_superuser=False, platform_role="NONE", auth_method="MARVIN",
        )
    )  # fmt: skip

    types = {}
    specs = {
        "newsletter-issue": ([_field("body", "markdown"), _field("preview")], None, None),
        "article": ([_field("body", "markdown", required=True)], "/articles/{slug}", None),
        "campaign": ([_field("utm_source"), _field("utm_medium")], "/campaigns/{slug}", None),
        "contact-request": ([_field("email"), _field("message", "textarea")], None, {"submittable": True}),
    }
    for slug, (fields, pattern, caps) in specs.items():
        et = EntryTypes(session=db_session, group_id=gid, name=slug.replace("-", " ").title(), slug=slug, schema_json={"fields": fields})
        et.id = uuid.uuid4()
        et.page_url_pattern = pattern
        et.capabilities_json = caps
        db_session.add(et)
        types[slug] = et.id
    db_session.add(Collections(session=db_session, group_id=gid, name="Featured", slug="featured"))
    for slug, provider in (("newsletter", "buttondown"), ("alerts", "apprise"), ("automation-hub", "n8n")):
        db_session.add(IntegrationModel(session=db_session, group_id=gid, provider=provider, name=slug, slug=slug, enabled=True, config={}))
    webhooks = {}
    for name, url in (
        ("announce", "https://community.example/hooks/new-post"),
        ("search-index", "https://search.example/reindex"),
        ("handoff", "https://client.example/intake"),
        ("forum", "https://forum.example/posts.json"),
        ("uploads", "https://chat.example/hooks/uploads"),
    ):
        row = GroupWebhooksModel(
            session=db_session, group_id=gid, name=name, url=url, method=Method.POST, enabled=True, webhook_type=WebhookMode.workflow
        )
        db_session.add(row)
        db_session.flush()
        webhooks[name] = str(row.id)
    db_session.add(WorkspaceAISettingsModel(session=db_session, group_id=gid, enabled=True, model="fake-model", approval_mode="allow-draft-update"))
    db_session.commit()

    values = {
        "newsletter_entry_type": "newsletter-issue",
        "newsletter_integration": "newsletter",
        "body_field": "body",
        "preview_field": "preview",
        "entry_type": "article",
        "announcement_webhook_id": webhooks["announce"],
        "refresh_webhook_id": webhooks["search-index"],
        "handoff_webhook_id": webhooks["handoff"],
        "forum_webhook_id": webhooks["forum"],
        "discussion_url_path": "topic_url",
        "ready_status": "approved",
        "campaign_entry_type": "campaign",
        "source_field": "utm_source",
        "medium_field": "utm_medium",
        "form_entry_type": "contact-request",
        "message_field": "message",
        "notify_integration": "alerts",
        "collection_name": "Featured",
        "n8n_integration": "automation-hub",
        "n8n_webhook_path": "editorial-tasks",
        "collection_slug": "featured",
        "interval_seconds": 3600,
        "incoming_webhook": "any",
        "upload_webhook_id": webhooks["uploads"],
    }
    yield SimpleNamespace(gid=gid, uid=uid, session=db_session, types=types, webhooks=webhooks, values=values, providers=providers, ai=transport)

    from marvin.db.models.groups.automation_executions import AutomationActionExecutionModel, AutomationExecutionModel
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    db_session.query(AutomationActionExecutionModel).filter(AutomationActionExecutionModel.group_id == gid).delete()
    db_session.query(AutomationExecutionModel).filter(AutomationExecutionModel.group_id == gid).delete()
    db_session.query(WorkspaceAutomationModel).filter(WorkspaceAutomationModel.group_id == gid).delete()
    db_session.query(IntegrationModel).filter(IntegrationModel.group_id == gid).delete()
    db_session.query(WorkspaceAISettingsModel).filter(WorkspaceAISettingsModel.group_id == gid).delete()
    purge_group_dependents(db_session, gid)
    db_session.query(Users).filter(Users.id == uid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _configured(ws, rid: str) -> dict:
    """The recipe's definition with the fixture workspace's values in place of its setup placeholders —
    as a copy from the library would hand it to POST /api/automations."""
    doc, vars_ = _recipe(rid)
    configured = configure(doc, {k: ws.values[k] for k in placeholders(doc)}, vars_)
    assert unresolved(configured) == set()
    before, after = json.dumps(doc).count("${"), json.dumps(configured).count("${")
    assert before == after, f"{rid}: setup substitution must leave every ${{…}} run-time template in place"
    parsed = parse_workflow(configured)
    assert parsed.error is None and parsed.name, parsed.error
    return parsed.definition


def _install(ws, rid: str, *, enabled: bool = True):
    """Save a configured recipe as a workflow in the fixture workspace, after it passes draft_issues."""
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    definition = _configured(ws, rid)
    assert draft_issues(ws.session, ws.gid, definition) == [], rid
    row = WorkspaceAutomationModel(session=ws.session, group_id=ws.gid, name=BY_ID[rid]["title"], slug=rid, enabled=enabled, definition=definition)
    ws.session.add(row)
    ws.session.commit()
    return row


def _entry(ws, type_slug: str, title: str, *, status: str = "draft", data: dict | None = None, summary: str | None = None, metadata=None):
    from marvin.db.models.platform import Entries

    entry = Entries(
        session=ws.session,
        group_id=ws.gid,
        entry_type_id=ws.types[type_slug],
        title=title,
        slug=f"{title.lower().replace(' ', '-')}-{ws.gid.hex[:6]}",
        status=status,
        data_json=data or {},
        metadata_json=metadata or {},
        summary=summary,
    )
    ws.session.add(entry)
    ws.session.commit()
    return entry


def _reload(ws, entry):
    from marvin.db.models.platform import Entries

    ws.session.expire_all()
    return ws.session.get(Entries, entry.id)


def _fire(ws, event_type: str, document: dict, *, entity=None, entity_type: str | None = None, user_id=None, correlation_id: str = "corr-1"):
    """Dispatch one event to the engine exactly as the reaction listener would build it."""
    ctx = event_context(event_type, document, entity_id=entity, entity_type=entity_type, user_id=user_id, correlation_id=correlation_id)
    ran = run_automations_for_event(ws.session, ws.gid, ctx, recorder=ExecutionRecorder(ws.session, ws.gid))
    ws.session.expire_all()
    return ran


def _entry_doc(entry, **extra) -> dict:
    return {"entry_id": str(entry.id), "entry_title": entry.title, "entry_type": None, "workspace_id": None, **extra}


def _dispatched(monkeypatch):
    """Record the events the engine's item ops send instead of putting them on the bus: [(event_type, entity_id)]."""
    from marvin.services.event_bus_service.event_bus_service import EventBusService

    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(EventBusService, "dispatch", lambda self, **kw: seen.append((kw["event_type"].name, str(kw["entity_id"]))))
    return seen


def _runs(ws, slug: str):
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel

    rows = ws.session.query(AutomationExecutionModel).filter_by(group_id=ws.gid, automation_slug=slug)
    return rows.order_by(AutomationExecutionModel.started_at).all()


def _http(monkeypatch, *, status: int = 200, body: dict | None = None):
    """Mock the webhook step's single httpx call; returns the list of (method, url, json) it saw."""
    calls: list[tuple[str, str, dict]] = []
    payload = body or {"ok": True}

    def request(method, url, **kw):
        calls.append((method, url, kw.get("json")))
        return SimpleNamespace(status_code=status, is_success=200 <= status < 300, text=json.dumps(payload), json=lambda: payload)

    monkeypatch.setattr(httpx, "request", request)
    return calls


# ── Every workflow recipe passes the validator once configured ───────────────
@pytest.mark.parametrize("rid", WORKFLOW_RECIPES)
def test_configured_recipe_passes_draft_issues(ws, rid):
    definition = _configured(ws, rid)
    assert draft_issues(ws.session, ws.gid, definition) == []


# ── The verified recipes run end to end ───────────────────────────────────────
class TestExecution:
    def test_newsletter_delivery(self, ws):
        _install(ws, "newsletter-delivery")
        issue = _entry(ws, "newsletter-issue", "Issue 12", status="published", data={"body": "# Hello", "preview": "The twelfth"})

        _fire(ws, "entry_published", _entry_doc(issue), entity=issue.id, entity_type="entry", user_id=ws.uid)

        (key, args) = ws.providers["buttondown"].calls[0]
        assert key == "create_issue_email"
        assert (args["subject"], args["body"], args["description"], args["entry_id"]) == ("Issue 12", "# Hello", "The twelfth", str(issue.id))
        assert args["email_id"] is None  # nothing recorded yet: the provider creates
        meta = _reload(ws, issue).metadata_json
        assert (meta["buttondown_email_id"], meta["buttondown_issue_delivery"]) == ("em_1", "draft")

        # Replayed (re-published): the recorded id goes back to the provider, which updates instead of creating twice.
        _fire(ws, "entry_published", _entry_doc(issue), entity=issue.id, entity_type="entry")
        assert [a["email_id"] for _, a in ws.providers["buttondown"].calls] == [None, "em_1"]
        assert _reload(ws, issue).metadata_json["buttondown_email_id"] == "em_1"
        assert [r.status for r in _runs(ws, "newsletter-delivery")] == ["success", "success"]

    def test_newsletter_delivery_skips_other_types_and_records_a_provider_failure(self, ws):
        _install(ws, "newsletter-delivery")
        article = _entry(ws, "article", "Not an issue", status="published", data={"body": "x"})
        _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry")
        assert ws.providers["buttondown"].calls == [] and _runs(ws, "newsletter-delivery") == []

        broken = _entry(ws, "newsletter-issue", "Boom", status="published", data={"body": "x", "preview": "y"})
        _fire(ws, "entry_published", _entry_doc(broken), entity=broken.id, entity_type="entry")
        (run,) = _runs(ws, "newsletter-delivery")
        assert run.status == "failed" and "Buttondown is down" in run.error
        assert "buttondown_email_id" not in _reload(ws, broken).metadata_json  # the metadata step never ran

    def test_publication_announcement(self, ws, monkeypatch):
        calls = _http(monkeypatch, status=202, body={"id": 7})
        _install(ws, "publication-announcement")
        article = _entry(ws, "article", "Big news", status="published", data={"body": "x"}, summary="In short")

        _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry", correlation_id="corr-announce")

        [(method, url, body)] = calls
        assert (method, url) == ("POST", "https://community.example/hooks/new-post")
        assert body == {"title": "Big news", "url": f"/articles/{article.slug}", "summary": "In short", "entry_id": str(article.id), "image": None}
        assert _reload(ws, article).metadata_json["announcement"] == {"status_code": 202, "run": "corr-announce"}

    def test_content_refresh(self, ws, monkeypatch):
        calls = _http(monkeypatch)
        _install(ws, "content-refresh")
        live = _entry(ws, "article", "Live", status="published", data={"body": "x"})
        draft = _entry(ws, "article", "Draft", status="draft", data={"body": "x"})

        _fire(ws, "entry_updated", _entry_doc(draft, changed_fields=["title"]), entity=draft.id, entity_type="entry")
        assert calls == []
        _fire(ws, "entry_updated", _entry_doc(live, changed_fields=["title"]), entity=live.id, entity_type="entry")
        [(_, url, body)] = calls
        assert url == "https://search.example/reindex"
        assert body == {"entry_id": str(live.id), "slug": live.slug, "url": f"/articles/{live.slug}", "title": "Live", "changed_fields": ["title"]}

    def test_client_handoff(self, ws, monkeypatch):
        calls = _http(monkeypatch, body={"id": "rcpt_9"})
        _install(ws, "client-handoff")
        ready = _entry(ws, "article", "Deliverable", status="approved", data={"body": "final"})

        transition = _entry_doc(ready, changed_fields=["status"], before={"status": "draft"}, after={"status": "approved"})
        _fire(ws, "entry_updated", transition, entity=ready.id, entity_type="entry", correlation_id="corr-handoff")
        [(_, url, body)] = calls
        assert url == "https://client.example/intake" and body["data"] == {"body": "final"} and body["status"] == "approved"
        assert _reload(ws, ready).metadata_json["handoff"] == {"status_code": 200, "receipt": {"id": "rcpt_9"}, "run": "corr-handoff"}

        # A save that doesn't move the status to approved is not a handoff.
        _fire(ws, "entry_updated", _entry_doc(ready, changed_fields=["title"]), entity=ready.id, entity_type="entry")
        assert len(calls) == 1

    def test_editorial_approval_gate(self, ws):
        _install(ws, "editorial-approval-gate")
        complete = _entry(ws, "article", "Complete", status="approved", data={"body": "all there"})
        incomplete = _entry(ws, "article", "Incomplete", status="approved", data={})
        approved = lambda e: _entry_doc(e, changed_fields=["status"], before={"status": "needs_review"}, after={"status": "approved"})  # noqa: E731

        _fire(ws, "entry_updated", approved(complete), entity=complete.id, entity_type="entry")
        assert _reload(ws, complete).status == "published"

        _fire(ws, "entry_updated", approved(incomplete), entity=incomplete.id, entity_type="entry")
        held = _reload(ws, incomplete)
        assert held.status == "needs_review"
        (reason,) = held.metadata_json["review_reasons"]
        assert reason.startswith("Publish refused by the approval gate: entry publish refused:") and "body" in reason.lower()
        runs = {r.status for r in _runs(ws, "editorial-approval-gate")}
        assert runs == {"success", "failed"}

    def test_publication_ledger(self, ws):
        _install(ws, "publication-ledger")
        article = _entry(ws, "article", "Ledgered", status="published", data={"body": "x"})

        _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry", user_id=ws.uid, correlation_id="corr-ledger")

        assert _reload(ws, article).metadata_json["publication_ledger"] == {
            "event": "entry_published",
            "run": "corr-ledger",
            "published_by": str(ws.uid),  # a UUID in the context, stored as JSON text
            "url": f"/articles/{article.slug}",
            "slug": article.slug,
        }

    def test_utm_librarian(self, ws):
        definition = _install(ws, "utm-librarian").definition
        link = definition["actions"][0]["metadata"]["utm"]["link"]
        assert link == "${entry.url}?utm_source=${entry.data.utm_source}&utm_medium=${entry.data.utm_medium}&utm_campaign=${entry.slug}"
        campaign = _entry(ws, "campaign", "Spring launch", data={"utm_source": "newsletter", "utm_medium": "email"})

        _fire(ws, "entry_created", _entry_doc(campaign), entity=campaign.id, entity_type="entry")

        assert _reload(ws, campaign).metadata_json["utm"] == {
            "source": "newsletter",
            "medium": "email",
            "campaign": campaign.slug,
            "link": f"/campaigns/{campaign.slug}?utm_source=newsletter&utm_medium=email&utm_campaign={campaign.slug}",
        }

    def test_form_intake_desk(self, ws):
        _install(ws, "form-intake-desk")
        data = {"email": "ada@example.com", "message": "Can you engrave brass?"}
        request = _entry(ws, "contact-request", "Ada Lovelace", status="inbox", data=data)
        submission = _entry_doc(request, form_name="Contact", flagged=False, duplicate=False, submission_data=request.data_json)

        _fire(ws, "form_submission_received", submission, entity=request.id, entity_type="entry", correlation_id="corr-intake")

        triaged = _reload(ws, request)
        assert triaged.status == "needs_review"
        assert triaged.metadata_json["intake"] == {"form": "Contact", "flagged": False, "duplicate": False, "run": "corr-intake"}
        assert triaged.metadata_json["review_reasons"] == ["New Contact submission awaiting triage"]
        (notice,) = ws.providers["apprise"].calls
        assert notice == {"title": "New submission: Ada Lovelace", "body": "Contact — Can you engrave brass?"}

    def test_blocked_publication_rescue(self, ws):
        _install(ws, "blocked-publication-rescue")
        waiting = _entry(ws, "article", "October issue", status="draft", data={})
        issue = "Required field 'Body' is empty."
        blocked = _entry_doc(waiting, waiting_for="requirements", reason=issue, issues=[issue])

        _fire(ws, "entry_scheduled_publish_blocked", blocked, entity=waiting.id, entity_type="entry")

        held = _reload(ws, waiting)
        assert held.status == "needs_review"
        assert held.metadata_json["review_reasons"] == ["Scheduled publish is waiting (requirements): Required field 'Body' is empty."]
        (notice,) = ws.providers["apprise"].calls
        assert notice["title"] == "Scheduled publish is waiting: October issue"
        assert notice["body"] == f"Required field 'Body' is empty.\nFix it here: /articles/{waiting.slug}"

    def test_submission_surge_alert(self, ws):
        _install(ws, "submission-surge-alert")
        surge = {"form_id": str(ws.types["contact-request"]), "form_name": "Contact", "submission_count": 50, "threshold": 50, "window_minutes": 10}

        _fire(ws, "submission_surge_detected", surge, entity=ws.types["contact-request"], entity_type="entry_type")

        (notice,) = ws.providers["apprise"].calls
        assert notice["title"] == "Submission surge: Contact"
        assert notice["body"].startswith("50 submissions in 10 minutes (threshold 50).")

    def test_deployment_failure_desk(self, ws):
        _install(ws, "deployment-failure-desk")
        failed = {"status": "failed", "error_message": "Build timeout", "deployment_id": "dep_1", "site_url": "https://example.com"}

        _fire(ws, "site_deployment_failed", failed)

        (notice,) = ws.providers["apprise"].calls
        assert notice == {"title": "Site deployment failed", "body": "Build timeout\nDeployment: dep_1\nSite: https://example.com"}

    def test_deployment_celebration(self, ws):
        _install(ws, "deployment-celebration")

        _fire(ws, "site_deployment_completed", {"status": "completed", "deployment_id": "dep_2", "site_url": "https://example.com"})

        (notice,) = ws.providers["apprise"].calls
        assert notice == {"title": "Site deployed", "body": "https://example.com is live (deployment dep_2)."}

    def test_failure_repair_desk(self, ws):
        _install(ws, "failure-repair-desk")
        victim = _entry(ws, "article", "Stuck", status="published", data={"body": "x"})
        failure = {
            "automation_id": str(uuid.uuid4()),
            "automation_slug": "newsletter-delivery",
            "ok": False,
            "error": "buttondown.create_issue_email failed: Buttondown is down",
            "trigger_entity_type": "entry",
            "trigger_entity_id": str(victim.id),
            "handled": False,
        }

        _fire(ws, "automation_failed", failure, entity=uuid.UUID(failure["automation_id"]), entity_type="automation")
        repaired = _reload(ws, victim)
        assert repaired.status == "needs_review"
        assert repaired.metadata_json["review_reasons"] == [f"Workflow newsletter-delivery failed: {failure['error']}"]

        # A failure the integration's error policy already handled, or one that wasn't about an entry, is left alone.
        other = _entry(ws, "article", "Fine", status="published", data={"body": "x"})
        handled = {**failure, "trigger_entity_id": str(other.id), "handled": True}
        not_an_entry = {**failure, "trigger_entity_type": "incoming_webhook", "trigger_entity_id": str(uuid.uuid4())}
        for doc in (handled, not_an_entry):
            _fire(ws, "automation_failed", doc, entity=uuid.uuid4(), entity_type="automation")
        assert _reload(ws, other).status == "published"
        assert len(_runs(ws, "failure-repair-desk")) == 1

    def test_failure_repair_desk_reacts_to_a_real_failed_run(self, ws):
        """End to end through the event bus: the newsletter workflow fails on a provider error, its
        automation_failed event reaches the on_error workflow, and the entry lands in review."""
        _install(ws, "newsletter-delivery")
        _install(ws, "failure-repair-desk")
        broken = _entry(ws, "newsletter-issue", "Boom", status="published", data={"body": "x", "preview": "y"})

        _fire(ws, "entry_published", _entry_doc(broken), entity=broken.id, entity_type="entry")

        held = _reload(ws, broken)
        assert held.status == "needs_review"
        error = "buttondown.create_issue_email failed: Buttondown is down"
        assert held.metadata_json["review_reasons"] == [f"Workflow newsletter-delivery failed: {error}"]

    def test_collection_welcome_mat(self, ws):
        _install(ws, "collection-welcome-mat")
        bare = _entry(ws, "article", "No summary yet", status="draft", data={"body": "A long body."})
        told = _entry(ws, "article", "Summarised", status="draft", data={"body": "x"}, summary="Already has one")
        ws.ai.reply_text(json.dumps({"summary": "A short body.", "word_count": 3}))
        added = lambda e: _entry_doc(e, collection_id=str(uuid.uuid4()), collection_name="Featured")  # noqa: E731

        _fire(ws, "entry_added_to_collection", added(told), entity=told.id, entity_type="entry")
        assert ws.ai.requests == []  # a summarised entry costs nothing

        _fire(ws, "entry_added_to_collection", added(bare), entity=bare.id, entity_type="entry")
        assert len(ws.ai.requests) == 1
        assert _reload(ws, bare).summary == "A short body."  # allow-draft-update applies to a draft
        (run,) = _runs(ws, "collection-welcome-mat")
        assert run.status == "success" and run.actions[0].output_snapshot["_write_back"] == "applied"

        _fire(ws, "entry_added_to_collection", {**added(bare), "collection_name": "Archive"}, entity=bare.id, entity_type="entry")
        assert len(ws.ai.requests) == 1  # another collection is not the welcome mat's

    def test_seo_assistant(self, ws):
        _install(ws, "seo-assistant")
        reviewed = _entry(ws, "article", "Brass engraving", status="needs_review", data={"body": "How we engrave brass."})
        ws.ai.reply_text(json.dumps({"summary": "Engraving brass, step by step.", "word_count": 5}))
        ws.ai.reply_text(json.dumps({"tags": ["brass", "engraving"]}))
        sent = _entry_doc(reviewed, changed_fields=["status"], before={"status": "draft"}, after={"status": "needs_review"})

        _fire(ws, "entry_updated", sent, entity=reviewed.id, entity_type="entry")

        assert len(ws.ai.requests) == 2
        (run,) = _runs(ws, "seo-assistant")
        assert run.status == "success" and [a.output_snapshot["_write_back"] for a in run.actions] == ["staged", "staged"]
        entry = _reload(ws, reviewed)
        assert entry.summary is None and entry.suggestion_json["summary"] == "Engraving brass, step by step."  # proposed, not applied: mid-review
        assert entry.suggestion_json["tags"] == ["brass", "engraving"]

        _fire(ws, "entry_updated", _entry_doc(reviewed, changed_fields=["title"]), entity=reviewed.id, entity_type="entry")
        assert len(ws.ai.requests) == 2  # a plain save in review doesn't spend again

    def test_editorial_task_maker(self, ws):
        _install(ws, "editorial-task-maker")
        article = _entry(ws, "article", "Launch post", status="published", data={"body": "x"})

        _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry")

        (call,) = ws.providers["n8n"].calls
        assert call["path"] == "editorial-tasks" and call["entry_id"] == str(article.id)
        assert call["data"]["tasks"] == ['Reply to comments on "Launch post"', 'Follow up on "Launch post" in a week']
        assert _reload(ws, article).metadata_json["editorial_tasks"] == {"execution_id": "ex_1", "status_code": 200}

    def test_comment_discussion_starter(self, ws, monkeypatch):
        calls = _http(monkeypatch, body={"id": 42, "topic_url": "https://forum.example/t/42"})
        definition = _install(ws, "comment-discussion-starter").definition
        assert definition["actions"][1]["metadata"]["discussion_url"] == "${steps.discussion.output.body.topic_url}"
        article = _entry(ws, "article", "Discuss me", status="published", data={"body": "x"}, summary="A summary")

        _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry")

        [(_, url, body)] = calls
        assert url == "https://forum.example/posts.json" and body["title"] == "Discuss me" and body["raw"] == f"A summary\n\n/articles/{article.slug}"
        assert _reload(ws, article).metadata_json["discussion_url"] == "https://forum.example/t/42"

    def test_unpublish_entries_with_images(self, ws):
        from marvin.db.models.platform import Assets, EntryAssets

        row = _install(ws, "unpublish-entries-with-images")
        pictured = _entry(ws, "article", "With a photo", status="published", data={"body": "x"})
        plain = _entry(ws, "article", "Words only", status="published", data={"body": "x"})
        draft = _entry(ws, "article", "Draft with photo", status="draft", data={"body": "x"})
        for i, owner in enumerate((pictured, draft)):
            photo = Assets(
                session=ws.session, group_id=ws.gid, slug=f"p{i}-{ws.gid.hex[:6]}", name="P", original_filename="p.png", filename="p.png",
                extension="png", file_size=1, mime_type="image/png", asset_type="image", checksum=uuid.uuid4().hex,
                storage_provider="local", storage_key=f"p{i}.png", uploaded_by=ws.uid,
            )  # fmt: skip
            ws.session.add(photo)
            ws.session.flush()
            ws.session.add(EntryAssets(entry_id=owner.id, asset_id=photo.id, position=0))
        ws.session.commit()

        result = run_automation_now(ws.session, ws.gid, row, recorder=ExecutionRecorder(ws.session, ws.gid))

        assert (result["ok"], result["ran"]) == (True, 1)
        assert (_reload(ws, pictured).status, _reload(ws, plain).status, _reload(ws, draft).status) == ("draft", "published", "draft")
        (run,) = _runs(ws, "unpublish-entries-with-images")
        assert (run.targets_matched, run.targets_run, run.status) == (1, 1, "success")
        ws.session.query(EntryAssets).filter(EntryAssets.entry_id.in_([pictured.id, draft.id])).delete(synchronize_session=False)
        ws.session.query(Assets).filter(Assets.group_id == ws.gid).delete(synchronize_session=False)
        ws.session.commit()

    def test_trash_unattached_images(self, ws, monkeypatch):
        from marvin.db.models.platform import Assets, EntryAssets

        sent = _dispatched(monkeypatch)
        row = _install(ws, "trash-unattached-images")
        loose = _asset(ws, "loose")
        used = _asset(ws, "used")
        svg = _asset(ws, "logo", asset_type="svg", mime="image/svg+xml")
        binned = _asset(ws, "binned", trashed=True)
        page = _entry(ws, "article", "Page", data={"body": "x"})
        ws.session.add(EntryAssets(entry_id=page.id, asset_id=used.id, position=0))
        ws.session.commit()

        result = run_automation_now(ws.session, ws.gid, row, recorder=ExecutionRecorder(ws.session, ws.gid))

        assert (result["ok"], result["ran"]) == (True, 1)
        trashed = {a.name for a in ws.session.query(Assets).filter(Assets.group_id == ws.gid, Assets.trashed_at.isnot(None))}
        assert trashed == {"loose", "binned"}  # the used image and the svg stay
        assert ("asset_trashed", str(loose.id)) in sent and ("asset_trashed", str(binned.id)) not in sent
        assert run_automation_now(ws.session, ws.gid, row)["ran"] == 0  # nothing unattached is left outside the Trash
        del svg
        ws.session.query(EntryAssets).filter(EntryAssets.entry_id == page.id).delete(synchronize_session=False)
        ws.session.query(Assets).filter(Assets.group_id == ws.gid).delete(synchronize_session=False)
        ws.session.commit()

    def test_restore_trashed_resources(self, ws, monkeypatch):
        from marvin.db.models.platform import Resources

        sent = _dispatched(monkeypatch)
        row = _install(ws, "restore-trashed-resources")
        gone = _resource(ws, "gone", trashed=True)
        kept = _resource(ws, "kept")
        ws.session.commit()

        result = run_automation_now(ws.session, ws.gid, row, recorder=ExecutionRecorder(ws.session, ws.gid))

        assert (result["ok"], result["ran"]) == (True, 1)
        ws.session.expire_all()
        assert gone.trashed_at is None and kept.trashed_at is None
        assert [e for e in sent if e[0].startswith("resource_")] == [("resource_restored", str(gone.id))]
        ws.session.query(Resources).filter(Resources.group_id == ws.gid).delete(synchronize_session=False)
        ws.session.commit()

    def test_asset_upload_announcement(self, ws, monkeypatch):
        from marvin.db.models.platform import Assets

        calls = _http(monkeypatch)
        _install(ws, "asset-upload-announcement")
        photo = _asset(ws, "harbour", mime="image/jpeg")
        ws.session.commit()
        monkeypatch.setattr("marvin.services.storage.provider_factory.asset_public_url", lambda a: f"https://cdn.example/{a.slug}")

        _fire(ws, "asset_uploaded", {"asset_id": str(photo.id)}, entity=photo.id, entity_type="asset")

        [(method, url, body)] = calls
        assert (method, url) == ("POST", "https://chat.example/hooks/uploads")
        assert body == {"text": f"New image uploaded: harbour (image/jpeg) https://cdn.example/{photo.slug}"}
        assert [r.status for r in _runs(ws, "asset-upload-announcement")] == ["success"]
        ws.session.query(Assets).filter(Assets.group_id == ws.gid).delete(synchronize_session=False)
        ws.session.commit()

    def test_summarise_and_feature_on_publish(self, ws):
        from marvin.db.models.platform.entry_collections import EntryCollections

        _install(ws, "summarise-and-feature-on-publish")
        article = _entry(ws, "article", "Featured piece", status="published", data={"body": "A body worth featuring."})
        ws.ai.reply_text(json.dumps({"summary": "Worth featuring.", "word_count": 2}))

        _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry")

        assert len(ws.ai.requests) == 1
        entry = _reload(ws, article)
        assert entry.summary is None and entry.suggestion_json["summary"] == "Worth featuring."  # published: staged, not applied
        assert ws.session.query(EntryCollections).filter_by(entry_id=article.id).count() == 1
        (run,) = _runs(ws, "summarise-and-feature-on-publish")
        assert run.status == "success" and run.actions[0].output_snapshot["_write_back"] == "staged"

    def test_hourly_site_rebuild(self, ws, monkeypatch):
        from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
        from marvin.services.automation.workflows import sync_schedule
        from marvin.services.scheduled_tasks.handlers import TaskHandlerRegistry

        row = _install(ws, "hourly-site-rebuild")
        assert row.definition["trigger"]["schedule_config"] == {"interval_seconds": 3600}  # typed: an integer, not "3600"
        sync_schedule(ws.session, ws.gid, row)  # what create_workflow does: the backing scheduled task
        task = ws.session.query(ScheduledTaskModel).filter_by(group_id=ws.gid, slug=f"wf-{row.id}").one()
        assert (task.task_type, task.task_config) == ("run_automation", {"automation_id": str(row.id)})
        assert task.schedule_config == {"interval_seconds": 3600}
        requested: list[dict] = []
        real = TaskHandlerRegistry.get_handler
        fake = SimpleNamespace(execute=lambda task, bus: requested.append(task.task_config) or "queued")
        monkeypatch.setattr(TaskHandlerRegistry, "get_handler", lambda t: fake if t == "request_site_rebuild" else real(t))

        result = run_automation_now(ws.session, ws.gid, row, recorder=ExecutionRecorder(ws.session, ws.gid), trigger_kind="schedule")

        assert result["ok"] and requested == [{"reason": "scheduled rebuild"}]
        ws.session.delete(task)
        ws.session.commit()

    def test_archive_entry_from_webhook(self, ws):
        _install(ws, "archive-entry-from-webhook")
        target = _entry(ws, "article", "Retire me", status="published", data={"body": "x"})
        hook = {"webhook_id": str(uuid.uuid4()), "webhook_slug": "archive-requests", "webhook_name": "Archive requests"}
        call = lambda slug: {**hook, "payload": {"slug": slug}}  # noqa: E731

        _fire(ws, "incoming_webhook", call(target.slug), entity=uuid.uuid4(), entity_type="incoming_webhook")
        assert _reload(ws, target).status == "archived"

        _fire(ws, "incoming_webhook", call("no-such-entry"), entity=uuid.uuid4(), entity_type="incoming_webhook")
        runs = _runs(ws, "archive-entry-from-webhook")
        assert [r.status for r in runs] == ["success", "failed"] and "no entry with slug 'no-such-entry'" in runs[1].error


# ── The authoring guide and draft_workflow read the same store ───────────────
def _ctx(ws):
    member = SimpleNamespace(group_id=ws.gid, workspace_role="ADMIN")
    user = SimpleNamespace(id=ws.uid, admin=True, workspace_memberships=[member])
    return SimpleNamespace(session=ws.session, group_id=ws.gid, user=user, provider=None, logger=None)


def _tool(ws, name, args) -> dict:
    return json.loads(get_tool(name).handler(_ctx(ws), args))


def test_guide_offers_the_recipes_this_workspace_can_run(ws):
    from marvin.db.models.groups.integrations import IntegrationModel

    refs = workspace_refs(ws.session, ws.gid)
    offered = {r["id"] for r in recipes.offered(refs)}
    assert offered == set(WORKFLOW_RECIPES)  # the fixture has every connection and AI on

    section = authoring_guide(ws.session, ws.gid, "examples")
    assert sorted(r["recipe"] for r in section["examples"]["recipes"]) == WORKFLOW_RECIPES and guide_size(section) < 16_000
    one = authoring_guide(ws.session, ws.gid, "examples", "newsletter-delivery")["examples"]["newsletter-delivery"]
    assert one["definition"] == recipes.load_recipe("newsletter-delivery")["definition"] and "newsletter_integration" in one["setup_variables"]
    assert "{{" in json.dumps(one["definition"]) and "${entry.title}" in json.dumps(one["definition"])
    overview = authoring_guide(ws.session, ws.gid)["examples"]
    assert sorted(overview["available"]) == WORKFLOW_RECIPES and overview["available"][0] in overview

    # Disconnect Buttondown: the newsletter recipe is no longer offered, and asking for it says why.
    ws.session.query(IntegrationModel).filter_by(group_id=ws.gid, slug="newsletter").update({"enabled": False})
    ws.session.commit()
    refs = workspace_refs(ws.session, ws.gid)
    assert "newsletter-delivery" not in {r["id"] for r in recipes.offered(refs)}
    assert recipes.missing_prerequisites(recipes.entry("newsletter-delivery"), refs) == ["needs a connected buttondown integration"]
    asked = authoring_guide(ws.session, ws.gid, "examples", "newsletter-delivery")["examples"]
    assert "buttondown" in asked["error"] and "publication-ledger" in asked["available"]
    assert "no such recipe" in authoring_guide(ws.session, ws.gid, "examples", "nope")["examples"]["error"]
    # An idea is never offered, however the workspace is set up.
    assert "status is needs-engine-capability" in authoring_guide(ws.session, ws.gid, "examples", "weekly-digest")["examples"]["error"]


def test_draft_workflow_instantiates_a_recipe_with_typed_vars(ws):
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    values = {k: ws.values[k] for k in placeholders(recipes.load_recipe("newsletter-delivery"))}
    out = _tool(ws, "draft_workflow", {"recipe": "newsletter-delivery", "vars": values})
    assert out.get("created") is True, out
    row = ws.session.query(WorkspaceAutomationModel).filter_by(group_id=ws.gid, slug=out["workflow"]["slug"]).one()
    assert (row.name, row.enabled) == ("Newsletter delivery", False)
    assert row.definition == _configured(ws, "newsletter-delivery")
    assert (row.source_recipe, row.source_recipe_version) == ("newsletter-delivery", recipes.recipe_version("newsletter-delivery"))

    # A missing or mistyped value is refused with the recipe's variables, and nothing is saved.
    out = _tool(ws, "draft_workflow", {"recipe": "hourly-site-rebuild", "vars": {"interval_seconds": "3600"}})
    assert "must be a integer" in out["error"] and "interval_seconds" in out["setup_variables"]
    out = _tool(ws, "draft_workflow", {"recipe": "newsletter-delivery", "vars": {}})
    assert "missing setup value" in out["error"]
    out = _tool(ws, "draft_workflow", {"recipe": "weekly-digest", "vars": {}})
    assert "not runnable" in out["error"] and "publication-ledger" in out["available"]
    out = _tool(ws, "draft_workflow", {"name": "x"})
    assert "Pass a definition, or a recipe" in out["error"]
    assert ws.session.query(WorkspaceAutomationModel).filter_by(group_id=ws.gid).count() == 1
    shown = _tool(ws, "workflow_authoring_guide", {"recipe": "hourly-site-rebuild"})["examples"]["hourly-site-rebuild"]
    assert shown["setup_variables"]["interval_seconds"]["type"] == "integer"


# ── Recipes that aren't runnable say so ──────────────────────────────────────
def test_needs_and_concept_recipes_ship_no_runnable_json():
    for r in CATALOGUE["recipes"]:
        if r["status"] in RUNNABLE:
            continue
        assert r["runnable"] is False and r["shape"] == "idea" and r.get("recipe") is None, r["id"]
        assert not (RECIPES_DIR / f"{r['id']}.json").exists(), r["id"]
