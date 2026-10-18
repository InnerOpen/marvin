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

import base64
import io
import json
import pathlib
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image, ImageFilter
from pytest import fixture

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

from marvin_integration_sdk import INTEGRATION_REGISTRY, IntegrationProvider, ProviderAction  # noqa: E402
from marvin_integration_sdk.ai.fake import FakeAIProvider, ScriptedTransport  # noqa: E402

from marvin.services.ai.media import render  # noqa: E402
from marvin.services.ai.tools import get_tool  # noqa: E402
from marvin.services.automation import recipes  # noqa: E402
from marvin.services.automation.authoring import authoring_guide, draft_issues, guide_size, parse_workflow, workspace_refs  # noqa: E402
from marvin.services.automation.context import event_context  # noqa: E402
from marvin.services.automation.engine import run_automation_now, run_automations_for_event  # noqa: E402
from marvin.services.automation.library import RecipeConfigError, configure, placeholders, unresolved  # noqa: E402
from marvin.services.automation.recorder import ExecutionRecorder  # noqa: E402
from tests.test_workflow_fetch import _web  # noqa: E402
from tests.test_workflow_item_targets import _asset, _resource  # noqa: E402
from tests.test_workflow_media_documents import _Vision, pdf  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "docs" / "workflow-library"
RECIPES_DIR = recipes.DIR
CATALOGUE = recipes.catalogue()
BY_ID = {r["id"]: r for r in CATALOGUE["recipes"]}
STATUSES = ("verified-current", "supported-after-configuration", "needs-adapter", "needs-engine-capability", "concept")
RUNNABLE = {"verified-current", "supported-after-configuration"}
WORKFLOW_RECIPES = sorted(r["id"] for r in CATALOGUE["recipes"] if r["shape"] == "workflow")
VERIFIED = sorted(r["id"] for r in CATALOGUE["recipes"] if r["status"] == "verified-current")
needs_browser = pytest.mark.skipif(render.browser_path() is None, reason="no headless Chromium (chromium-headless-shell) here")


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
    tally = {s: sum(1 for r in CATALOGUE["recipes"] if r["status"] == s) for s in CATALOGUE["counts"]}
    assert CATALOGUE["counts"] == tally and sum(tally.values()) == len(CATALOGUE["recipes"]), "counts follow the recipes' statuses"
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


class _Images(IntegrationProvider):
    """OpenAI Images' shape (v0.3.0): paid actions, asked for approval, returning base64 pictures and the model used —
    generate makes new ones; edit changes the picture it's given (image_b64, from the step's source)."""

    slug = "openai_images"
    name = "OpenAI Images (fake)"
    actions = (
        ProviderAction(key="generate", label="Generate image", capability="image.generate", requires_approval=True),
        ProviderAction(key="edit", label="Edit an image", capability="image.edit", requires_approval=True),
    )

    def __init__(self):
        self.calls: list[dict] = []

    def run_action(self, key, args, ctx):
        self.calls.append(dict(args))
        if key == "edit":
            return {"image_b64": base64.b64encode(_picture((600, 600), color=(240, 240, 240))).decode(), "usage": {"model": "gpt-image-1"}}
        return {"images": [{"image_b64": base64.b64encode(_picture((900, 600))).decode()}], "usage": {"model": "gpt-image-1"}}


def _picture(size=(1600, 1200), color=(180, 90, 40), fmt="PNG") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format=fmt)
    return out.getvalue()


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

    providers = {"buttondown": _Buttondown(), "apprise": _Apprise(), "n8n": _N8n(), "openai_images": _Images()}
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
        "article": ([_field("body", "markdown", required=True), _field("project")], "/articles/{slug}", None),
        "campaign": ([_field("utm_source"), _field("utm_medium")], "/campaigns/{slug}", None),
        "contact-request": ([_field("email"), _field("message", "textarea")], None, {"submittable": True}),
        "project": ([_field("stage"), _field("collaborators")], None, None),
        "person": ([_field("handle"), _field("ok_to_tag", "boolean"), _field("role")], None, None),
        "rsvp": ([_field("event"), _field("email")], None, None),
        "event": ([_field("date", "date")], None, None),
    }
    for slug, (fields, pattern, caps) in specs.items():
        et = EntryTypes(session=db_session, group_id=gid, name=slug.replace("-", " ").title(), slug=slug, schema_json={"fields": fields})
        et.id = uuid.uuid4()
        et.page_url_pattern = pattern
        et.capabilities_json = caps
        db_session.add(et)
        types[slug] = et.id
    db_session.add(Collections(session=db_session, group_id=gid, name="Featured", slug="featured"))
    for slug, provider in (("newsletter", "buttondown"), ("alerts", "apprise"), ("automation-hub", "n8n"), ("openai-images", "openai_images")):
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
    # The workspace's own `custom.milestone` event (Achievement cabinet starts on it).
    from marvin.schemas.group.custom_events import CustomEventDefinition
    from marvin.services.events import custom_events

    custom_events.save(
        db_session,
        gid,
        CustomEventDefinition(name="milestone", title="Milestone reached", fields=[{"key": "milestone"}, {"key": "badge"}]),
    )

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
        "image_context": "Photos of finished artwork",
        "credit_key": "credit",
        "license_key": "license",
        "credit_metadata_key": "image_credit",
        "voice": "a weary robot",
        "note_key": "resource_note",
        "caption_style": "warm and plain",
        "draft_entry_type": "newsletter-issue",
        "update_entry_type": "article",
        "viewpoints": "a hopeful maker, a sceptical accountant",
        "language": "Spanish",
        "collection_purpose": "our best pieces",
        "notes_entry_type": "newsletter-issue",
        "task_entry_type": "article",
        "image_role": "hero",
        "quality": 82,
        "min_width": 1200,
        "min_sharpness": 60,
        "tag": "brand",
        "preset": "warm",
        "image_integration": "openai-images",
        "style": "a 1950s sci-fi pulp",
        "project_type": "project",
        "status_field": "stage",
        "done_value": "complete",
        "image_style": "A bright, hand-drawn poster",
        "attribution": "Grace Martin Franklin",
        "studio_name": "Mash & Burn Co.",
        "year_label": "MMXXVI",
        "card_series": "Workshop series",
        "newspaper_name": "The Raleigh Ledger",
        "footer": "A Mash & Burn tale",
        "compare_tag": "compare",
        "timezone": "America/New_York",
        "newsletter_body_field": "body",
        "since": "-14d",
        "title": "Brand board",
        "index_slug": "series-index",
        "log_entry_type": "article",
        "project_field": "project",
        "report_entry_type": "newsletter-issue",
        "report_body_field": "body",
        "draft_body_field": "body",
        "resource_type": "supplier",
        "unavailable_text": "sold out",
        "notes_body_field": "body",
        "remixes": ["a haiku", "a limerick"],
        "document_role": "download",
        "preview_role": "preview",
        "cover_role": "cover",
        "find": ["face", "plate"],
        "kicker": "Workshop field guide",
        "scene": "a sunlit oak workbench",
        "season": "winter holidays",
        "season_tag": "winter",
        "watermark_text": "© Mash & Burn Co.",
        "position": "bottom-right",
        "event_entry_type": "event",
        "event_date": "data.date",
        "remind_at": "09:00",
        "mastodon_server": "mastodon.social",
        "card_title": "On this day, a year ago",
        "signup_type": "contact-request",
        "audience_name": "subscribers",
        "people_field": "collaborators",
        "person_type": "person",
        "consent_field": "ok_to_tag",
        "handle_field": "handle",
        "role_field": "role",
        "rsvp_type": "rsvp",
        "rsvp_event_field": "event",
        "send_at": "10:00",
        "start_here_collection": "featured",
        "badge_entry_type": "article",
        "badge_body_field": "body",
        "cabinet_collection": "featured",
        "network": "Bluesky",
        "post_type": "article",
        "max_length": 300,
        "orientation": "landscape",
        "post_length": 300,
        "launch_entry_type": "event",
        "launch_date": "data.date",
        "post_at": "09:00",
        "product_type": "article",
        "open_after": "26w",
        "queues": "commissions, orders, press, other",
        "document_url_field": "message",
        "capability_schema": {
            "type": "object",
            "required": ["name", "url", "capabilities"],
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "url": {"type": "string", "pattern": "^https://"},
                "capabilities": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            },
        },
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


def _install_workflow(ws, slug: str, trigger: str, actions: list[dict], when: list[dict] | None = None):
    """A hand-written workflow in the fixture workspace (a sender for a recipe's event)."""
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    row = WorkspaceAutomationModel(
        session=ws.session,
        group_id=ws.gid,
        name=slug,
        slug=slug,
        enabled=True,
        definition={"trigger": {"type": "event", "event": trigger}, "conditions": when or [], "actions": actions},
    )
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


def _day_in(ws, days: int) -> str:
    """A date `days` from today in the workspace's own calendar (New York by default) — the one date-based waits
    ("the day after the event, 09:00") read. Between 00:00 and 04:00 UTC the UTC date is already tomorrow, and a
    date taken from it put a resume an hour before its wait was due (CI, 2026-10-14 00:30 UTC)."""
    from marvin.services.automation import waits

    return (datetime.now(waits.workspace_zone(ws.session, ws.gid)).date() + timedelta(days=days)).isoformat()


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

    rows = ws.session.query(AutomationExecutionModel).filter_by(group_id=ws.gid, automation_slug=slug).all()
    # Two runs can start in the same tick: one resumed from another (retry_of) comes after it, whatever the clock says.
    return sorted(rows, key=lambda r: (r.started_at, r.retry_of_id is not None))


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

    def test_alt_text_assistant(self, ws, monkeypatch):
        from marvin.db.models.platform import Assets

        _install(ws, "alt-text-assistant")
        photo = _asset(ws, "harbour", mime="image/jpeg")
        described = _asset(ws, "pier", mime="image/jpeg", alt_text="A pier at dusk")
        manual = _asset(ws, "manual", asset_type="document", mime="application/pdf")
        ws.session.commit()
        monkeypatch.setattr(
            "marvin.services.storage.provider_factory.provider_for",
            lambda name: SimpleNamespace(get=lambda key: __import__("io").BytesIO(b"\xff\xd8jpeg")),
        )
        ws.ai.reply_text(json.dumps({"alt_text": "Fishing boats moored in a harbour", "description": "Boats at rest."}))

        for asset in (photo, described, manual):
            _fire(ws, "asset_uploaded", {"asset_id": str(asset.id)}, entity=asset.id, entity_type="asset")

        (request,) = ws.ai.requests  # only the image without alt text costs a call
        assert "image" in json.dumps(request, default=str).lower() and "Photos of finished artwork" in json.dumps(request, default=str)
        assert ws.session.get(Assets, photo.id).alt_text == "Fishing boats moored in a harbour"  # draft-update mode: applied
        assert ws.session.get(Assets, described.id).alt_text == "A pier at dusk"
        (run,) = _runs(ws, "alt-text-assistant")
        assert run.status == "success" and run.actions[0].output_snapshot["_write_back"] == "applied"
        ws.session.query(Assets).filter(Assets.group_id == ws.gid).delete(synchronize_session=False)
        ws.session.commit()

    def test_alt_text_assistant_stages_in_review_mode(self, ws, monkeypatch):
        from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
        from marvin.db.models.platform import Assets

        ws.session.query(WorkspaceAISettingsModel).filter_by(group_id=ws.gid).update({"approval_mode": "require-approval"})
        _install(ws, "alt-text-assistant")
        photo = _asset(ws, "harbour", mime="image/jpeg")
        ws.session.commit()
        monkeypatch.setattr(
            "marvin.services.storage.provider_factory.provider_for",
            lambda name: SimpleNamespace(get=lambda key: __import__("io").BytesIO(b"\xff\xd8jpeg")),
        )
        ws.ai.reply_text(json.dumps({"alt_text": "Fishing boats"}))

        _fire(ws, "asset_uploaded", {"asset_id": str(photo.id)}, entity=photo.id, entity_type="asset")

        row = ws.session.get(Assets, photo.id)
        assert row.alt_text is None and row.suggestion_json["alt_text"] == "Fishing boats"  # a person accepts it
        ws.session.query(Assets).filter(Assets.group_id == ws.gid).delete(synchronize_session=False)
        ws.session.commit()

    def test_attribution_companion(self, ws):
        from marvin.db.models.platform import Assets

        _install(ws, "attribution-companion")
        article = _entry(ws, "article", "Harbour at dawn", data={"body": "x"})
        credited = _asset(ws, "harbour", mime="image/jpeg", metadata_json={"credit": "Ada Lovelace", "license": "CC BY 4.0"})
        anonymous = _asset(ws, "pier", mime="image/jpeg")
        ws.session.commit()

        _fire(ws, "asset_attached_to_entry", _entry_doc(article, asset_id=str(anonymous.id)), entity=article.id, entity_type="entry")
        assert "image_credit" not in (_reload(ws, article).metadata_json or {})  # no credit to record
        _fire(ws, "asset_attached_to_entry", _entry_doc(article, asset_id=str(credited.id)), entity=article.id, entity_type="entry")

        assert _reload(ws, article).metadata_json["image_credit"] == "Ada Lovelace (CC BY 4.0)"
        assert [r.status for r in _runs(ws, "attribution-companion")] == ["success"]
        ws.session.query(Assets).filter(Assets.group_id == ws.gid).delete(synchronize_session=False)
        ws.session.commit()

    # ── custom AI steps (op: "custom") ──
    def test_community_question(self, ws, monkeypatch):
        calls = _http(monkeypatch)
        _install(ws, "community-question")
        article = _entry(ws, "article", "Engraving brass", status="published", data={"body": "Brass, step by step."})
        ws.ai.reply_text(json.dumps({"question": "Which tool would you try first on brass?"}))

        _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry")

        [(method, url, body)] = calls
        assert url == "https://community.example/hooks/new-post" and body["text"] == "Which tool would you try first on brass?"
        assert "Engraving brass" in ws.ai.last_request()
        # Published: the question waits as a suggestion on the entry (approval mode allow-draft-update).
        assert _reload(ws, article).suggestion_json["metadata_json.discussion_question"] == "Which tool would you try first on brass?"
        assert [r.status for r in _runs(ws, "community-question")] == ["success"]

    def test_marvin_margin_notes(self, ws):
        row = _install(ws, "marvin-margin-notes")
        draft = _entry(ws, "article", "Half-finished thoughts", data={"body": "Things."})
        _entry(ws, "article", "Already out", status="published", data={"body": "Done."})  # not a draft: left alone
        ws.ai.reply_text(json.dumps({"note": "It is a beginning. Most things are, until they aren't."}))

        result = run_automation_now(ws.session, ws.gid, row, recorder=ExecutionRecorder(ws.session, ws.gid))

        assert result["ran"] == 1 and len(ws.ai.requests) == 1
        assert "a weary robot" in ws.ai.last_request()
        assert _reload(ws, draft).metadata_json["margin_note"].startswith("It is a beginning.")

    def test_soundtrack_brief(self, ws):
        row = _install(ws, "soundtrack-brief")
        story = _entry(ws, "article", "The lighthouse keeper", data={"body": "Storm, alone, a light."})
        ws.ai.reply_text(json.dumps({"mood": "brooding", "tempo_bpm": 400, "instrumentation": ["cello"], "brief": "x"}))  # misses twice over
        ws.ai.reply_text(
            json.dumps(
                {"mood": "brooding", "tempo_bpm": 64, "instrumentation": ["cello", "foghorn"], "brief": "Slow strings under a storm; one light."}
            )
        )

        run_automation_now(ws.session, ws.gid, row, recorder=ExecutionRecorder(ws.session, ws.gid))

        meta = _reload(ws, story).metadata_json
        assert (meta["soundtrack_mood"], meta["soundtrack_tempo_bpm"], meta["soundtrack_instruments"]) == ("brooding", 64, ["cello", "foghorn"])
        assert len(ws.ai.requests) == 2  # the first answer was checked and sent back once

    def test_resource_attachment_notes(self, ws):
        _install(ws, "resource-attachment-notes")
        article = _entry(ws, "article", "A waxed bag", data={"body": "Sewing a bag."})
        _fire(ws, "entry_resource_attached", _entry_doc(article, resource_name="Waxed Canvas"), entity=article.id, entity_type="entry")
        assert "resource_note" not in (_reload(ws, article).metadata_json or {})  # nothing queued: an empty answer fails, nothing written

        ws.ai.reply_text(json.dumps({"note": "Waxed canvas sheds rain and softens with use, which suits a bag carried every day."}))
        _fire(ws, "entry_resource_attached", _entry_doc(article, resource_name="Waxed Canvas"), entity=article.id, entity_type="entry")

        assert "Waxed Canvas" in ws.ai.last_request()
        assert _reload(ws, article).metadata_json["resource_note"].startswith("Waxed canvas sheds rain")
        assert [r.status for r in _runs(ws, "resource-attachment-notes")] == ["failed", "success"]

    def test_asset_attachment_social_kit(self, ws, monkeypatch):
        from marvin.db.models.platform import Assets

        _install(ws, "asset-attachment-social-kit")
        article = _entry(ws, "article", "Harbour at dawn", data={"body": "x"})
        photo = _asset(ws, "harbour", mime="image/jpeg")
        ws.session.commit()
        monkeypatch.setattr(
            "marvin.services.storage.provider_factory.provider_for",
            lambda name: SimpleNamespace(get=lambda key: __import__("io").BytesIO(b"\xff\xd8jpeg")),
        )
        ws.ai.reply_text(json.dumps({"caption": "Boats waking up in the harbour.", "square_crop": "the red boat", "story_crop": "mast to water"}))

        _fire(ws, "asset_attached_to_entry", _entry_doc(article, asset_id=str(photo.id)), entity=article.id, entity_type="entry")

        assert "image" in ws.ai.last_request().lower()  # it looked at the picture
        meta = _reload(ws, article).metadata_json
        assert meta["social_caption"] == "Boats waking up in the harbour."
        assert meta["social_crops"] == {"square": "the red boat", "story": "mast to water", "asset_id": str(photo.id)}
        ws.session.query(Assets).filter(Assets.group_id == ws.gid).delete(synchronize_session=False)
        ws.session.commit()

    # ── custom AI step + create a draft ──
    def _drafts(self, ws, key):
        from marvin.db.models.platform import Entries

        return [e for e in ws.session.query(Entries).filter(Entries.group_id == ws.gid).all() if key in (e.metadata_json or {})]

    def test_one_entry_many_voices(self, ws):
        _install(ws, "one-entry-many-voices")
        article = _entry(ws, "article", "Engraving brass", status="published", data={"body": "Brass, step by step."})
        answer = {
            "linkedin": "Ten years of brass taught me patience. " * 2,
            "short_post": "Brass, patiently.",
            "community": "What's the first thing you'd engrave? " * 2,
        }
        ws.ai.reply_text(json.dumps(answer))
        ws.ai.reply_text(json.dumps(answer))

        _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry", correlation_id="pub-voices")
        _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry", correlation_id="pub-voices")  # the same event again

        second = _runs(ws, "one-entry-many-voices")[-1]
        assert second.status == "success" and second.actions[1].output_snapshot["created"] is False  # found, not made twice

        (draft,) = self._drafts(ws, "voices_of")
        assert (draft.title, draft.status) == ("Voices: Engraving brass", "draft") and draft.entry_type_id == ws.types["newsletter-issue"]
        assert draft.data_json["body"].startswith("LinkedIn:\nTen years") and "Short post:\nBrass, patiently." in draft.data_json["body"]

    def test_behind_the_scenes_diary(self, ws, monkeypatch):
        from marvin.db.models.platform import Assets
        from marvin.db.models.platform.entry_assets import EntryAssets

        _install(ws, "behind-the-scenes-diary")
        update = _entry(ws, "article", "Week 3 on the loom", status="published", data={"body": "Warped the loom; broke two threads."})
        photo = _asset(ws, "loom", mime="image/jpeg")
        ws.session.add(EntryAssets(entry_id=update.id, asset_id=photo.id, position=0))
        ws.session.commit()
        monkeypatch.setattr(
            "marvin.services.storage.provider_factory.provider_for",
            lambda name: SimpleNamespace(get=lambda key: __import__("io").BytesIO(b"\xff\xd8jpeg")),
        )
        ws.ai.reply_text(json.dumps({"title": "Warping the loom", "body": "This week the loom went from bare frame to warped and ready. " * 2}))

        _fire(ws, "entry_published", _entry_doc(update), entity=update.id, entity_type="entry", correlation_id="pub-diary")

        assert "image" in ws.ai.last_request().lower()  # the process photo went to the AI
        (draft,) = self._drafts(ws, "diary_of")
        assert draft.title == "Warping the loom" and draft.data_json["body"].startswith("This week the loom")
        ws.session.query(EntryAssets).filter(EntryAssets.asset_id == photo.id).delete(synchronize_session=False)
        ws.session.query(Assets).filter(Assets.group_id == ws.gid).delete(synchronize_session=False)
        ws.session.commit()

    def test_ada_explains_it(self, ws):
        _install(ws, "ada-explains-it")
        article = _entry(ws, "article", "Vector clocks", status="published", data={"body": "Lamport timestamps and beyond."})
        ws.ai.reply_text(
            json.dumps({"title": "Who spoke first?", "explanation": "Imagine friends passing notes in class, each numbering theirs. " * 3})
        )

        _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry", correlation_id="pub-ada")

        (draft,) = self._drafts(ws, "adaptation_of")
        assert draft.title == "Who spoke first?" and "An adaptation of “Vector clocks”" in draft.data_json["body"]
        assert "written by AI" in draft.data_json["body"]

    def test_fictional_debate_club(self, ws):
        row = _install(ws, "fictional-debate-club")
        _entry(ws, "article", "Hand tools or power tools", status="published", data={"body": "x"})
        _entry(ws, "article", "Still a draft", data={"body": "x"})  # not published: not debated
        ws.ai.reply_text(
            json.dumps({"title": "The bench debate", "dialogue": "MAKER: The chisel listens. ACCOUNTANT: The router invoices faster. " * 3})
        )

        result = run_automation_now(ws.session, ws.gid, row, recorder=ExecutionRecorder(ws.session, ws.gid))

        assert result["ran"] == 1 and "a sceptical accountant" in ws.ai.last_request()
        (draft,) = self._drafts(ws, "debate_on")
        assert draft.data_json["body"].startswith("A fictional debate — the speakers are made up.")

    # ── approval steps ──
    def _decide(self, ws, decision="approve"):
        from marvin.services.automation import approvals
        from marvin.services.automation.authz import ROLE_EDITOR

        (waiting,) = approvals.pending(ws.session, ws.gid, ROLE_EDITOR)
        return approvals.decide(ws.session, ws.gid, waiting.id, decision, user_id=ws.uid, role=ROLE_EDITOR)

    def test_translation_desk(self, ws):
        _install(ws, "translation-desk")
        article = _entry(ws, "article", "Engraving brass", status="published", data={"body": "Brass, step by step."})
        ws.ai.reply_text(json.dumps({"title": "Grabado en latón", "body": "Latón, paso a paso, con paciencia y buenas herramientas."}))

        _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry", correlation_id="pub-translate")
        (draft,) = self._drafts(ws, "translation_of")
        assert (draft.title, draft.status, draft.metadata_json["language"]) == ("Grabado en latón", "draft", "Spanish")
        self._decide(ws)

        assert _reload(ws, draft).status == "published"

    def test_featured_collection_curator(self, ws):
        from marvin.db.models.platform.entry_collections import EntryCollections
        from marvin.services.automation import approvals
        from marvin.services.automation.authz import ROLE_EDITOR

        _install(ws, "featured-collection-curator")
        weak = _entry(ws, "article", "Shop closed Monday", status="published", data={"body": "x"})
        ws.ai.reply_text(json.dumps({"fits": False, "reason": "A notice, not a piece."}))
        _fire(ws, "entry_published", _entry_doc(weak), entity=weak.id, entity_type="entry", correlation_id="pub-weak")
        assert approvals.pending(ws.session, ws.gid, ROLE_EDITOR) == []  # nothing to ask

        strong = _entry(ws, "article", "Engraving brass", status="published", data={"body": "x"})
        ws.ai.reply_text(json.dumps({"fits": True, "reason": "A thorough guide readers keep coming back to."}))
        _fire(ws, "entry_published", _entry_doc(strong), entity=strong.id, entity_type="entry", correlation_id="pub-strong")
        self._decide(ws)

        assert ws.session.query(EntryCollections).filter_by(entry_id=strong.id).count() == 1
        assert ws.session.query(EntryCollections).filter_by(entry_id=weak.id).count() == 0

    def test_meeting_notes_to_tasks(self, ws):
        _install(ws, "meeting-notes-to-tasks")
        notes = _entry(ws, "newsletter-issue", "Monday sync", data={"body": "Ada will email the venue by Friday."})
        ws.ai.reply_text(json.dumps({"count": 1, "tasks_markdown": "- Ada: email the venue by Friday (“Ada will email the venue by Friday.”)"}))

        _fire(ws, "entry_created", _entry_doc(notes), entity=notes.id, entity_type="entry", correlation_id="notes-1")
        assert self._drafts(ws, "tasks_from") == []  # waits for an editor
        self._decide(ws)

        (tasks,) = self._drafts(ws, "tasks_from")
        assert tasks.title == "Tasks from Monday sync" and tasks.data_json["body"].startswith("- Ada: email the venue")

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

    # ── media steps and generated images ──
    @fixture
    def store(self, ws, tmp_path, monkeypatch):
        """Storage in a temporary folder; the events item ops send are recorded rather than put on the bus."""
        from marvin.services.storage import provider_factory
        from marvin.services.storage.local_provider import LocalStorageProvider

        local = LocalStorageProvider(root=tmp_path / "store", public_base_url="/assets")
        monkeypatch.setattr(provider_factory, "get_storage_provider", lambda *a, **k: local)
        monkeypatch.setattr(provider_factory, "provider_for", lambda slug: local)
        yield SimpleNamespace(local=local, sent=_dispatched(monkeypatch))
        from marvin.db.models.platform import Assets, EntryAssets

        ws.session.rollback()
        ws.session.query(EntryAssets).filter(EntryAssets.asset_id.in_(ws.session.query(Assets.id).filter(Assets.group_id == ws.gid))).delete(
            synchronize_session=False
        )
        ws.session.query(Assets).filter(Assets.group_id == ws.gid).delete(synchronize_session=False)
        ws.session.commit()

    def _picture_asset(self, ws, store, name, data, mime="image/png", **extra):
        row = _asset(ws, name, mime=mime, **extra)
        row.storage_key, row.file_size = f"lib/{row.slug}", len(data)
        store.local.put(storage_key=row.storage_key, file_data=io.BytesIO(data), content_type=mime)
        ws.session.commit()
        return row

    def _made_from(self, ws, source) -> list:
        from marvin.db.models.platform import Assets

        rows = ws.session.query(Assets).filter(Assets.group_id == ws.gid).all()
        return sorted((a for a in rows if (a.metadata_json or {}).get("derived_from") == str(source.id)), key=lambda a: a.width or 0)

    def _upload(self, ws, asset, correlation_id="corr-1"):
        _fire(ws, "asset_uploaded", {"asset_id": str(asset.id)}, entity=asset.id, entity_type="asset", correlation_id=correlation_id)

    def test_responsive_image_factory(self, ws, store):
        from marvin.db.models.platform import EntryAssets

        _install(ws, "responsive-image-factory")
        article = _entry(ws, "article", "Harbour", data={"body": "x"})
        hero = self._picture_asset(ws, store, "hero", _picture((2400, 1600)))
        ws.session.add(EntryAssets(entry_id=article.id, asset_id=hero.id, role="hero", position=0))
        ws.session.commit()

        _fire(ws, "asset_attached_to_entry", _entry_doc(article, asset_id=str(hero.id), role="hero"), entity=article.id, entity_type="entry")
        _fire(ws, "asset_attached_to_entry", _entry_doc(article, asset_id=str(hero.id), role="gallery"), entity=article.id, entity_type="entry")

        sizes = self._made_from(ws, hero)
        assert [(a.width, a.height, a.mime_type) for a in sizes] == [(400, 267, "image/webp"), (800, 533, "image/webp"), (1600, 1067, "image/webp")]
        roles = {ea.role for ea in ws.session.query(EntryAssets).filter_by(entry_id=article.id)}
        assert roles == {"hero", "hero-400", "hero-800", "hero-1600"}
        assert [r.status for r in _runs(ws, "responsive-image-factory")] == ["success"]  # the gallery attach didn't match

    def test_smart_crop_pack(self, ws, store):
        from marvin.db.models.groups.ai_executions import AIExecutionModel

        _install(ws, "smart-crop-pack")
        photo = self._picture_asset(ws, store, "harbour", _picture((1200, 800)))
        ws.ai.reply_text(json.dumps({"box": [0.1, 0.2, 0.3, 0.5]}))  # one answer: the three crops share it

        self._upload(ws, photo)
        self._upload(ws, photo, correlation_id="corr-2")  # again: the crops are reused, not remade

        crops = self._made_from(ws, photo)
        assert sorted((a.width, a.height) for a in crops) == [(640, 800), (800, 800), (1200, 675)]
        assert all(a.metadata_json["derivation"].endswith("focus=subject") for a in crops)
        assert ws.session.query(AIExecutionModel).filter_by(group_id=ws.gid, operation_slug="detect-subject").count() == 1
        assert len(ws.ai.requests) == 1  # one vision call per picture, and none on the re-run (the crops are reused)
        assert [s["reused"] for s in (a.output_snapshot for a in _runs(ws, "smart-crop-pack")[-1].actions)] == [True, True, True]

    def test_file_format_converter(self, ws, store):
        _install(ws, "file-format-converter")
        jpeg = self._picture_asset(ws, store, "photo", _picture(fmt="JPEG"), mime="image/jpeg")
        webp = self._picture_asset(ws, store, "already", _picture(fmt="WEBP"), mime="image/webp")

        for asset in (jpeg, webp):
            self._upload(ws, asset)

        (copy,) = self._made_from(ws, jpeg)
        assert (copy.mime_type, copy.extension, copy.metadata_json["derivation"]) == ("image/webp", "webp", "media:convert:format=webp,quality=82")
        assert self._made_from(ws, webp) == [] and self._made_from(ws, copy) == []  # its own copy isn't an upload

    def test_image_quality_gate(self, ws, store):
        _install(ws, "image-quality-gate")
        crisp = Image.new("RGB", (1600, 1200), (255, 255, 255))
        for x in range(0, 1600, 8):
            crisp.paste((0, 0, 0), (x, 0, x + 4, 1200))
        blurry = crisp.filter(ImageFilter.GaussianBlur(12))
        assets = []
        for name, img in (("crisp", crisp), ("blurry", blurry)):
            out = io.BytesIO()
            img.save(out, format="PNG")
            assets.append(self._picture_asset(ws, store, name, out.getvalue()))
        small = self._picture_asset(ws, store, "thumb", _picture((300, 200)))

        for asset in (*assets, small):
            self._upload(ws, asset)

        reported = [c["body"] for c in ws.providers["apprise"].calls]
        assert len(reported) == 2 and any("“blurry”" in b for b in reported) and any("“thumb” is 300×200" in b for b in reported)

    def test_brand_recolor(self, ws, store):
        from marvin.db.models.platform import AssetTags, Tags

        row = _install(ws, "brand-recolor")
        tag = Tags(session=ws.session, group_id=ws.gid, name="brand", slug="brand")
        ws.session.add(tag)
        ws.session.flush()
        logo = self._picture_asset(ws, store, "logo", _picture(color=(120, 120, 120)))
        other = self._picture_asset(ws, store, "other", _picture())
        ws.session.add(AssetTags(asset_id=logo.id, tag_id=tag.id))
        ws.session.commit()

        result = run_automation_now(ws.session, ws.gid, row, recorder=ExecutionRecorder(ws.session, ws.gid))

        (graded,) = self._made_from(ws, logo)
        assert result["ok"] and graded.metadata_json["derivation"] == "media:grade:preset=warm" and self._made_from(ws, other) == []

    def test_alternate_universe_cover(self, ws, store):
        from marvin.db.models.platform import EntryAssets

        _install(ws, "alternate-universe-cover")
        article = _entry(ws, "article", "Harbour at dawn", status="published", data={"body": "x"}, summary="Boats at first light.")

        _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry", correlation_id="pub-cover")
        assert ws.providers["openai_images"].calls == []  # nothing drawn before an editor says yes
        self._decide(ws)

        (call,) = ws.providers["openai_images"].calls
        assert "1950s sci-fi pulp" in call["prompt"] and "Harbour at dawn" in call["prompt"]
        # Drawn, kept, and now shown: the second approval carries the picture, and nothing is attached until it's a yes.
        from marvin.services.automation import approvals as approvals_svc
        from marvin.services.automation.authz import ROLE_EDITOR

        (asking,) = approvals_svc.pending(ws.session, ws.gid, ROLE_EDITOR)
        assert asking.image_url and "Use this" in asking.message
        assert ws.session.query(EntryAssets).filter_by(entry_id=article.id, role="cover-variant").count() == 0
        self._decide(ws)
        link = ws.session.query(EntryAssets).filter_by(entry_id=article.id, role="cover-variant").one()
        cover = link.asset
        assert asking.image_url.endswith(cover.storage_key.rsplit("/", 1)[-1]) or cover.slug in asking.image_url
        assert cover.name == "Harbour at dawn — a 1950s sci-fi pulp cover" and cover.mime_type == "image/png"
        assert cover.metadata_json["generated_by"] == "openai_images.generate" and cover.metadata_json["model"] == "gpt-image-1"

    def test_image_prompt_archive(self, ws, store):
        _install(ws, "image-prompt-archive")
        article = _entry(ws, "article", "Harbour", data={"body": "x"})
        drawn = self._picture_asset(
            ws, store, "drawn", _picture(), metadata_json={"generated_by": "openai_images.generate", "prompt": "A harbour", "model": "gpt-image-1"}
        )
        photo = self._picture_asset(ws, store, "photo", _picture())

        for asset in (photo, drawn):
            _fire(ws, "asset_attached_to_entry", _entry_doc(article, asset_id=str(asset.id)), entity=article.id, entity_type="entry")

        meta = _reload(ws, article).metadata_json
        assert (meta["image_prompt"], meta["image_model"], meta["image_generated_by"], meta["image_asset"]) == (
            "A harbour",
            "gpt-image-1",
            "openai_images.generate",
            drawn.slug,
        )
        assert [r.status for r in _runs(ws, "image-prompt-archive")] == ["success"]  # the photo didn't match

    def test_milestone_celebration(self, ws, store):
        from marvin.db.models.platform import EntryAssets

        _install(ws, "milestone-celebration")
        project = _entry(ws, "project", "Brass lantern", data={"stage": "complete"})
        ws.ai.reply_text(json.dumps({"post": "The brass lantern is finished — weeks of careful work.", "visual": "a glowing brass lantern"}))
        updated = _entry_doc(project, changed_fields=["data_json"])

        _fire(ws, "entry_updated", updated, entity=project.id, entity_type="entry", correlation_id="upd-1")
        _fire(ws, "entry_updated", updated, entity=project.id, entity_type="entry", correlation_id="upd-2")  # a later save
        self._decide(ws)

        meta = _reload(ws, project).metadata_json
        assert meta["celebrated"] is True and meta["celebration_post"].startswith("The brass lantern is finished")
        assert len(ws.ai.requests) == 1  # once per project
        (call,) = ws.providers["openai_images"].calls
        assert call["prompt"] == "A bright, hand-drawn poster: a glowing brass lantern"
        assert ws.session.query(EntryAssets).filter_by(entry_id=project.id, role="celebration").count() == 1

    # ── documents and privacy (a media step's extract_text / pages / find_sensitive / redact) ──
    def _document(self, ws, store, name, pages):
        return self._picture_asset(ws, store, name, pdf(pages), mime="application/pdf", asset_type="document")

    def test_ocr_notebook(self, ws, store):
        _install(ws, "ocr-notebook")
        guide = self._document(ws, store, "wax-guide", ["Warm the wax before you rub it in.", "Let the canvas cure for a week."])
        photo = self._picture_asset(ws, store, "snapshot", _picture())
        ws.ai.reply_text(json.dumps({"title": "Notes: waxing canvas", "body": "Warm the wax first (p. 1). Cure for a week (p. 2)."}))

        for asset in (photo, guide):  # a picture isn't read: the recipe takes PDFs (a scan's pages are read by the AI)
            self._upload(ws, asset, correlation_id=f"up-{asset.slug}")

        prompt = ws.ai.last_request()
        assert "[page 1]" in prompt and "Warm the wax before you rub it in." in prompt and "[page 2]" in prompt
        (notes,) = self._issues(ws)
        assert (notes.title, notes.status, notes.metadata_json["source_document"]) == ("Notes: waxing canvas", "draft", guide.slug)
        assert len(ws.ai.requests) == 1  # the text layer was read without AI

    def test_document_preview_factory(self, ws, store):
        from marvin.db.models.platform import EntryAssets

        _install(ws, "document-preview-factory")
        kit = _entry(ws, "article", "Pattern kit", data={"body": "x"})
        doc = self._document(ws, store, "pattern-kit", ["Cover", "Pieces"])
        ws.session.add(EntryAssets(entry_id=kit.id, asset_id=doc.id, role="download", position=0))
        ws.session.commit()

        _fire(ws, "asset_attached_to_entry", _entry_doc(kit, asset_id=str(doc.id), role="download"), entity=kit.id, entity_type="entry")

        made = sorted(self._made_from(ws, doc), key=lambda a: (a.metadata_json["page"], a.width))
        assert [(a.metadata_json["page"], a.width) for a in made] == [(1, 1200), (1, 1600), (2, 1200)]  # 2 pages; 1 cover
        links = {(ea.asset_id, ea.role) for ea in ws.session.query(EntryAssets).filter_by(entry_id=kit.id)}
        assert links == {(doc.id, "download"), (made[0].id, "preview"), (made[2].id, "preview"), (made[1].id, "cover")}

    def test_privacy_crop_desk(self, ws, store, monkeypatch):
        from marvin.services.automation.actions import media as media_step

        vision = _Vision(regions=[{"kind": "face", "box": [0.3, 0.2, 0.2, 0.3]}, {"kind": "text", "box": [0.1, 0.8, 0.4, 0.1]}])
        monkeypatch.setattr(media_step, "vision_handler", lambda session, group_id, kind: (vision, None))
        _install(ws, "privacy-crop-desk")
        street = self._picture_asset(ws, store, "street", _picture((800, 600)))

        self._upload(ws, street)
        assert self._made_from(ws, street) == []  # waits for an editor
        self._decide(ws)

        (blurred,) = self._made_from(ws, street)
        assert blurred.metadata_json["media_op"] == "redact" and blurred.metadata_json["regions"] == 1  # a face; text isn't asked for
        assert [t.slug for t in blurred.tags] == ["blurred"] and len(vision.calls) == 1

    def test_archive_packager(self, ws, store):
        import zipfile

        from marvin.db.models.platform import Assets, Collections, EntryAssets
        from marvin.db.models.platform.entry_collections import EntryCollections
        from tests.test_workflow_media_documents import _bytes_of

        row = _install(ws, "archive-packager")
        featured = ws.session.query(Collections).filter_by(group_id=ws.gid, slug="featured").one()
        for order, title in enumerate(("Brass lantern", "Chore coat")):
            entry = _entry(ws, "article", title, status="published", data={"body": f"All about the {title.lower()}."})
            ws.session.add(EntryCollections(entry_id=entry.id, collection_id=featured.id, sort_order=order))
            picture = self._picture_asset(ws, store, f"{entry.slug}-photo", _picture())
            ws.session.add(EntryAssets(entry_id=entry.id, asset_id=picture.id, role="hero", position=0))
        ws.session.commit()

        self._run_with(ws, row, {"collection": "featured"})

        (archive,) = [a for a in ws.session.query(Assets).filter(Assets.group_id == ws.gid) if a.mime_type == "application/zip"]
        with zipfile.ZipFile(io.BytesIO(_bytes_of(ws, archive))) as z:
            names = z.namelist()
            manifest = json.loads(z.read("manifest.json"))
        assert sum(n.endswith("entry.json") for n in names) == 2 and len(manifest["files"]) == 2
        assert [i["title"] for i in manifest["items"]] == ["Brass lantern", "Chore coat"]  # the collection's order
        assert [t.slug for t in archive.tags] == ["archive"]

    @needs_browser
    def test_workshop_field_guide(self, ws, store):
        from marvin.services.ai.media import documents
        from tests.test_workflow_media_documents import _bytes_of

        row = _install(ws, "workshop-field-guide")
        lantern = _entry(ws, "project", "Brass lantern", status="published", data={"stage": "complete"})
        self._with_hero(ws, store, lantern)
        for title, body in (("Cutting", "Cut the shade from 0.5 mm brass."), ("Wiring", "Soldered the leads.")):
            _entry(ws, "article", title, status="published", data={"body": body, "project": lantern.slug})
        guide = {
            "title": "Making a brass lantern",
            "intro": "A small lantern from one sheet of brass.",
            "body": "## Tools and materials\n\n- Brass sheet\n- Snips\n\n## Steps\n\n1. Cut the shade.\n2. Solder the leads.\n\n## Tips\n\nGo slow.",
        }
        ws.ai.reply_text(json.dumps(guide))

        self._run_with(ws, row, {"project": lantern.slug})

        assert "Cut the shade from 0.5 mm brass." in ws.ai.last_request()  # the log
        (link,) = self._role(ws, lantern, "field-guide")
        assert link.asset.mime_type == "application/pdf"
        first_page = documents.read(_bytes_of(ws, link.asset))[1][0]
        assert "Making a brass lantern" in first_page and "1. Cut the shade." in first_page and "Solder the leads." in first_page

    # ── social ──
    @staticmethod
    def _site(ws, url="https://studio.example"):
        from marvin.db.models.groups.preferences import GroupPreferencesModel

        prefs = ws.session.query(GroupPreferencesModel).filter_by(group_id=ws.gid).first()
        if prefs is None:
            prefs = GroupPreferencesModel(session=ws.session, group_id=ws.gid)
            ws.session.add(prefs)
        prefs.site_canonical_url = url
        ws.session.commit()

    def test_one_tap_share_links(self, ws):
        self._site(ws)
        _install(ws, "one-tap-share-links")
        piece = _entry(ws, "article", "Tide and Moon", status="published", data={"body": "A new etching of the harbour at night."})
        ws.ai.reply_text(json.dumps({"text": "New etching: the harbour at night. #printmaking"}))

        _fire(ws, "entry_published", _entry_doc(piece), entity=piece.id, entity_type="entry")

        meta = _reload(ws, piece).metadata_json
        assert meta["share_text"] == "New etching: the harbour at night. #printmaking"
        links = meta["share_links"]
        assert set(links) == {"Bluesky", "Mastodon", "Threads", "LinkedIn", "Email"}
        page = f"https%3A%2F%2Fstudio.example%2Farticles%2F{piece.slug}"
        assert links["Bluesky"] == (
            "https://bsky.app/intent/compose?text=New%20etching%3A%20the%20harbour%20at%20night.%20%23printmaking%0A%0A"
            f"{page}%3Futm_source%3Dbluesky%26utm_medium%3Dsocial%26utm_campaign%3D{piece.slug}"
        )
        assert links["Mastodon"].startswith("https://mastodon.social/share?text=New%20etching")
        assert (
            links["LinkedIn"]
            == f"https://www.linkedin.com/sharing/share-offsite/?url={page}%3Futm_source%3Dlinkedin%26utm_medium%3Dsocial%26utm_campaign%3D{piece.slug}"
        )
        assert links["Email"].startswith("mailto:?subject=Tide%20and%20Moon&body=")

    def test_one_tap_share_links_needs_a_full_page_address(self, ws):
        _install(ws, "one-tap-share-links")  # no Canonical URL: the page is only a path, useless in a post
        piece = _entry(ws, "article", "Tide", status="published", data={"body": "x"})
        _fire(ws, "entry_published", _entry_doc(piece), entity=piece.id, entity_type="entry")
        assert "share_links" not in (_reload(ws, piece).metadata_json or {}) and ws.ai.requests == []

    @needs_browser
    def test_on_this_day(self, ws, store):
        from marvin.db.models.platform import EntryAssets

        row = _install(ws, "on-this-day")
        kiln = self._aged(ws, _entry(ws, "article", "First kiln firing", status="published", data={"body": "We fired the kiln."}), published=365.5)
        hero = self._with_hero(ws, store, kiln)
        self._aged(ws, _entry(ws, "article", "Not a year ago", status="published", data={"body": "x"}), published=300)
        post = {"title": "A year ago: the first firing", "body": "A year ago today we fired the kiln.", "caption": "Our first firing."}
        ws.ai.reply_text(json.dumps(post))

        self._run(ws, row, trigger_kind="schedule")

        (draft,) = self._issues(ws)
        assert draft.status == "draft" and draft.metadata_json["throwback_of"] == kiln.slug
        assert "First kiln firing" in json.dumps(ws.ai.requests[0]) and "Not a year ago" not in json.dumps(ws.ai.requests[0])
        (card,) = self._rendered(ws, "card")
        assert [t.slug for t in card.tags] == ["on-this-day"] and card.metadata_json["rendered_from"] == {"image": str(hero.id)}
        roles = {ea.role for ea in ws.session.query(EntryAssets).filter_by(entry_id=draft.id, asset_id=card.id)}
        assert roles == {"throwback-card"}

    def test_on_this_day_quiet_when_nothing_was_published(self, ws):
        row = _install(ws, "on-this-day")
        self._run(ws, row, trigger_kind="schedule")
        assert self._issues(ws) == [] and ws.ai.requests == []

    @needs_browser
    def test_audience_milestone(self, ws, store):
        from marvin.db.models.platform import EntryAssets

        _install(ws, "audience-milestone")
        people = [_entry(ws, "contact-request", f"Reader {i}", status="published", data={"email": f"r{i}@x.test"}) for i in range(10)]
        post = {"title": "Ten of you!", "body": "Thank you, all ten of you, for signing up.", "headline": "Thank you"}
        ws.ai.reply_text(json.dumps(post))

        for person in (people[-1], people[-1]):  # the tenth sign-up — and the same one published again
            _fire(ws, "entry_published", _entry_doc(person), entity=person.id, entity_type="entry", user_id=ws.uid)

        (thanks,) = self._issues(ws)  # once per milestone
        assert thanks.metadata_json["audience_milestone"] == "subscribers 10"
        assert "Reader" not in json.dumps(ws.ai.requests)  # counts only: no one's name reaches the AI
        (card,) = self._rendered(ws, "card")
        assert ws.session.query(EntryAssets).filter_by(entry_id=thanks.id, asset_id=card.id).one().role == "milestone-card"

        eleventh = _entry(ws, "contact-request", "Reader 10", status="published", data={"email": "r10@x.test"})
        _fire(ws, "entry_published", _entry_doc(eleventh), entity=eleventh.id, entity_type="entry")
        assert len(self._issues(ws)) == 1 and len(ws.ai.requests) == 1  # 11 isn't a milestone

    def test_collaborator_shout_out(self, ws):
        _install(ws, "collaborator-shout-out")
        ada = _entry(ws, "person", "Ada", status="published", data={"handle": "@ada@mastodon.social", "ok_to_tag": True})
        grace = _entry(ws, "person", "Grace", status="published", data={"handle": "@grace@bsky.social", "ok_to_tag": False})
        lantern = _entry(ws, "project", "Brass lantern", status="published", data={"collaborators": f"{ada.slug}, {grace.slug}"})
        ws.ai.reply_text(json.dumps({"title": "Thank you, Ada", "body": "The brass lantern is out — thank you @ada@mastodon.social!"}))

        _fire(ws, "entry_published", _entry_doc(lantern), entity=lantern.id, entity_type="entry", correlation_id="pub-lantern")
        asked = json.dumps(ws.ai.requests)
        assert "@ada@mastodon.social" in asked and "Grace" not in asked and "@grace" not in asked  # only those who said yes
        assert self._issues(ws) == []  # waiting for an editor

        self._decide(ws)

        (thanks,) = self._issues(ws)
        assert thanks.status == "draft" and thanks.metadata_json["shout_out_for"] == lantern.slug
        assert _reload(ws, ada).metadata_json["last_credited"] == {"for": lantern.slug, "title": "Brass lantern"}  # each one thanked
        assert "last_credited" not in (_reload(ws, grace).metadata_json or {})  # not asked to be tagged: not thanked

    def test_collaborator_shout_out_declined_drafts_nothing(self, ws):
        _install(ws, "collaborator-shout-out")
        ada = _entry(ws, "person", "Ada", status="published", data={"handle": "@ada", "ok_to_tag": True})
        lantern = _entry(ws, "project", "Lantern", status="published", data={"collaborators": ada.slug})
        ws.ai.reply_text(json.dumps({"title": "Thanks", "body": "Thank you @ada for the lantern."}))
        _fire(ws, "entry_published", _entry_doc(lantern), entity=lantern.id, entity_type="entry")

        self._decide(ws, "deny")

        assert self._issues(ws) == []

    def test_thread_builder(self, ws):
        _install(ws, "thread-builder")
        piece = _entry(ws, "article", "Waxing canvas", status="published", data={"body": "Warm the wax. Rub it in. Let it cure."})
        posts = ["Waxed canvas, start to finish 🧵", "Warm the wax first.", "Then let it cure for a week."]
        ws.ai.reply_text(json.dumps({"title": "Thread: waxing canvas", "posts": posts, "body": "1/3 Waxed canvas… 2/3 Warm… 3/3 Cure…"}))

        _fire(ws, "entry_published", _entry_doc(piece), entity=piece.id, entity_type="entry")

        (draft,) = self._issues(ws)
        assert draft.status == "draft" and draft.data_json["body"].startswith("1/3")
        assert draft.metadata_json["thread"] == posts and draft.metadata_json["thread_for"] == piece.slug
        assert '"maxLength": 300' in json.dumps(ws.ai.requests[0])  # the post length, from the setup

    def test_teaser_ladder(self, ws):
        from marvin.services.automation import waits

        _install(ws, "teaser-ladder")
        day = _day_in(ws, 10)
        kiln = _entry(ws, "event", "Kiln No. 2", status="published", data={"date": day})
        for title in ("Three days to go", "It's here", "A week on"):
            ws.ai.reply_text(json.dumps({"title": title, "body": f"{title} — the new kiln."}))

        _fire(ws, "entry_published", _entry_doc(kiln), entity=kiln.id, entity_type="entry", correlation_id="pub-kiln")
        assert self._issues(ws) == []
        for days in (8, 11, 18):  # past the teaser (day 7, 09:00), the launch (day 10) and the follow-up (day 17)
            waits.resume_due(ws.session, now_=waits.now() + timedelta(days=days))

        posts = {e.metadata_json["launch_post"]: e.title for e in self._issues(ws)}
        assert posts == {"teaser": "Three days to go", "launch": "It's here", "follow-up": "A week on"}

    @needs_browser
    def test_carousel_storyteller(self, ws, store):
        from marvin.db.models.platform import EntryAssets

        _install(ws, "carousel-storyteller")
        piece = _entry(ws, "article", "Brass lantern", status="published", data={"body": "How the lantern was made."})
        hero = self._with_hero(ws, store, piece)
        slides = [{"title": f"Step {n}", "text": f"What happened in step {n}."} for n in range(1, 6)]
        ws.ai.reply_text(json.dumps({"slides": slides}))

        _fire(ws, "entry_published", _entry_doc(piece), entity=piece.id, entity_type="entry", user_id=ws.uid)

        cards = {ea.role: a for ea, a in self._links(ws, piece) if ea.role.startswith("carousel-")}
        assert sorted(cards) == [f"carousel-{n}" for n in range(1, 6)]
        assert cards["carousel-1"].metadata_json["rendered_from"] == {"image": str(hero.id)}  # the first slide has the picture
        assert all([t.slug for t in cards[f"carousel-{n}"].tags] == ["carousel"] for n in range(1, 6))
        assert ws.session.query(EntryAssets).filter_by(entry_id=piece.id, role="hero").count() == 1

    @needs_browser
    def test_launch_kit(self, ws, store):
        _install(ws, "launch-kit")
        coat = _entry(ws, "article", "Chore coat", status="published", data={"body": "Waxed canvas, brass rivets, two pockets."})
        self._with_hero(ws, store, coat)
        kit = {
            "announcement_title": "Meet the chore coat", "announcement": "The chore coat is here: waxed canvas, brass rivets.",
            "faq": "**Is it waterproof?** It's waxed canvas.", "newsletter_title": "New: the chore coat",
            "newsletter": "This month we made a coat — waxed canvas, brass rivets and two pockets.", "tagline": "Built to last",
        }  # fmt: skip
        ws.ai.reply_text(json.dumps(kit))

        _fire(ws, "entry_published", _entry_doc(coat), entity=coat.id, entity_type="entry")

        parts = {e.metadata_json["launch_part"]: e for e in self._issues(ws)}
        assert set(parts) == {"announcement", "faq", "newsletter"} and all(e.status == "draft" for e in parts.values())
        assert parts["faq"].title == "FAQ: Chore coat" and len(ws.ai.requests) == 1  # one AI call for the whole kit
        roles = {ea.role for ea, a in self._links(ws, coat) if (a.metadata_json or {}).get("render_template") == "card"}
        assert roles == {"launch-card"}

    def test_time_capsule(self, ws):
        from marvin.services.automation import waits

        _install(ws, "time-capsule")
        plan = _entry(ws, "article", "Kiln plans", status="published", data={"body": "We'll build three kilns this year."})
        ws.ai.reply_text(
            json.dumps({"title": "Kiln plans, six months on", "body": "We planned three kilns and built two — the third waits for spring."})
        )

        _fire(ws, "entry_published", _entry_doc(plan), entity=plan.id, entity_type="entry", correlation_id="pub-plan")
        assert _reload(ws, plan).metadata_json["time_capsule"]["text"] == "We'll build three kilns this year."
        plan.data_json = {"body": "Two kilns built; the third in spring."}  # it changes meanwhile
        ws.session.commit()
        _fire(ws, "entry_published", _entry_doc(plan), entity=plan.id, entity_type="entry", correlation_id="pub-again")  # sealed once

        assert waits.resume_due(ws.session, now_=waits.now() + timedelta(weeks=26, days=1)) == 1

        (look_back,) = self._issues(ws)
        assert look_back.metadata_json["retrospective_of"] == plan.slug
        asked = json.dumps(ws.ai.requests)
        assert "three kilns this year" in asked and "third in spring" in asked  # then and now

    def test_intake_triage(self, ws):
        _install(ws, "intake-triage")
        request = _entry(
            ws, "contact-request", "Ada Lovelace", status="inbox", data={"email": "ada@example.com", "message": "Can you engrave a brass plate?"}
        )
        answer = {"intent": "Asks for an engraved brass plate", "queue": "commissions", "urgency": "normal",
                  "questions": ["What size is the plate?"], "reply": "Thanks, Ada — happy to. What size is the plate?"}  # fmt: skip
        ws.ai.reply_text(json.dumps(answer))
        spam = _entry(ws, "contact-request", "Buy now", status="inbox", data={"email": "x@spam.test", "message": "cheap pills"})

        for entry, flagged in ((request, False), (spam, True)):
            doc = _entry_doc(entry, form_name="Contact", flagged=flagged, duplicate=False, submission_data=entry.data_json)
            _fire(ws, "form_submission_received", doc, entity=entry.id, entity_type="entry", correlation_id=f"form-{entry.slug}")

        triaged = _reload(ws, request)
        assert triaged.status == "needs_review" and triaged.metadata_json["triage"]["questions"] == ["What size is the plate?"]
        assert triaged.metadata_json["review_reasons"] == ["commissions · normal: Asks for an engraved brass plate"]
        assert "commissions, orders, press, other" in json.dumps(ws.ai.requests[0])
        assert len(ws.ai.requests) == 1 and "triage" not in (_reload(ws, spam).metadata_json or {})  # flagged: never sent to the AI

    def test_thumbnail_audition(self, ws, store):
        from marvin.db.models.platform import EntryAssets
        from marvin.services.automation import approvals
        from marvin.services.automation.authz import ROLE_EDITOR

        row = _install(ws, "thumbnail-audition")
        piece = _entry(ws, "article", "Brass lantern", status="published", data={"body": "How the lantern was made."})
        concepts = [
            {"title": t, "visual": f"{t}: a lantern, {v}"}
            for t, v in (("Glow", "lit at dusk"), ("Parts", "exploded view"), ("Hands", "being polished"))
        ]
        ws.ai.reply_text(json.dumps({"concepts": concepts, "titles": [c["title"] for c in concepts]}))

        self._run_with(ws, row, {"piece": piece.slug})
        assert ws.providers["openai_images"].calls == []  # nothing drawn before an editor says yes
        self._decide(ws)  # draw them

        assert [c["prompt"] for c in ws.providers["openai_images"].calls] == [f"a 1950s sci-fi pulp: {c['visual']}" for c in concepts]
        roles = {ea.role for ea in ws.session.query(EntryAssets).filter_by(entry_id=piece.id)}
        assert roles == {"thumbnail-option-0", "thumbnail-option-1", "thumbnail-option-2"}
        (pick,) = approvals.pending(ws.session, ws.gid, ROLE_EDITOR)
        assert pick.choices == ["Glow", "Parts", "Hands"]

        approvals.decide(ws.session, ws.gid, pick.id, "approve", user_id=ws.uid, role=ROLE_EDITOR, choice="Parts")

        assert _reload(ws, piece).metadata_json["thumbnail"] == {"role": "thumbnail-option-1", "concept": "Parts"}

    def test_platform_preview_checker(self, ws, store, monkeypatch):
        _install(ws, "platform-preview-checker")
        _web(monkeypatch, {"https://shop.example/brass": (200, "text/html", ""), "https://shop.example/old": (404, "text/html", "")})
        body = "A new lantern. " * 25 + "See https://shop.example/brass and https://shop.example/old"
        post = _entry(ws, "article", "Lantern post", status="draft", data={"body": body})
        self._with_hero(ws, store, post, size=(900, 1200))  # portrait
        fine = _entry(ws, "article", "Short post", status="draft", data={"body": "Short and sweet. https://shop.example/brass"})
        self._with_hero(ws, store, fine, size=(1200, 900))

        for entry in (post, fine):
            _fire(
                ws,
                "entry_updated",
                _entry_doc(entry, changed_fields=["data_json"]),
                entity=entry.id,
                entity_type="entry",
                correlation_id=f"upd-{entry.slug}",
            )

        flagged = _reload(ws, post)
        assert flagged.status == "needs_review"
        reasons = flagged.metadata_json["review_reasons"]
        assert reasons[0] == "Too long for Bluesky: over its character limit"
        assert reasons[1].startswith("Dead links:") and "shop.example/old" in reasons[1] and "shop.example/brass" not in reasons[1]
        assert reasons[2] == "The picture is 900×1200; Bluesky shows landscape pictures best"
        assert _reload(ws, fine).status == "draft"  # nothing wrong: left alone

    def test_thank_you_notes(self, ws):
        _install(ws, "thank-you-notes")
        ada = _entry(ws, "person", "Ada", status="published", data={"role": "wiring"})
        grace = _entry(ws, "person", "Grace", status="published", data={"role": "glass"})
        lantern = _entry(ws, "project", "Brass lantern", status="published", data={"collaborators": f"{ada.slug}, {grace.slug}"})
        for name in ("Ada", "Grace"):
            ws.ai.reply_text(json.dumps({"title": f"Thank you, {name}", "body": f"{name} — the lantern wouldn't shine without your work on it."}))

        _fire(ws, "entry_published", _entry_doc(lantern), entity=lantern.id, entity_type="entry", correlation_id="pub-lantern")

        notes = {e.metadata_json["to"]: e for e in self._issues(ws)}
        assert set(notes) == {ada.slug, grace.slug} and all(
            e.status == "draft" and e.metadata_json["thank_you_for"] == lantern.slug for e in notes.values()
        )
        asked = [json.dumps(r) for r in ws.ai.requests]
        assert len(asked) == 2 and {("wiring" in a, "glass" in a) for a in asked} == {(True, False), (False, True)}  # each note: its person's part

    def test_post_event_recap(self, ws):
        from marvin.services.automation import waits

        _install(ws, "post-event-recap")
        day = _day_in(ws, 3)
        fair = _entry(ws, "event", "Maker fair", status="published", data={"date": day})
        guests = [
            _entry(ws, "rsvp", name, status="published", data={"event": fair.slug, "email": f"{name.lower()}@x.test"}) for name in ("Ada", "Grace")
        ]
        _entry(ws, "rsvp", "Elsewhere", status="published", data={"event": "another-event"})
        ws.ai.reply_text(json.dumps({"title": "What a fair", "body": "Thank you all for coming to the Maker fair — send us your photos!"}))
        for name in ("Ada", "Grace"):
            ws.ai.reply_text(json.dumps({"body": f"{name}, thank you for coming yesterday. Send any photos you took!"}))

        _fire(ws, "entry_published", _entry_doc(fair), entity=fair.id, entity_type="entry", correlation_id="pub-fair")
        assert self._issues(ws) == [] and ws.ai.requests == []  # the day after, not now
        waits.resume_due(ws.session, now_=waits.now() + timedelta(days=4, hours=12))

        (recap,) = self._issues(ws)
        assert recap.metadata_json["recap_of"] == fair.slug and "2 guests" in json.dumps(ws.ai.requests[0])
        written = {_reload(ws, g).metadata_json["thank_you"]["message"].split(",")[0] for g in guests}
        assert written == {"Ada", "Grace"} and all(_reload(ws, g).metadata_json["thank_you"]["for"] == fair.slug for g in guests)
        assert len(ws.ai.requests) == 3  # the recap, and one message per guest who came — none for another event's RSVP

    def test_achievement_cabinet(self, ws, monkeypatch):
        from fastapi.encoders import jsonable_encoder

        from marvin.db.models.platform import Collections, Entries, EntryCollections
        from marvin.services.event_bus_service.event_bus_service import EventBusService

        _install(ws, "achievement-cabinet")
        # The event comes from another workflow, as it would in practice: a project's stage becomes "shipped".
        _install_workflow(
            ws,
            "award-shipping",
            "entry_updated",
            [{"kind": "emit_event", "event": "custom.milestone", "payload": {"milestone": "Shipped", "badge": "First ${entry.title}"}}],
            when=[{"field": "entry.data.stage", "op": "eq", "value": "shipped"}],
        )
        sent: list[dict] = []
        monkeypatch.setattr(EventBusService, "dispatch", lambda self, **kw: sent.append(kw))
        lantern = _entry(ws, "project", "Brass lantern", status="published", data={"stage": "shipped"})

        def hand_on(chain: str):
            """The custom event the sender workflow put on the bus, delivered to the workflows that start on it (each real
            event has its own correlation id: a create is made once per id, so the badge check here is what counts)."""
            event = [e for e in sent if e["event_type"].name.startswith("custom.")][-1]
            document = jsonable_encoder(event["document_data"], by_alias=False)
            return _fire(ws, event["event_type"].name, document, entity=event["entity_id"], entity_type=event["entity_type"], correlation_id=chain)

        def badges():
            return [
                e
                for e in ws.session.query(Entries).filter_by(group_id=ws.gid, entry_type_id=ws.types["article"]).all()
                if e.metadata_json.get("achievement")
            ]

        def cabinet():
            featured = ws.session.query(Collections).filter_by(group_id=ws.gid, slug="featured").one()
            return {m.entry_id for m in ws.session.query(EntryCollections).filter_by(collection_id=featured.id)}

        for n in range(2):  # the stage change, and the same event sent again: the badge is awarded once
            _fire(ws, "entry_updated", _entry_doc(lantern), entity=lantern.id, entity_type="entry", user_id=ws.uid, correlation_id=f"cab-1-{n}")
            assert hand_on(f"cab-1-{n}") == 1
            assert [(e["event_type"].name, e["reaction_depth"]) for e in sent if e["event_type"].name.startswith("custom.")][-1] == (
                "custom.milestone",
                1,
            )
            (badge,) = badges()
            assert (badge.title, badge.status, badge.data_json["body"]) == ("First Brass lantern", "draft", "Brass lantern reached “Shipped”.")
            assert {k: v for k, v in badge.metadata_json.items() if k != "automation_created"} == {
                "achievement": f"{lantern.slug}:First Brass lantern",
                "project": lantern.slug,
                "milestone": "Shipped",
            }
            assert cabinet() == {badge.id}

        # …another badge for the same project is another award; the same badge for another project is too
        for n, (badge_name, project) in enumerate((("Tinkerer", lantern), ("Tinkerer", _entry(ws, "project", "Copper kettle", status="published")))):
            doc = {"event_name": "milestone", "payload": {"milestone": "Tinkered", "badge": badge_name}, "workspace_id": str(ws.gid)}
            _fire(ws, "custom.milestone", doc, entity=project.id, entity_type="entry", correlation_id=f"cab-2-{n}")
        assert sorted(b.title for b in badges()) == ["First Brass lantern", "Tinkerer", "Tinkerer"] and len(cabinet()) == 3

        # an event about no project, or naming no badge, is ignored
        _fire(ws, "custom.milestone", {"event_name": "milestone", "payload": {"badge": "Orphan"}}, correlation_id="cab-3")
        _fire(ws, "custom.milestone", {"event_name": "milestone", "payload": {"milestone": "x"}}, entity=lantern.id, entity_type="entry")
        assert len(badges()) == 3

    def test_community_welcome_pack(self, ws):
        from marvin.db.models.platform import Collections, EntryCollections

        _install(ws, "community-welcome-pack")
        featured = ws.session.query(Collections).filter_by(group_id=ws.gid, slug="featured").one()
        for order, title in enumerate(("Start here", "How we work")):
            piece = _entry(ws, "article", title, status="published", data={"body": "x"})
            ws.session.add(EntryCollections(entry_id=piece.id, collection_id=featured.id, sort_order=order))
        ws.session.commit()
        ws.ai.reply_text(json.dumps({"title": "Welcome, U", "body": "Welcome aboard — start with “Start here”, then “How we work”."}))
        joined = {
            "operation": "create",
            "workspace_id": str(ws.gid),
            "user_id": str(ws.uid),
            "username": "u",
            "user_full_name": "U",
            "role": "EDITOR",
        }

        _fire(ws, "member_added", joined, entity=ws.uid, entity_type="member", correlation_id="join-1")

        (welcome,) = self._issues(ws)
        assert welcome.status == "draft" and welcome.metadata_json["welcome_for"] and welcome.metadata_json["to"].endswith("@t.test")
        asked = json.dumps(ws.ai.requests[0])
        assert "joined as EDITOR" in asked and "Start here" in asked and "/articles/" in asked  # the pieces, with their addresses

    # ── waits ──
    def test_event_countdown(self, ws):
        from marvin.services.automation import waits

        _install(ws, "event-countdown")
        day = _day_in(ws, 12)
        fair = _entry(ws, "event", "Maker fair", status="published", data={"date": day})
        ws.ai.reply_text(json.dumps({"title": "One week to the Maker fair", "body": "The Maker fair is a week away — come and see the stalls."}))
        ws.ai.reply_text(json.dumps({"title": "Maker fair: tomorrow!", "body": "Tomorrow's the Maker fair — doors at nine, come early."}))

        _fire(ws, "entry_published", _entry_doc(fair), entity=fair.id, entity_type="entry", correlation_id="pub-fair")
        assert self._issues(ws) == [] and ws.ai.requests == []  # waiting for the week before

        waits.resume_due(ws.session, now_=waits.now() + timedelta(days=4))
        assert self._issues(ws) == []  # not yet: a week before is day 5, at 09:00
        waits.resume_due(ws.session, now_=waits.now() + timedelta(days=6))
        (week,) = self._issues(ws)
        assert (week.title, week.metadata_json["reminder_for"]) == ("One week to the Maker fair", fair.slug)

        waits.resume_due(ws.session, now_=waits.now() + timedelta(days=12))
        assert sorted(e.title for e in self._issues(ws)) == ["Maker fair: tomorrow!", "One week to the Maker fair"]
        assert len(ws.ai.requests) == 2

    def test_event_countdown_skips_a_reminder_already_past(self, ws):
        _install(ws, "event-countdown")
        soon = _entry(ws, "event", "Pop-up", status="published", data={"date": _day_in(ws, 3)})
        _fire(ws, "entry_published", _entry_doc(soon), entity=soon.id, entity_type="entry", correlation_id="pub-pop")
        assert self._issues(ws) == [] and ws.ai.requests == []  # the week-before moment has passed: no draft; it waits for the day before

    def test_event_countdown_to_a_date_every_entry_has(self, ws, monkeypatch):
        from marvin.services.automation import waits

        monkeypatch.setitem(ws.values, "event_date", "expire_at")  # no date field needed: the entry's expiry date
        _install(ws, "event-countdown")
        sale = _entry(ws, "event", "Studio sale", status="published")
        sale.expire_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=12)
        ws.session.commit()
        ws.ai.reply_text(json.dumps({"title": "One week left", "body": "The studio sale ends in a week."}))

        _fire(ws, "entry_published", _entry_doc(sale), entity=sale.id, entity_type="entry", correlation_id="pub-sale")
        assert self._issues(ws) == []
        waits.resume_due(ws.session, now_=waits.now() + timedelta(days=5, hours=1))

        (week,) = self._issues(ws)
        assert week.metadata_json["reminder_for"] == sale.slug

    # ── watermarks ──
    def test_watermark_new_pictures(self, ws, store):
        from marvin.db.models.platform import EntryAssets

        _install(ws, "watermark-new-pictures")
        coat = _entry(ws, "article", "Chore coat", data={"body": "x"})
        hero = self._with_hero(ws, store, coat)

        for _ in range(2):  # the same attach twice: one copy
            _fire(ws, "asset_attached_to_entry", _entry_doc(coat, asset_id=str(hero.id), role="hero"), entity=coat.id, entity_type="entry")

        (marked,) = self._made_from(ws, hero)
        assert marked.metadata_json["media_op"] == "watermark" and [t.slug for t in marked.tags] == ["watermarked"]
        links = {(ea.asset_id, ea.role) for ea in ws.session.query(EntryAssets).filter_by(entry_id=coat.id)}
        assert links == {(hero.id, "hero"), (marked.id, "hero-watermarked")}

    def test_watermark_a_set(self, ws, store):
        from marvin.db.models.platform import AssetTags, Tags

        row = _install(ws, "watermark-a-set")
        tag = Tags(session=ws.session, group_id=ws.gid, name="brand", slug="brand")
        ws.session.add(tag)
        ws.session.flush()
        shots = [self._picture_asset(ws, store, f"shot-{i}", _picture((600, 400))) for i in range(2)]
        other = self._picture_asset(ws, store, "not-tagged", _picture())
        ws.session.add_all(AssetTags(asset_id=s.id, tag_id=tag.id) for s in shots)
        ws.session.commit()

        self._run(ws, row)

        assert all(len(self._made_from(ws, s)) == 1 for s in shots) and self._made_from(ws, other) == []

    # ── provider image edits (OpenAI Images' edit, given the picture as the step's source) ──
    def _edit_recipe(self, ws, store, rid):
        from marvin.db.models.platform import Assets, AssetTags, Tags

        row = _install(ws, rid)
        product = self._picture_asset(ws, store, "lantern-product", _picture((800, 800)))
        self._picture_asset(ws, store, "untagged", _picture())
        tag = Tags(session=ws.session, group_id=ws.gid, name="brand", slug="brand")
        ws.session.add(tag)
        ws.session.flush()
        ws.session.add(AssetTags(asset_id=product.id, tag_id=tag.id))
        ws.session.commit()

        assert run_automation_now(ws.session, ws.gid, row, user_id=ws.uid, recorder=ExecutionRecorder(ws.session, ws.gid))["ok"]
        assert ws.providers["openai_images"].calls == []  # waits for an editor: a paid edit
        self._decide(ws)

        (call,) = ws.providers["openai_images"].calls
        assert base64.b64decode(call["image_b64"]) == _picture((800, 800))  # the tagged picture, not the other
        (edited,) = ws.session.query(Assets).filter(Assets.group_id == ws.gid, Assets.source_asset_id == product.id).all()
        assert edited.origin == "derived" and edited.metadata_json["derivation"] == "edited:openai_images.edit"
        return call, edited

    def test_background_remover(self, ws, store):
        call, edited = self._edit_recipe(ws, store, "background-remover")
        assert call["background"] == "transparent" and "Remove the background" in call["prompt"]
        assert [t.slug for t in edited.tags] == ["no-background"]

    def test_product_scene_studio(self, ws, store):
        call, edited = self._edit_recipe(ws, store, "product-scene-studio")
        assert "a sunlit oak workbench" in call["prompt"] and call["fidelity"] == "high"
        assert [t.slug for t in edited.tags] == ["scene"]

    def test_seasonal_variation(self, ws, store):
        call, edited = self._edit_recipe(ws, store, "seasonal-variation")
        assert "winter holidays" in call["prompt"] and [t.slug for t in edited.tags] == ["winter"]

    # ── rendered images (a media step's render op; needs headless Chromium) ──
    def _with_hero(self, ws, store, entry, size=(1200, 900)):
        from marvin.db.models.platform import EntryAssets

        hero = self._picture_asset(ws, store, f"{entry.slug}-hero", _picture(size))
        ws.session.add(EntryAssets(entry_id=entry.id, asset_id=hero.id, role="hero", position=0))
        ws.session.commit()
        return hero

    def _links(self, ws, entry):
        """(link, asset) for each asset attached to the entry."""
        from marvin.db.models.platform import Assets, EntryAssets

        ws.session.expire_all()
        return ws.session.query(EntryAssets, Assets).join(Assets, Assets.id == EntryAssets.asset_id).filter(EntryAssets.entry_id == entry.id).all()

    def _role(self, ws, entry, role):
        from marvin.db.models.platform import EntryAssets

        ws.session.expire_all()
        return ws.session.query(EntryAssets).filter_by(entry_id=entry.id, role=role).all()

    @needs_browser
    def test_quote_card_studio(self, ws, store):
        _install(ws, "quote-card-studio")
        body = "Brass takes patience. Every scratch tells you where the file went. I polish until the lamp looks lived in."
        good = _entry(ws, "article", "Engraving brass", status="published", data={"body": body})
        made_up = _entry(ws, "article", "Waxing canvas", status="published", data={"body": "Wax goes on warm. Then it cures for a week."})
        self._with_hero(ws, store, good)
        ws.ai.reply_text(json.dumps({"quote": "Every scratch tells you where the file went."}))
        ws.ai.reply_text(json.dumps({"quote": "Canvas loves wax more than people do."}))  # not in the text

        for entry in (good, made_up):
            _fire(ws, "entry_published", _entry_doc(entry), entity=entry.id, entity_type="entry", correlation_id=f"pub-{entry.slug}")

        (link,) = self._role(ws, good, "quote-card")
        assert (link.asset.width, link.asset.height, link.asset.metadata_json["render_template"]) == (1080, 1080, "quote")
        assert self._role(ws, made_up, "quote-card") == []  # a quote that isn't in the text is never rendered

    @needs_browser
    def test_retro_poster_machine(self, ws, store):
        row = _install(ws, "retro-poster-machine")
        coat = _entry(ws, "project", "Chore Coat", status="published", data={"stage": "complete"})
        hero = self._with_hero(ws, store, coat)
        _entry(ws, "project", "No picture yet", status="published", data={"stage": "draft"})  # has_images leaves it out

        assert run_automation_now(ws.session, ws.gid, row, recorder=ExecutionRecorder(ws.session, ws.gid))["ok"]
        run_automation_now(ws.session, ws.gid, row, recorder=ExecutionRecorder(ws.session, ws.gid))  # done: metadata.poster

        (link,) = self._role(ws, coat, "poster")
        assert (link.asset.width, link.asset.height, link.asset.source_asset_id) == (1200, 1800, hero.id)
        assert _reload(ws, coat).metadata_json["poster"] == link.asset.slug

    @needs_browser
    def test_trading_card_collection(self, ws, store):
        _install(ws, "trading-card-collection")
        lantern = _entry(ws, "project", "Brass lantern", status="published", data={"stage": "complete"})
        self._with_hero(ws, store, lantern)
        ws.ai.reply_text(json.dumps({"stats": "Stage: complete\nMaterial: brass", "flavor": "It finally glows."}))

        _fire(ws, "entry_updated", _entry_doc(lantern, changed_fields=["data_json"]), entity=lantern.id, entity_type="entry", correlation_id="u1")
        _fire(ws, "entry_updated", _entry_doc(lantern, changed_fields=["data_json"]), entity=lantern.id, entity_type="entry", correlation_id="u2")

        (link,) = self._role(ws, lantern, "trading-card")
        assert (link.asset.width, link.asset.height) == (750, 1050) and len(ws.ai.requests) == 1

    @needs_browser
    def test_meme_workshop(self, ws, store):
        row = _install(ws, "meme-workshop")
        post = _entry(ws, "article", "First pattern draft", status="published", data={"body": "It fit."})
        self._with_hero(ws, store, post)
        ws.ai.reply_text(json.dumps({"top": "When the pattern fits", "bottom": "On the first try"}))

        run_automation_now(ws.session, ws.gid, row, recorder=ExecutionRecorder(ws.session, ws.gid))
        assert self._role(ws, post, "meme") == []  # waits for an editor
        self._decide(ws)

        (link,) = self._role(ws, post, "meme")
        assert link.asset.metadata_json["render_template"] == "meme" and _reload(ws, post).metadata_json["meme"] == "approved"

    @needs_browser
    def test_future_newspaper(self, ws, store):
        row = _install(ws, "future-newspaper")
        coat = _entry(ws, "project", "Chore Coat", status="published", data={"stage": "complete"})
        story = {
            "headline": "Coat Outlasts Its Maker's Patience",
            "deck": "Ten winters on",
            "date": "12 October 2036",
            "body": "The coat came back for its tenth rewax this autumn.\n\nIts maker says the elbows are the only honest part left.",
        }
        ws.ai.reply_text(json.dumps(story))  # no picture: the page prints without one

        result = run_automation_now(ws.session, ws.gid, row, user_id=ws.uid, recorder=ExecutionRecorder(ws.session, ws.gid))  # the Run button's user
        assert result["ok"], [a.error for r in _runs(ws, "future-newspaper") for a in r.actions if a.error]

        (link,) = self._role(ws, coat, "future-front-page")
        assert (link.asset.width, link.asset.height, link.asset.origin) == (1200, 1600, "generated")

    @needs_browser
    def test_comic_strip_edition(self, ws, store):
        row = _install(ws, "comic-strip-edition")
        post = _entry(ws, "article", "The chore coat", status="published", data={"body": "Canvas, pattern, wax, done."})
        self._with_hero(ws, store, post)
        ws.ai.reply_text(
            json.dumps({"title": "The Chore Coat", "caption1": "Canvas.", "caption2": "Pattern.", "caption3": "Wax.", "caption4": "Done."})
        )

        run_automation_now(ws.session, ws.gid, row, recorder=ExecutionRecorder(ws.session, ws.gid))
        self._decide(ws)

        (link,) = self._role(ws, post, "comic")
        assert (link.asset.width, link.asset.height) == (1200, 1400)

    @needs_browser
    def test_before_after_slider_kit(self, ws, store):
        from marvin.db.models.platform import Assets, AssetTags, Tags

        row = _install(ws, "before-after-slider-kit")
        before = self._picture_asset(ws, store, "lantern-before", _picture((800, 600), color=(90, 80, 70)))
        after = self._picture_asset(ws, store, "lantern-after", _picture((800, 600), color=(200, 160, 60)))
        after.origin, after.source_asset_id = "derived", before.id
        tag = Tags(session=ws.session, group_id=ws.gid, name="compare", slug="compare")
        ws.session.add(tag)
        ws.session.flush()
        ws.session.add(AssetTags(asset_id=after.id, tag_id=tag.id))
        ws.session.commit()

        assert run_automation_now(ws.session, ws.gid, row, recorder=ExecutionRecorder(ws.session, ws.gid))["ok"]

        ws.session.expire_all()
        (pair,) = [
            a for a in ws.session.query(Assets).filter(Assets.group_id == ws.gid) if (a.metadata_json or {}).get("render_template") == "side-by-side"
        ]
        assert (pair.width, pair.height, pair.source_asset_id) == (1600, 900, before.id)
        assert pair.metadata_json["rendered_from"] == {"left": str(before.id), "right": str(after.id)}

    # ── gathered items (a collect step: many → one) and relative dates ──
    def _aged(self, ws, entry, *, published=None, updated=None):
        """Back-date an entry: published and/or last updated that many days ago."""
        if published is not None:
            entry.published_at = datetime.now(UTC) - timedelta(days=published)
        if updated is not None:
            entry.update_at = (datetime.now(UTC) - timedelta(days=updated)).replace(tzinfo=None)  # naive UTC, like the column
        ws.session.commit()
        return entry

    def _issues(self, ws):
        from marvin.db.models.platform import Entries

        ws.session.expire_all()
        return ws.session.query(Entries).filter_by(group_id=ws.gid, entry_type_id=ws.types["newsletter-issue"]).all()

    def _tagged(self, ws, slug, assets):
        from marvin.db.models.platform import AssetTags, Tags

        tag = Tags(session=ws.session, group_id=ws.gid, name=slug, slug=slug)
        ws.session.add(tag)
        ws.session.flush()
        ws.session.add_all(AssetTags(asset_id=a.id, tag_id=tag.id) for a in assets)
        ws.session.commit()

    def _rendered(self, ws, template):
        from marvin.db.models.platform import Assets

        ws.session.expire_all()
        rows = ws.session.query(Assets).filter(Assets.group_id == ws.gid).all()
        return [a for a in rows if (a.metadata_json or {}).get("render_template") == template]

    def _run(self, ws, row, trigger_kind="manual"):
        recorder = ExecutionRecorder(ws.session, ws.gid)
        result = run_automation_now(ws.session, ws.gid, row, user_id=ws.uid, recorder=recorder, trigger_kind=trigger_kind)
        assert result["ok"], [a.error for r in _runs(ws, row.slug) for a in r.actions if a.error]

    def test_weekly_digest(self, ws):
        from zoneinfo import ZoneInfo

        from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
        from marvin.services.automation.workflows import sync_schedule

        row = _install(ws, "weekly-digest")
        sync_schedule(ws.session, ws.gid, row)
        task = ws.session.query(ScheduledTaskModel).filter_by(group_id=ws.gid, slug=f"wf-{row.id}").one()
        next_run = task.next_run_at if task.next_run_at.tzinfo else task.next_run_at.replace(tzinfo=UTC)  # SQLite drops the zone
        local = next_run.astimezone(ZoneInfo("America/New_York"))
        assert (local.weekday(), local.hour, local.minute) == (0, 9, 0)  # the cron runs Mondays at 9:00 in the workspace's zone
        for title, days in (("Brass lantern", 2), ("Chore coat", 5), ("Old loom", 20)):
            self._aged(ws, _entry(ws, "article", title, status="published", data={"body": f"All about the {title.lower()}."}), published=days)
        _entry(ws, "article", "Unfinished", data={"body": "x"})
        ws.ai.reply_text(json.dumps({"title": "This week: lanterns and coats", "body": "Two pieces this week: the lantern and the coat. " * 2}))

        self._run(ws, row, trigger_kind="schedule")

        prompt = ws.ai.last_request()
        assert "Brass lantern" in prompt and "All about the chore coat." in prompt  # titles and their text
        assert "Old loom" not in prompt and "Unfinished" not in prompt  # older than 7 days; not published
        (issue,) = self._issues(ws)
        assert (issue.title, issue.status) == ("This week: lanterns and coats", "draft") and issue.data_json["body"].startswith("Two pieces")
        ws.session.delete(task)
        ws.session.commit()

    def test_release_notes_compiler(self, ws):
        row = _install(ws, "release-notes-compiler")
        self._aged(ws, _entry(ws, "article", "New pattern library", data={"body": "x"}, summary="Patterns for coats"), updated=3)
        self._aged(ws, _entry(ws, "article", "Fixed sizing chart", status="published", data={"body": "x"}), updated=10)
        self._aged(ws, _entry(ws, "article", "Ancient change", data={"body": "x"}), updated=40)
        ws.ai.reply_text(json.dumps({"title": "Release notes", "body": "New: the pattern library.\nFixed: the sizing chart."}))

        self._run(ws, row)

        prompt = ws.ai.last_request()
        assert "New pattern library" in prompt and "Patterns for coats" in prompt and "Fixed sizing chart" in prompt
        assert "Ancient change" not in prompt  # changed before -14d
        (notes,) = self._issues(ws)
        assert notes.status == "draft" and notes.data_json["body"].startswith("New: the pattern library")

    def test_personal_project_radar(self, ws):
        row = _install(ws, "personal-project-radar")
        stalled = self._aged(ws, _entry(ws, "project", "Brass lantern", data={"stage": "wiring"}), updated=20)
        moving = _entry(ws, "project", "Chore coat", data={"stage": "cutting"})
        done = self._aged(ws, _entry(ws, "project", "Old loom", status="published", data={"stage": "complete"}), updated=60)
        ws.ai.reply_text(json.dumps({"actions": "Buy a bulb holder; solder the leads."}))

        self._run(ws, row, trigger_kind="schedule")

        assert len(ws.ai.requests) == 1  # only the stalled draft
        stalled = _reload(ws, stalled)
        assert stalled.status == "needs_review"
        assert stalled.metadata_json["review_reasons"] == ["Stalled for two weeks — next: Buy a bulb holder; solder the leads."]
        assert (_reload(ws, moving).status, _reload(ws, done).status) == ("draft", "published")

    def test_evergreen_resurfacer(self, ws):
        row = _install(ws, "evergreen-resurfacer")
        for title, published, updated in (("Waxing canvas", 500, 400), ("Engraving brass", 420, 30), ("This spring", 90, 90)):
            self._aged(ws, _entry(ws, "article", title, status="published", data={"body": "x"}), published=published, updated=updated)
        ws.ai.reply_text(json.dumps({"title": "Pieces to refresh", "body": "Waxing canvas: the new wax. Engraving brass: new photos."}))

        self._run(ws, row, trigger_kind="schedule")

        prompt = ws.ai.last_request()
        assert prompt.index("Waxing canvas") < prompt.index("Engraving brass")  # the least recently touched first
        assert "This spring" not in prompt  # published within the year
        (draft,) = self._issues(ws)
        assert (draft.title, draft.status) == ("Pieces to refresh", "draft")

    def test_series_index_keeper(self, ws):
        from marvin.db.models.platform import Collections
        from marvin.db.models.platform.entry_collections import EntryCollections

        _install(ws, "series-index-keeper")
        index = _entry(ws, "article", "Series index", status="published", data={"body": "(empty)"})
        index.slug = "series-index"
        series = ws.session.query(Collections).filter_by(group_id=ws.gid, slug="featured").one()
        parts = {}
        for title, order, status in (("Part two", 1, "published"), ("Part one", 0, "published"), ("Part three", 2, "draft")):
            parts[title] = _entry(ws, "article", title, status=status, data={"body": "x"})
            ws.session.add(EntryCollections(entry_id=parts[title].id, collection_id=series.id, sort_order=order))
        outsider = _entry(ws, "article", "Unrelated", status="published", data={"body": "x"})
        ws.session.commit()

        _fire(ws, "entry_published", _entry_doc(outsider), entity=outsider.id, entity_type="entry", correlation_id="p-out")
        assert _reload(ws, index).data_json["body"] == "(empty)"  # not a member: nothing to refresh
        _fire(ws, "entry_published", _entry_doc(parts["Part two"]), entity=parts["Part two"].id, entity_type="entry", correlation_id="p-2")

        lines = _reload(ws, index).data_json["body"].splitlines()
        assert [line.split(" (")[0] for line in lines] == ["- Part one", "- Part two"]  # the series' order; the draft waits
        assert lines[0].endswith(f"(/articles/{parts['Part one'].slug})")

    def test_knowledge_gap_finder(self, ws):
        from marvin.db.models.platform import Collections
        from marvin.db.models.platform.entry_collections import EntryCollections

        row = _install(ws, "knowledge-gap-finder")
        featured = ws.session.query(Collections).filter_by(group_id=ws.gid, slug="featured").one()
        for title, status in (("Waxing canvas", "published"), ("Setting rivets", "published"), ("Unfinished idea", "draft")):
            entry = _entry(ws, "article", title, status=status, data={"body": "x"}, summary=f"How to {title.lower()}")
            ws.session.add(EntryCollections(entry_id=entry.id, collection_id=featured.id))
        _entry(ws, "article", "Elsewhere", status="published", data={"body": "x"})
        ws.session.commit()
        ws.ai.reply_text(json.dumps({"title": "Featured: what's missing", "body": "Caring for leather: the pieces cover canvas and metal only."}))

        self._run(ws, row)

        prompt = ws.ai.last_request()
        assert "How to waxing canvas" in prompt and "Setting rivets" in prompt and "Featured" in prompt
        assert "Unfinished idea" not in prompt and "Elsewhere" not in prompt
        (backlog,) = self._issues(ws)
        assert (backlog.title, backlog.status) == ("Featured: what's missing", "draft")

    def test_project_milestone_report(self, ws):
        from marvin.db.models.platform.entry_resources import EntryResources

        _install(ws, "project-milestone-report")
        lantern = _entry(ws, "project", "Brass lantern", data={"stage": "complete"})
        coat = _entry(ws, "project", "Chore coat", data={"stage": "cutting"})
        for title, project, body in (
            ("Cutting the shade", lantern, "Cut the brass shade from a 0.5 mm sheet."),
            ("Wiring day", lantern, "Soldered the leads; the bulb holder was too deep."),
            ("Pattern drafting", coat, "Drafted the coat's back panel."),
        ):
            _entry(ws, "article", title, status="published", data={"body": body, "project": project.slug})
        supplier = _resource(ws, "Brass sheet supply")
        ws.session.add(EntryResources(entry_id=lantern.id, resource_id=supplier.id))
        ws.session.commit()
        ws.ai.reply_text(
            json.dumps({"title": "Brass lantern: done", "body": "The lantern is finished: a cut brass shade, rewired after one setback."})
        )

        for correlation_id in ("u1", "u2"):  # a later save of the finished project doesn't report again
            _fire(
                ws,
                "entry_updated",
                _entry_doc(lantern, changed_fields=["data_json"]),
                entity=lantern.id,
                entity_type="entry",
                correlation_id=correlation_id,
            )

        prompt = ws.ai.last_request()
        assert prompt.index("Cut the brass shade") < prompt.index("Soldered the leads")  # its log, oldest first
        assert "Brass sheet supply" in prompt and "back panel" not in prompt  # its materials; not another project's log
        (report,) = self._issues(ws)
        assert (report.title, report.status, len(ws.ai.requests)) == ("Brass lantern: done", "draft", 1)
        assert _reload(ws, lantern).metadata_json["reported"] is True
        ws.session.query(EntryResources).filter_by(resource_id=supplier.id).delete()
        ws.session.delete(supplier)  # resources aren't swept with the workspace's entries
        ws.session.commit()

    def test_living_resource_collection(self, ws):
        from marvin.db.models.platform import Resources
        from marvin.db.models.platform.entry_resources import EntryResources

        _install(ws, "living-resource-collection")
        supplier = _resource(ws, "Brass supply", description="Now ships 0.8 mm sheet only.", url="https://brass.example")
        users = [
            _entry(ws, "article", "Cutting the shade", status="published", data={"body": "I used the 0.5 mm sheet from Brass supply."}),
            _entry(ws, "article", "Wiring day", data={"body": "Brass supply's thin sheet bends by hand."}),
        ]
        _entry(ws, "article", "Pattern drafting", data={"body": "Nothing about brass."})
        unused = _resource(ws, "Canvas mill")
        ws.session.add_all(EntryResources(entry_id=e.id, resource_id=supplier.id) for e in users)
        ws.session.commit()
        ws.ai.reply_text(json.dumps({"title": "Brass supply changed: 2 passages", "body": "“the 0.5 mm sheet” → “the 0.8 mm sheet”."}))

        _fire(ws, "resource_updated", {"resource_id": str(unused.id)}, entity=unused.id, entity_type="resource", correlation_id="r0")
        assert ws.ai.requests == []  # nothing uses it: no AI call, no draft
        _fire(ws, "resource_updated", {"resource_id": str(supplier.id)}, entity=supplier.id, entity_type="resource", correlation_id="r1")

        prompt = ws.ai.last_request()
        assert "Now ships 0.8 mm sheet only." in prompt and "I used the 0.5 mm sheet" in prompt and "bends by hand" in prompt
        assert "Nothing about brass" not in prompt
        (draft,) = self._issues(ws)
        assert (draft.title, draft.status) == ("Brass supply changed: 2 passages", "draft")
        ws.session.query(EntryResources).filter(EntryResources.resource_id == supplier.id).delete()
        ws.session.query(Resources).filter(Resources.group_id == ws.gid).delete(synchronize_session=False)
        ws.session.commit()

    def test_duplicate_asset_scout(self, ws):
        from marvin.db.models.platform import Assets

        _install(ws, "duplicate-asset-scout")
        first, again, new = _asset(ws, "lantern-photo"), _asset(ws, "lantern-photo-copy"), _asset(ws, "coat-photo")
        first.checksum = again.checksum = "a" * 64  # the same file, uploaded twice
        ws.session.commit()

        for asset in (new, again):
            _fire(ws, "asset_uploaded", {"asset_id": str(asset.id)}, entity=asset.id, entity_type="asset", correlation_id=f"up-{asset.slug}")

        (sent,) = ws.providers["apprise"].calls  # the re-upload only
        assert sent["title"] == "“lantern-photo-copy” is already in the library"
        assert "lantern-photo" in sent["body"] and "lantern-photo-copy" not in sent["body"].split("\n")[1]  # the other one, not itself
        assert first.id  # kept: the scout never trashes anything
        ws.session.query(Assets).filter(Assets.group_id == ws.gid).delete(synchronize_session=False)
        ws.session.commit()

    def test_entry_schema_impact_report(self, ws):
        _install(ws, "entry-schema-impact-report")
        _entry(ws, "article", "Complete piece", status="published", data={"body": "All here."})
        _entry(ws, "article", "Missing its body", status="published", data={"project": "lantern"})  # body is required
        _entry(ws, "project", "A project", data={})  # another type: not checked
        changed = {"entry_type_slug": "article", "entry_type_name": "Article", "entry_type_id": str(ws.types["article"])}

        _fire(ws, "entry_type_updated", changed, correlation_id="et1")

        (sent,) = ws.providers["apprise"].calls
        assert sent["title"] == "1 “Article” entries don't pass its rules now"
        assert "- Missing its body — Field 'body': Required field is missing or null" in sent["body"]
        assert "Complete piece" not in sent["body"]

    def test_surprise_remix_button(self, ws):
        from marvin.services.automation.inputs import RunInputError

        row = _install(ws, "surprise-remix-button")
        lantern = _entry(ws, "article", "Brass lantern", status="published", data={"body": "Cut, soldered, lit."})
        ws.ai.reply_text(json.dumps({"title": "Lantern, in five lines", "body": "A sheet of brass, a careful cut..."}))

        with pytest.raises(RunInputError, match="one of a haiku, a limerick"):  # only the forms set up
            run_automation_now(ws.session, ws.gid, row, user_id=ws.uid, inputs={"piece": lantern.slug, "remix": "a sonnet"})
        self._run_with(ws, row, {"piece": lantern.slug, "remix": "a limerick"})

        prompt = ws.ai.last_request()
        assert "Brass lantern" in prompt and "as a limerick" in prompt
        (draft,) = self._issues(ws)
        assert (draft.title, draft.status, draft.metadata_json["remix_of"]) == ("Lantern, in five lines", "draft", lantern.slug)

    def _run_with(self, ws, row, inputs):
        recorder = ExecutionRecorder(ws.session, ws.gid)
        assert run_automation_now(ws.session, ws.gid, row, user_id=ws.uid, recorder=recorder, inputs=inputs)["ok"]

    # ── reading the web (a fetch step; the web is faked at the guarded client) ──
    def test_broken_link_patrol(self, ws, monkeypatch):
        row = _install(ws, "broken-link-patrol")
        body = "Bought from [the shop](https://shop.example/brass) — see https://gone.example/guide and <a href='https://shop.example/old'>this</a>."
        broken = _entry(ws, "article", "Brass lantern", status="published", data={"body": body})
        fine = _entry(ws, "article", "Chore coat", status="published", data={"body": "All at https://shop.example/brass."})
        _entry(ws, "article", "Unfinished", data={"body": "https://gone.example/draft"})  # a draft isn't patrolled
        calls = _web(monkeypatch, {"https://shop.example/brass": (200, "text/html", ""), "https://shop.example/old": (404, "text/html", "")})

        self._run(ws, row, trigger_kind="schedule")

        assert "https://gone.example/draft" not in {url for _, url in calls}
        assert _reload(ws, broken).metadata_json["broken_links"] == 2
        assert "broken_links" not in (_reload(ws, fine).metadata_json or {})  # a clean entry is never written to
        (sent,) = ws.providers["apprise"].calls  # only the entry with broken links
        assert sent["title"] == "Broken links in “Brass lantern”" and sent["body"].splitlines()[:3] == [
            "2 of 3 links don't work:",
            "- https://gone.example/guide — no answer (ConnectionRefusedError: connection refused)",
            "- https://shop.example/old — 404",
        ]

        edited = _reload(ws, broken).update_at
        self._run(ws, row, trigger_kind="schedule")  # next week, the same answer: nothing saved, nothing "updated"
        assert _reload(ws, broken).update_at == edited

    def test_resource_availability_watch(self, ws, monkeypatch):
        from marvin.db.models.platform import Resources

        row = _install(ws, "resource-availability-watch")
        for name, url in (
            ("Brass supply", "https://brass.example/sheet"),
            ("Canvas mill", "https://canvas.example/waxed"),
            ("Rivet shop", "https://rivets.example/copper"),
            ("Local smith", None),  # no page to check
        ):
            _resource(ws, name, url=url)
        ws.session.commit()
        _web(
            monkeypatch,
            {
                "https://brass.example/sheet": (200, "text/html", "<title>Brass sheet</title> In stock"),
                "https://canvas.example/waxed": (200, "text/html", "<title>Waxed canvas</title> SOLD OUT"),
            },
        )

        self._run(ws, row, trigger_kind="schedule")

        sent = sorted(c["title"] for c in ws.providers["apprise"].calls)
        assert sent == ["Check “Canvas mill”", "Check “Rivet shop”"]  # says sold out; no answer
        ws.session.query(Resources).filter(Resources.group_id == ws.gid).delete(synchronize_session=False)
        ws.session.commit()

    # ── checking a document against a schema (a schema_check step) ──
    def test_agent_directory_intake(self, ws, monkeypatch):
        _install(ws, "agent-directory-intake")
        good_url, bad_url = "https://agents.example/scribe.json", "https://agents.example/broken.json"
        _web(
            monkeypatch,
            {
                good_url: (200, "application/json", json.dumps({"name": "Scribe", "url": "https://scribe.example", "capabilities": ["summarise"]})),
                bad_url: (200, "application/json", json.dumps({"name": "Broken", "url": "http://insecure.example"})),
            },
        )
        good = _entry(ws, "contact-request", "Scribe", status="inbox", data={"message": good_url})
        bad = _entry(ws, "contact-request", "Broken", status="inbox", data={"message": bad_url})
        gone = _entry(ws, "contact-request", "Gone", status="inbox", data={"message": "https://nowhere.example/agent.json"})
        for n, request in enumerate((good, bad, gone)):
            doc = _entry_doc(request, form_name="Agents", flagged=False, duplicate=False, submission_data=request.data_json)
            _fire(ws, "form_submission_received", doc, entity=request.id, entity_type="entry", correlation_id=f"corr-agent-{n}")

        fits, misses, unread = (_reload(ws, e) for e in (good, bad, gone))
        assert (fits.status, misses.status, unread.status) == ("needs_review",) * 3
        assert fits.metadata_json["capability_check"]["valid"] is True
        assert fits.metadata_json["review_reasons"] == ["Capability document fits the schema — ready for a look"]
        check = misses.metadata_json["capability_check"]
        assert check["valid"] is False and check["fetched_status"] == 200 and check["error_count"] == 2
        assert {e["path"] for e in check["errors"]} == {"$", "$.url"}  # a missing field, an address that isn't https
        assert misses.metadata_json["review_reasons"][0].startswith("Capability document doesn't fit the schema (2 problems):\n- $")
        assert unread.metadata_json["capability_check"]["valid"] is False and unread.metadata_json["capability_check"]["fetched_status"] == 0
        sent = {c["title"]: c["body"] for c in ws.providers["apprise"].calls}
        assert sorted(sent) == ["Agent submission: Broken", "Agent submission: Gone", "Agent submission: Scribe"]
        assert "fits the schema: True" in sent["Agent submission: Scribe"] and "fits the schema: False" in sent["Agent submission: Broken"]

        # A second delivery of the same submission (a retried event) reads the same answer and leaves the review as it was.
        doc = _entry_doc(good, form_name="Agents", flagged=False, duplicate=False, submission_data=good.data_json)
        _fire(ws, "form_submission_received", doc, entity=good.id, entity_type="entry", correlation_id="corr-agent-0")
        assert _reload(ws, good).metadata_json["review_reasons"] == ["Capability document fits the schema — ready for a look"]
        assert _reload(ws, good).metadata_json["capability_check"]["valid"] is True

    def test_choose_your_own_adventure(self, ws):
        from marvin.db.models.platform import Entries

        row = _install(ws, "choose-your-own-adventure")
        premise = _entry(ws, "article", "A lighthouse at the edge of the map", status="published", data={"body": "Who keeps the light?"})
        story = {
            "text": "You wake in the lamp room; the lens is dark and a storm is coming.",
            "choices": [
                {"label": "Relight the lamp", "next": {"text": "The beam sweeps out and a ship answers.", "ending": "A ship is saved"}},
                {
                    "label": "Climb down to the cellar",
                    "next": {
                        "text": "The cellar door hangs open; something knocks below.",
                        "choices": [
                            {"label": "Answer the knock", "next": {"text": "A drowned keeper hands you a key.", "ending": "You inherit the light"}},
                            {"label": "Bolt the door", "next": {"text": "Dawn finds you alive and very alone.", "ending": "A quiet morning"}},
                        ],
                    },
                },
            ],
        }
        dead_end = {
            **story,
            "choices": [story["choices"][0], {"label": "Walk into the sea", "next": {"text": "The water is cold and the story stops."}}],
        }

        def adventures():
            ws.session.expire_all()
            return (
                ws.session.query(Entries).filter(Entries.group_id == ws.gid, Entries.metadata_json["adventure_of"].as_string() == premise.slug).all()
            )

        def run(answer):
            ws.ai.reply_text(json.dumps({"title": "The Lamp Room", "story_json": json.dumps(answer)}))
            recorder = ExecutionRecorder(ws.session, ws.gid)
            return run_automation_now(ws.session, ws.gid, row, user_id=ws.uid, recorder=recorder, inputs={"premise": premise.slug})

        assert run(story)["ok"]
        (draft,) = adventures()
        assert (draft.title, draft.status, draft.metadata_json["story_check"]) == ("The Lamp Room", "draft", {"valid": True})
        assert json.loads(draft.data_json["body"]) == story  # saved as written

        # A story with a branch that never ends stops the run at the check: nothing is drafted, and the message names the branch.
        assert not run(dead_end)["ok"]
        failed = [a.error for r in _runs(ws, row.slug) for a in r.actions if a.error]
        assert any("$.choices[1].next" in e and "'choices' is a required property" in e for e in failed), failed
        assert len(adventures()) == 1

        assert run(story)["ok"]  # run again: another draft, the premise is untouched
        assert len(adventures()) == 2 and "adventure_of" not in (_reload(ws, premise).metadata_json or {})

    @needs_browser
    def test_best_of_month(self, ws, store):
        row = _install(ws, "best-of-month")
        lantern = self._aged(ws, _entry(ws, "article", "Brass lantern", status="published", data={"body": "x"}), published=3)
        coat = self._aged(ws, _entry(ws, "article", "Chore coat", status="published", data={"body": "x"}), published=10)
        heroes = [self._with_hero(ws, store, e) for e in (lantern, coat)]
        self._with_hero(ws, store, self._aged(ws, _entry(ws, "article", "Last spring", status="published", data={"body": "x"}), published=60))
        self._aged(ws, _entry(ws, "article", "No picture", status="published", data={"body": "x"}), published=1)

        self._run(ws, row, trigger_kind="schedule")

        (sheet,) = self._rendered(ws, "grid")
        assert (sheet.width, sheet.height) == (1600, 1600) and [t.slug for t in sheet.tags] == ["best-of-month"]
        assert sheet.metadata_json["rendered_from"] == {"tiles": [str(h.id) for h in heroes]}  # newest first; the month's pictures only

    @needs_browser
    def test_contact_sheet_maker(self, ws, store):
        row = _install(ws, "contact-sheet-maker")
        shots = [self._picture_asset(ws, store, f"shot-{i}", _picture((600, 400), color=(60 * i, 90, 120))) for i in range(3)]
        crop = self._picture_asset(ws, store, "shot-0-square", _picture((400, 400)))
        crop.origin, crop.source_asset_id = "derived", shots[0].id
        self._picture_asset(ws, store, "untagged", _picture())
        self._tagged(ws, "brand", [*shots, crop])

        self._run(ws, row)

        (sheet,) = self._rendered(ws, "grid")
        assert sorted(sheet.metadata_json["rendered_from"]["tiles"]) == sorted(str(s.id) for s in shots)  # a version stays out
        assert [t.slug for t in sheet.tags] == ["contact-sheet"]

    @needs_browser
    def test_color_moodboard(self, ws, store):
        import re

        row = _install(ws, "color-moodboard")
        sea = self._picture_asset(ws, store, "sea", _picture((600, 600), color=(20, 60, 140)))
        sand = self._picture_asset(ws, store, "sand", _picture((600, 600), color=(220, 190, 120)))
        self._tagged(ws, "brand", [sea, sand])
        ws.ai.reply_text(json.dumps({"notes": "Cool sea blues against warm sand: calm, sunlit, a little weathered."}))

        self._run(ws, row)

        prompt = ws.ai.last_request()
        assert "sea" in prompt and "sand" in prompt and re.search(r"#[0-9a-f]{6}", prompt)  # the pictures and the collage's palette
        (collage,) = self._rendered(ws, "grid")
        (board,) = self._rendered(ws, "moodboard")
        assert (collage.width, collage.height, board.width, board.height) == (1200, 1200, 1600, 1200)
        assert sorted(board.metadata_json["rendered_from"]["tiles"]) == sorted([str(sea.id), str(sand.id)])


# ── A dry run previews what an AI step's answer feeds ────────────────────────
# The AI isn't called in a dry run, so a custom step's answer is a stand-in (‹AI answer: key›) and the steps after it —
# a create's title, a render's text — preview as they will run instead of failing on an empty value.
def _dry(ws, rid: str) -> dict:
    row = _install(ws, rid)
    return run_automation_now(ws.session, ws.gid, row, user_id=ws.uid, dry_run=True)


def _step_errors(plan) -> list:
    return [(p.get("label") or p.get("kind"), p.get("error")) for p in plan if p.get("error")]


def test_a_dry_run_previews_a_create_fed_by_an_ai_step(ws):
    from marvin.db.models.platform import Collections
    from marvin.db.models.platform.entry_collections import EntryCollections

    featured = ws.session.query(Collections).filter_by(group_id=ws.gid, slug="featured").one()
    piece = _entry(ws, "article", "Waxing canvas", status="published", data={"body": "x"})
    ws.session.add(EntryCollections(entry_id=piece.id, collection_id=featured.id))
    ws.session.commit()

    result = _dry(ws, "knowledge-gap-finder")

    assert result["ok"], _step_errors(result["plan"])
    create = result["plan"][-1]["resolved"]
    assert (create["title"], create["data"]) == ("‹AI answer: title›", {"body": "‹AI answer: body›"})
    assert ws.ai.requests == []  # previewed, not asked


def test_a_dry_run_of_a_scheduled_digest_and_an_event_recipe_passes(ws):
    from marvin.services.automation.context import event_context
    from marvin.services.automation.engine import dry_run_for_event

    self_published = _entry(ws, "article", "Vector clocks", status="published", data={"body": "Lamport timestamps."})
    self_published.published_at = datetime.now(UTC) - timedelta(days=1)
    ws.session.commit()
    assert _dry(ws, "weekly-digest")["ok"]

    row = _install(ws, "ada-explains-it")
    ctx = event_context("entry_published", _entry_doc(self_published), entity_id=self_published.id, entity_type="entry", correlation_id="dry")
    preview = dry_run_for_event(ws.session, ws.gid, row, ctx)
    assert preview["would_fire"] and _step_errors(preview["plan"]) == []
    assert preview["plan"][-1]["resolved"]["title"] == "‹AI answer: title›"


def test_a_dry_run_of_the_achievement_cabinet_previews_the_badge_and_the_event_that_sends_it(ws, monkeypatch):
    from marvin.db.models.platform import Entries
    from marvin.services.automation.engine import dry_run_for_event
    from marvin.services.event_bus_service.event_bus_service import EventBusService

    monkeypatch.setattr(EventBusService, "dispatch", lambda self, **kw: pytest.fail("a dry run sent an event"))
    lantern = _entry(ws, "project", "Brass lantern", status="published")
    row = _install(ws, "achievement-cabinet")
    doc = {"event_name": "milestone", "payload": {"milestone": "Shipped", "badge": "First release"}, "workspace_id": str(ws.gid)}
    ctx = event_context("custom.milestone", doc, entity_id=lantern.id, entity_type="entry", correlation_id="dry")

    preview = dry_run_for_event(ws.session, ws.gid, row, ctx)

    assert preview["would_fire"] and _step_errors(preview["plan"]) == []
    create = next(p for p in preview["plan"] if p.get("kind") == "entry" and p["resolved"].get("title"))["resolved"]
    assert create["title"] == "First release" and create["data"] == {"body": "Brass lantern reached “Shipped”."}
    assert ws.session.query(Entries).filter_by(group_id=ws.gid, title="First release").count() == 0  # previewed, not made

    sender = _install_workflow(
        ws, "sender", "entry_updated", [{"kind": "emit_event", "event": "custom.milestone", "payload": {"badge": "B", "milestone": "M"}}]
    )
    result = run_automation_now(ws.session, ws.gid, sender, user_id=ws.uid, dry_run=True)
    assert result["ok"], _step_errors(result["plan"])
    assert result["plan"][0]["resolved"]["payload"] == {"badge": "B", "milestone": "M"}


def test_a_dry_run_of_the_schema_recipes_checks_nothing_it_cant_have(ws, monkeypatch):
    from marvin.services.automation.engine import dry_run_for_event

    calls = _web(monkeypatch, {})
    request = _entry(ws, "contact-request", "Scribe", status="inbox", data={"message": "https://agents.example/scribe.json"})
    row = _install(ws, "agent-directory-intake")
    ctx = event_context(
        "form_submission_received", _entry_doc(request, form_name="Agents"), entity_id=request.id, entity_type="entry", correlation_id="dry"
    )
    preview = dry_run_for_event(ws.session, ws.gid, row, ctx)
    assert preview["would_fire"] and _step_errors(preview["plan"]) == [] and calls == []  # the page wasn't fetched, so nothing was judged
    assert preview["plan"][1]["resolved"]["valid"] is None

    premise = _entry(ws, "article", "A lighthouse", status="published", data={"body": "x"})
    adventure = _install(ws, "choose-your-own-adventure")
    result = run_automation_now(ws.session, ws.gid, adventure, user_id=ws.uid, dry_run=True, inputs={"premise": premise.slug})
    assert result["ok"], _step_errors(result["plan"])  # the AI wasn't asked: its stand-in isn't a story to fail on
    assert ws.ai.requests == [] and result["plan"][1]["resolved"]["valid"] is None
    assert result["plan"][-1]["resolved"]["title"] == "‹AI answer: title›"


def test_a_dry_run_fills_a_render_from_an_ai_step_without_a_browser(ws, monkeypatch):
    monkeypatch.setattr(render, "screenshot", lambda *a, **k: pytest.fail("a dry run took a screenshot"))
    _entry(ws, "project", "Chore coat", status="published", data={"stage": "complete"})
    result = _dry(ws, "future-newspaper")
    assert result["ok"], _step_errors(result["plan"])


def test_see_nothing_means_the_prompt_alone():
    from marvin.services.ai.operations.custom import DEFAULT_SEE, CustomOperation

    assert CustomOperation(see=()).see == () and CustomOperation(see=None).see == DEFAULT_SEE == ("item",)


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
    index = authoring_guide(ws.session, ws.gid)
    assert index["workspace"]["recipes_ready"] == len(WORKFLOW_RECIPES) and "examples" in index["sections"]  # the list is a call away

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
    assert "status is needs-engine-capability" in authoring_guide(ws.session, ws.gid, "examples", "reply-drafting-desk")["examples"]["error"]


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
    out = _tool(ws, "draft_workflow", {"recipe": "reply-drafting-desk", "vars": {}})
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


def test_a_workspace_type_and_a_built_in_with_the_same_slug_are_listed_once(ws):
    """The pickers (Library setup, the editor) offered "article" twice when the workspace had its own copy of a built-in."""
    from marvin.db.models.platform import EntryTypes

    built_in = EntryTypes(session=ws.session, group_id=None, name="Article (built-in)", slug="article", schema_json={"fields": [_field("headline")]})
    ws.session.add(built_in)
    ws.session.commit()
    try:
        articles = [t for t in workspace_refs(ws.session, ws.gid).entry_types if t["slug"] == "article"]
        assert len(articles) == 1 and articles[0]["fields"] == ["body", "project"]  # the workspace's own, as a step resolves it
    finally:
        ws.session.delete(built_in)
        ws.session.commit()
