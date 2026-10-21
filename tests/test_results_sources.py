# ruff: noqa: F811  (the `workspace` fixture is imported and extended)
"""Automation results from Cloudflare Pages builds and Buttondown sends, end to end, through the real plugins.

The plugins' own blueprints are applied the way the integration card applies them (so the workflows, the incoming webhooks and the
"installed by" connection are the shipped ones), the provider calls go to a stub HTTP client, and the engine and the event bus are the
real ones:

* a site rebuild runs the Cloudflare ``deploy`` action from its ``webhook_triggered`` subscription and records the build In flight;
  Cloudflare's started / success / failed notifications settle it, and a failure carries the build log tail;
* publishing a newsletter issue runs Buttondown's ``create_issue_email``: a send records In flight and ``email.sent`` settles it, a draft
  (and delivery off) records nothing.

Skipped when a plugin isn't installed (CI's test job has no plugin group).
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")
pytest.importorskip("marvin_integration_cloudflare_pages", reason="the Cloudflare Pages plugin is not installed")
pytest.importorskip("marvin_integration_buttondown", reason="the Buttondown plugin is not installed")

from marvin_integration_sdk import Response  # noqa: E402

from marvin.db.models.groups.automation_results import AutomationResultModel as Result  # noqa: E402
from marvin.db.models.groups.automations import WorkspaceAutomationModel  # noqa: E402
from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel  # noqa: E402
from marvin.db.models.groups.integration_event_subscriptions import IntegrationEventSubscriptionModel  # noqa: E402
from marvin.db.models.groups.integrations import IntegrationModel  # noqa: E402
from marvin.db.models.platform import Entries, EntryTypes  # noqa: E402
from marvin.services.automation.engine import run_automations_for_event  # noqa: E402
from marvin.services.automation.recorder import ExecutionRecorder  # noqa: E402
from marvin.services.blueprints.apply import apply_many, outdated  # noqa: E402
from marvin.services.blueprints.catalog import list_blueprints  # noqa: E402
from marvin.services.event_bus_service.event_bus_service import EventBusService  # noqa: E402
from marvin.services.scheduled_tasks.handlers.publishing import dispatch_site_rebuild  # noqa: E402
from marvin.services.site_rebuild import dispatch_due_rebuilds, request_rebuild  # noqa: E402
from tests.test_content_role_gates import workspace  # noqa: E402, F401  (the `workspace` fixture)

ACCOUNT, PROJECT = "acct-fake", "my-site"
TOKEN = "fake-cloudflare-token"  # a made-up credential, to prove it never reaches a result
DEPLOY_ID = "dep-0001"
DASHBOARD = f"https://dash.cloudflare.com/{ACCOUNT}/pages/view/{PROJECT}/{DEPLOY_ID}"
LOGS = {
    "result": {
        "data": [
            {"line": "Installing dependencies"},
            {"line": "npm ERR! missing script: build"},
            {"line": "Failed: build command exited with code: 1"},
        ]
    },
    "success": True,
}
# The same email, as Buttondown's API names it (a TypeID) and as its webhook most likely does (the UUID under it).
EMAIL_TYPEID, EMAIL_UUID = "em_01h455vb4pex5vsknk084sn02q", "01890a5d-ac96-774b-bcce-b302099a8057"


class _Http:
    """A stub HTTP client: ``routes`` are (method, url fragment, status, body); everything else is a 599 so a stray call is loud."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def _answer(self, method, url, body=None, data=None, headers=None):
        self.calls.append({"method": method, "url": url, "json": body})
        for route_method, needle, status, payload in self.routes:
            if route_method == method and needle in url:
                return Response(status_code=status, content=json.dumps(payload).encode())
        return Response(status_code=599, content=b'{"errors":[{"code":0,"message":"no stub route"}]}')

    def get(self, url, *, headers=None, timeout=15):
        return self._answer("GET", url, headers=headers)

    def post(self, url, *, json=None, data=None, headers=None, timeout=15):
        return self._answer("POST", url, json, data, headers)


DEPLOYMENT = {
    "id": DEPLOY_ID,
    "environment": "preview",
    "url": f"https://{DEPLOY_ID}.my-site.pages.dev",
    "deployment_trigger": {"metadata": {"branch": "develop", "commit_message": "Fix the feed\n\nA longer explanation."}},
}


def _sites_routes(deploy=(200, {"result": {"id": DEPLOY_ID, "url": f"https://{DEPLOY_ID}.my-site.pages.dev"}, "success": True})):
    return [
        ("GET", "/history/logs", 200, LOGS),
        # The success workflow reads the deployment itself for its Results line (deployment_summary).
        ("GET", f"/deployments/{DEPLOY_ID}", 200, {"result": DEPLOYMENT, "success": True}),
        ("GET", f"/pages/projects/{PROJECT}", 200, {"result": {"id": "proj-1", "production_branch": "main"}, "success": True}),
        ("POST", "/deployments", *deploy),
    ]


def _mail_routes(status="about_to_send"):
    return [
        ("GET", "/v1/emails?", 200, {"results": [], "count": 0}),
        ("POST", "/v1/emails", 201, {"id": EMAIL_TYPEID, "status": status, "absolute_url": "https://buttondown.com/n/archive/hello/"}),
    ]


@pytest.fixture
def world(db_session, workspace, monkeypatch):
    """A workspace with a Cloudflare Pages connection (its blueprints applied, workflows on, a deploy hook subscribed to a site
    rebuild), a Buttondown connection (issue workflow and email-sent workflow applied and on, delivery = send) and a published issue."""
    monkeypatch.setattr("marvin.services.secrets.resolver.resolve_secret", lambda ref, gid=None: TOKEN)
    http = SimpleNamespace(current=_Http([]))
    monkeypatch.setattr("marvin.services.integrations.build_http", lambda *a, **k: http.current)
    sent = []  # every event the bus was asked to send, whatever the listeners then did
    dispatch = EventBusService.dispatch

    def spy(self, *args, **kwargs):
        sent.append(kwargs.get("event_type") or args[2])
        return dispatch(self, *args, **kwargs)

    monkeypatch.setattr(EventBusService, "dispatch", spy)

    gid = workspace.gid
    pages = IntegrationModel(
        session=db_session,
        group_id=gid,
        provider="cloudflare_pages",
        name="Site builds",
        slug="pages",
        enabled=True,
        config={"account_id": ACCOUNT, "project_name": PROJECT},
        secret_ref="CF_TOKEN",
    )
    news = IntegrationModel(
        session=db_session,
        group_id=gid,
        provider="buttondown",
        name="Newsletter",
        slug="news",
        enabled=True,
        config={"issue_delivery": "send"},
        secret_ref="BD_KEY",
    )
    kind = EntryTypes(session=db_session, group_id=gid, name="Newsletter issue", slug="newsletter-issue", schema_json={"fields": []})
    kind.id = uuid.uuid4()
    db_session.add_all([pages, news, kind])
    db_session.flush()
    issue = Entries(
        session=db_session,
        group_id=gid,
        entry_type_id=kind.id,
        title="Notes from the studio",
        slug=f"notes-{gid.hex[:6]}",
        data_json={"body": "New: a blue work.", "preview": "Recent works"},
        status="published",
    )
    db_session.add(issue)
    db_session.flush()

    for provider, connection, only in (
        ("cloudflare_pages", pages, None),
        ("buttondown", news, {"buttondown", "buttondown-issue-on-publish", "buttondown-email-sent"}),
    ):
        blueprints = [b for b in list_blueprints(source=provider) if only is None or b.slug in only]
        applied = apply_many(db_session, gid, blueprints, integration_id=connection.id)
        assert all(r.created for r in applied), [(r.slug, r.detail) for r in applied]
    db_session.query(WorkspaceAutomationModel).filter_by(group_id=gid).update({"enabled": True})
    db_session.add(
        IntegrationEventSubscriptionModel(
            session=db_session, group_id=gid, integration_id=pages.id, event_type="webhook_triggered", action="deploy", args={}, enabled=True
        )
    )
    db_session.commit()
    return SimpleNamespace(ws=workspace, session=db_session, gid=gid, pages=pages, news=news, issue=issue, http=http, sent=sent)


def _rows(world, **where):
    world.session.expire_all()
    return world.session.query(Result).filter_by(group_id=world.gid, **where).order_by(Result.sent_at, Result.created_at).all()


def _rebuild(world):
    """A site rebuild, as the scheduler's tick sends it: queued, quiet for long enough, then ``webhook_triggered`` on the bus."""
    request_rebuild(world.session, world.gid, "content change: a post was published")
    bus = EventBusService(bg_tasks=None)
    dispatch_due_rebuilds(
        world.session,
        lambda gid, summary, changes, count: dispatch_site_rebuild(gid, summary, bus, changes=changes, request_count=count),
        now=datetime.now(UTC) + timedelta(hours=1),
    )
    world.session.expire_all()


def _hook(world, slug, payload):
    """What an incoming webhook delivers, run through the workflows that listen to it. Returns how many ran."""
    ran = run_automations_for_event(
        world.session,
        world.gid,
        {"event_type": "incoming_webhook", "webhook_slug": slug, "payload": payload, "user_id": None},
        recorder=ExecutionRecorder(world.session, world.gid),
    )
    world.session.expire_all()
    return ran


def _cloudflare(world, event, deployment_id=DEPLOY_ID):
    payload = {
        "data": {
            "event": event,
            "deployment_id": deployment_id,
            "project_name": PROJECT,
            "pages_dev_url": f"https://{deployment_id}.my-site.pages.dev",
        }
    }
    return _hook(world, "cloudflare-pages", payload)


def _publish(world):
    event = {"event_type": "entry_published", "entry_id": str(world.issue.id), "user_id": None}
    run_automations_for_event(world.session, world.gid, event, recorder=ExecutionRecorder(world.session, world.gid))
    world.session.expire_all()


# ── Cloudflare Pages: a site rebuild ─────────────────────────────────────────────────────────────────────────────


def test_a_site_rebuild_through_the_cloudflare_deploy_action_records_the_build_in_flight_with_its_deployment_id_and_dashboard_link(world):
    world.http.current = _Http(_sites_routes())

    _rebuild(world)

    (row,) = _rows(world)
    assert (row.status, row.action, row.remote_id, row.remote_url) == ("in_flight", "deploy", DEPLOY_ID, DASHBOARD)
    assert (row.integration_id, row.workflow_id, row.entry_id, row.finished_at) == (world.pages.id, None, None, None)
    assert [c["method"] for c in world.http.current.calls if "/deployments" in c["url"]] == ["POST"]  # the build was started once


def test_cloudflares_started_notification_leaves_the_build_in_flight(world):
    world.http.current = _Http(_sites_routes())
    _rebuild(world)

    assert _cloudflare(world, "EVENT_DEPLOYMENT_STARTED") == 1

    (row,) = _rows(world)
    assert (row.status, row.finished_at) == ("in_flight", None)


def test_cloudflares_success_notification_settles_the_build_succeeded(world):
    world.http.current = _Http(_sites_routes())
    _rebuild(world)
    _cloudflare(world, "EVENT_DEPLOYMENT_STARTED")

    assert _cloudflare(world, "EVENT_DEPLOYMENT_SUCCESS") == 1

    (row,) = _rows(world)  # the same record, not another
    assert (row.status, row.remote_id, row.message, row.dismissed_at) == ("succeeded", DEPLOY_ID, "Preview on develop: Fix the feed", None)
    assert row.finished_at is not None and row.workflow_id is None
    assert row.remote_url.startswith("https://dash.cloudflare.com/")  # the deploy's link to the build is kept, not replaced


def test_cloudflares_failure_notification_settles_the_build_failed_with_the_build_log_tail(world):
    world.http.current = _Http(_sites_routes())
    _rebuild(world)
    _cloudflare(world, "EVENT_DEPLOYMENT_STARTED")

    assert _cloudflare(world, "EVENT_DEPLOYMENT_FAILED") == 1

    (row,) = _rows(world)
    assert (row.status, row.remote_id) == ("failed", DEPLOY_ID)
    assert "Failed: build command exited with code: 1" in row.message and DASHBOARD in row.message  # what the toast shows
    assert row.finished_at is not None and TOKEN not in row.message


def test_a_started_notification_that_arrives_after_the_end_does_not_reopen_the_build(world):
    world.http.current = _Http(_sites_routes())
    _rebuild(world)
    _cloudflare(world, "EVENT_DEPLOYMENT_SUCCESS")

    _cloudflare(world, "EVENT_DEPLOYMENT_STARTED")  # deliveries aren't ordered

    (row,) = _rows(world)
    assert row.status == "succeeded"


def test_the_three_notification_workflows_still_emit_their_site_deployment_events(world):
    world.http.current = _Http(_sites_routes())

    for word in ("EVENT_DEPLOYMENT_STARTED", "EVENT_DEPLOYMENT_SUCCESS", "EVENT_DEPLOYMENT_FAILED"):
        _cloudflare(world, word)

    names = [getattr(e, "name", e) for e in world.sent]
    assert [n for n in names if n.startswith("site_deployment_")] == [
        "site_deployment_started",
        "site_deployment_completed",
        "site_deployment_failed",
    ]


def test_a_build_marvin_did_not_start_is_listed_from_its_first_notification_on_the_connection_that_installed_the_webhook(world):
    world.http.current = _Http(_sites_routes())

    _cloudflare(world, "EVENT_DEPLOYMENT_STARTED", deployment_id="dep-from-a-git-push")
    _cloudflare(world, "EVENT_DEPLOYMENT_SUCCESS", deployment_id="dep-from-a-git-push")

    (row,) = _rows(world)
    assert (row.status, row.remote_id, row.integration_id, row.target) == ("succeeded", "dep-from-a-git-push", world.pages.id, PROJECT)


def test_a_rebuild_whose_deploy_call_fails_records_a_failed_result_without_the_token(world):
    deny = (403, {"errors": [{"code": 10000, "message": f"Authentication error for {TOKEN}"}], "success": False})
    world.http.current = _Http(_sites_routes(deploy=deny))

    _rebuild(world)

    (row,) = _rows(world)
    assert (row.status, row.remote_id, row.workflow_id, row.action) == ("failed", None, None, "deploy")
    assert "create deployment failed" in row.message and TOKEN not in row.message
    assert row.finished_at is not None


def test_two_rebuilds_are_two_builds(world):
    for deployment in ("dep-a", "dep-b"):
        world.http.current = _Http(_sites_routes(deploy=(200, {"result": {"id": deployment}, "success": True})))
        _rebuild(world)

    assert [r.remote_id for r in _rows(world)] == ["dep-a", "dep-b"]


def test_the_applied_cloudflare_workflows_match_what_the_plugin_declares(world):
    blueprints = {b.slug: b for b in list_blueprints(source="cloudflare_pages") if b.kind == "workflow"}

    assert set(blueprints) == {"cloudflare-pages-deploy-started", "cloudflare-pages-deploy-succeeded", "cloudflare-pages-deploy-failed"}
    assert [outdated(world.session, world.gid, b) for b in blueprints.values()] == [False, False, False]


def test_the_webhook_the_plugin_applied_names_the_cloudflare_connection_as_its_installer(world):
    hook = world.session.query(WorkspaceIncomingWebhookModel).filter_by(group_id=world.gid, slug="cloudflare-pages").one()

    assert hook.source_integration_id == world.pages.id


# ── Buttondown: a newsletter send ────────────────────────────────────────────────────────────────────────────────


def test_publishing_an_issue_with_delivery_send_records_the_send_in_flight_with_the_emails_id(world):
    world.http.current = _Http(_mail_routes())

    _publish(world)

    (row,) = _rows(world)
    assert (row.status, row.action, row.remote_id, row.remote_url) == (
        "in_flight",
        "create_issue_email",
        EMAIL_TYPEID,
        "https://buttondown.com/n/archive/hello/",
    )
    assert (row.integration_id, row.entry_id, row.finished_at) == (world.news.id, world.issue.id, None)
    assert row.workflow_id == world.session.query(WorkspaceAutomationModel).filter_by(group_id=world.gid, slug="buttondown-issue-on-publish").one().id


@pytest.mark.parametrize("webhook_id", [EMAIL_UUID, EMAIL_TYPEID], ids=["the webhooks UUID", "an em_ id"])
def test_buttondowns_email_sent_event_settles_the_send_succeeded_whichever_id_it_carries(world, webhook_id):
    world.http.current = _Http(_mail_routes())
    _publish(world)

    ran = _hook(world, "buttondown", {"event_type": "email.sent", "data": {"email": webhook_id}})

    assert ran == 1
    (row,) = _rows(world)  # the same record, not another
    assert (row.status, row.remote_id, row.integration_id) == ("succeeded", EMAIL_TYPEID, world.news.id)
    assert row.finished_at is not None and row.entry_id == world.issue.id


def test_a_draft_records_nothing(world):
    world.news.config = {"issue_delivery": "draft"}
    world.session.commit()
    world.http.current = _Http(_mail_routes(status="draft"))

    _publish(world)

    assert _rows(world) == []
    posted = next(c for c in world.http.current.calls if c["method"] == "POST")
    assert posted["json"]["status"] == "draft"  # the call was made, and it saved a draft: not a hand-off


def test_delivery_off_records_nothing_and_calls_nothing(world):
    world.news.config = {"issue_delivery": "off"}
    world.session.commit()
    world.http.current = _Http(_mail_routes())

    _publish(world)

    assert _rows(world) == [] and world.http.current.calls == []


def test_publishing_the_same_issue_again_does_not_record_a_second_send(world):
    world.http.current = _Http(_mail_routes())
    _publish(world)
    world.http.current = _Http(
        [("GET", "/v1/emails?", 200, {"results": [{"id": EMAIL_TYPEID, "status": "sent", "metadata": {"marvin_entry_id": str(world.issue.id)}}]})]
    )

    _publish(world)  # Buttondown already has the email: the call is skipped, sends nothing, and so is no new hand-off

    assert [r.status for r in _rows(world)] == ["in_flight"]


def test_an_email_sent_event_for_an_email_marvin_did_not_send_is_listed_as_a_new_result(world):
    ran = _hook(world, "buttondown", {"event_type": "email.sent", "data": {"email": str(uuid.uuid4())}})

    assert ran == 1
    (row,) = _rows(world)
    assert (row.status, row.integration_id, row.entry_id) == ("succeeded", world.news.id, None) and row.remote_id.startswith("em_")


def test_other_buttondown_events_do_not_touch_results(world):
    assert _hook(world, "buttondown", {"event_type": "subscriber.confirmed", "data": {"subscriber": str(uuid.uuid4())}}) == 0
    assert _hook(world, "buttondown", {"event_type": "email.sent", "data": {}}) == 0  # no email id: nothing to settle

    assert _rows(world) == []


def test_the_applied_buttondown_workflows_match_what_the_plugin_declares(world):
    blueprints = [b for b in list_blueprints(source="buttondown") if b.slug in {"buttondown-issue-on-publish", "buttondown-email-sent"}]

    assert [outdated(world.session, world.gid, b) for b in blueprints] == [False, False]
