"""The `describe_event` AI tool: "what happens when X?" for the agent and MCP clients.

It answers from services/events/connections.py — the same lookup as the Events pages — so these tests check the
wiring (registry, role, permission matrix, which events a caller may ask about, how a hint resolves), not the
lookup itself (tests/test_event_connections.py covers that).
"""

import json

import pytest

from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.services.ai.operations.base import ROLE_ADMIN
from marvin.services.ai.tools import get_tool
from marvin.services.ai.tools.base import ToolContext
from marvin.services.ai.tools.categories import CATEGORY_BY_TOOL, category_writes
from marvin.services.events import connections
from tests import test_event_connections as evc

world = evc.world  # the shared two-workspace fixture


def _ask(db_session, world, event, role=WorkspaceRole.OWNER, platform_role=PlatformRole.NONE) -> dict:
    ctx = ToolContext(session=db_session, group_id=world.a, user=evc._caller(world, role, platform_role))
    return json.loads(get_tool("describe_event").handler(ctx, {"event": event}))


def test_it_is_a_read_only_admin_tool_the_agent_and_mcp_both_get():
    spec = get_tool("describe_event")
    assert spec.read_only and spec.min_role == ROLE_ADMIN
    assert "mcp" in spec.sources and "agent" in spec.sources
    assert spec.input_schema["required"] == ["event"]
    assert CATEGORY_BY_TOOL["describe_event"] == "automation_read" and not category_writes("automation_read")


@pytest.mark.parametrize(("role", "listed"), [(WorkspaceRole.VIEWER, False), (WorkspaceRole.EDITOR, False), (WorkspaceRole.ADMIN, True)])
def test_only_workspace_admins_see_it_projected(world, role, listed):
    res = evc._client(world, role).get("/api/ai/tools")
    assert res.status_code == 200, res.text
    assert ("describe_event" in {t["name"] for t in res.json()}) is listed


def test_it_tells_the_whole_story_of_an_event(db_session, world):
    acme = evc.integration(db_session, world.a)
    evc.workflow(db_session, world.a, "Email the issue", {"type": "event", "event": "entry_published"}, source=acme)
    evc.webhook(db_session, world.a, "Notify", ["entry_published"], enabled=False)
    evc._log(db_session, world.a, "entry_published", 5, "published")
    evc.workflow(db_session, world.b, "B's own", {"type": "event", "event": "entry_published"})

    out = _ask(db_session, world, "entry_published")
    assert out["found"] and (out["eventType"], out["name"], out["scope"]) == ("entry_published", "Entry Published", "workspace")
    expected = connections.detail(db_session, world.a, connections.workspace_entry("entry_published"), limit=1)
    assert [s["name"] for s in out["sentBy"]] == [s.name for s in expected.senders]
    assert [(r["kind"], r["name"], r["enabled"]) for r in out["reactions"]] == [(r.kind, r.name, r.enabled) for r in expected.reactions]
    flow = next(r for r in out["reactions"] if r["name"] == "Email the issue")
    assert flow["installedBy"]["name"] == acme.name and flow["enabled"] is True
    assert ("webhook", "Notify", False) in [(r["kind"], r["name"], r["enabled"]) for r in out["reactions"]]
    assert "Queues a site rebuild" in [r["name"] for r in out["reactions"] if r["kind"] == "builtin"]
    assert "B's own" not in json.dumps(out) and "very-secret-token" not in json.dumps(out)
    assert {"eventType": "site_rebuild_queued", "name": "Site Rebuild Queued"} in out["leadsTo"]
    assert out["lastOccurredAt"] and out["recorded"] is True


@pytest.mark.parametrize(
    ("hint", "event_type"),
    [
        ("publish", "entry_published"),
        ("What happens when I publish?", "entry_published"),
        ("Entry Published", "entry_published"),
        ("site rebuild sent", "webhook_triggered"),
        ("form submission", "form_submission_received"),
        ("site_build_failed", "site_deployment_failed"),  # an old name is its counterpart
    ],
)
def test_a_hint_resolves_through_the_catalog(db_session, world, hint, event_type):
    out = _ask(db_session, world, hint)
    assert out["found"] and out["eventType"] == event_type, out.get("error")


def test_a_hint_with_several_matches_lists_the_others(db_session, world):
    out = _ask(db_session, world, "published")
    assert out["eventType"] == "entry_published"
    assert "form_published" in {m["eventType"] for m in out["otherMatches"]}


@pytest.mark.parametrize("event", ["webhook_delivery_succeeded", "site_published", "no such thing", "user_signup"])
def test_hidden_unknown_and_platform_events_are_not_described_to_a_workspace(db_session, world, event):
    out = _ask(db_session, world, event)
    assert out["found"] is False
    listed = {e["eventType"] for e in out["eventTypes"]}
    assert "entry_published" in listed and not {"user_signup", "webhook_delivery_succeeded", "site_build_failed"} & listed


def test_a_super_admin_gets_platform_events(db_session, world):
    note = evc.template(db_session, world.a, "Signup note")
    evc.esub(db_session, world.a, note, "user_signup")
    out = _ask(db_session, world, "user_signup", role=None, platform_role=PlatformRole.SUPER_ADMIN)
    assert out["found"] and out["scope"] == "platform"
    mine = [w for w in out["workspaceReactions"] if any(r["name"] == "Signup note" for r in w["reactions"])]
    assert mine and [s["name"] for s in out["sentBy"]] == ["Signing up"]
