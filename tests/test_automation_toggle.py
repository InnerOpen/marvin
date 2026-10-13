"""Switching an automation on or off — the agent's `set_automation_enabled` and the admin pages, one audited path
(services/automation/toggle.py, services/ai/tools/builtins_automation_toggle.py).

The case: asked to turn on Slack announcements, the agent found the blueprint's integration action switched off and
could only tell the admin to flip it. Now it asks, the admin approves, it flips `enabled` — nothing else — and the
event log keeps who did it. The pages' PATCH routes send the same events.
"""

import json
import uuid

import pytest

from marvin.db.models.users.roles import WorkspaceRole
from marvin.services.ai.agent import AgentTool, ResumeState, run_agent_loop
from marvin.services.ai.agents import ROUTER_ASK_CATEGORIES
from marvin.services.ai.base import Message, ToolCall
from marvin.services.ai.operations.base import ROLE_ADMIN
from marvin.services.ai.tools import bulk_writes, get_tool
from marvin.services.ai.tools.base import ToolContext
from marvin.services.ai.tools.categories import category_of
from tests import test_event_connections as evc
from tests.test_archive_entries_tool import _Provider, _result
from tests.test_event_connections import world  # noqa: F401 — the fixture

TOOL = "set_automation_enabled"


class _SpyBus:
    events: list = []

    def __init__(self, *a, **k):
        pass

    def dispatch(self, *, event_type, entity_id=None, document_data=None, user_id=None, **_):
        _SpyBus.events.append((event_type.name, str(entity_id), document_data, user_id))


@pytest.fixture
def spy(monkeypatch):
    monkeypatch.setattr("marvin.services.event_bus_service.event_bus_service.EventBusService", _SpyBus)
    _SpyBus.events = []
    return _SpyBus


@pytest.fixture
def slack(db_session, world):  # noqa: F811
    """The incident's shape: a Slack integration (on) whose blueprint-installed send_message is off."""
    integ = evc.integration(db_session, world.a, name="Slack", provider="slack")
    action = evc.isub(db_session, world.a, integ, "entry_published", action="send_message", enabled=False, source=integ)
    action.args = {"text": "New: {{title}}"}
    db_session.commit()
    return action


def _ctx(db_session, world, role=WorkspaceRole.ADMIN):  # noqa: F811
    return ToolContext(session=db_session, group_id=world.a, user=evc._caller(world, role))


def _call(ctx, **args) -> dict:
    return json.loads(get_tool(TOOL).handler(ctx, args))


def _args(row, enabled=True, kind="integration_action", **extra):
    return {"kind": kind, "id": str(row.id), "enabled": enabled, **extra}


# ── Where it sits ────────────────────────────────────────────────────────────


def test_it_is_an_admin_write_in_its_own_row_that_always_asks_the_router():
    spec = get_tool(TOOL)
    assert spec.min_role == ROLE_ADMIN and spec.read_only is False and spec.ask_first is not None
    assert category_of(TOOL, read_only=False) == "automation_manage"
    assert "automation_manage" in ROUTER_ASK_CATEGORIES


# ── The approval card ───────────────────────────────────────────────────────


def test_the_card_says_what_it_does_who_installed_it_and_the_switch(db_session, world, slack):  # noqa: F811
    asked = get_tool(TOOL).ask_first(_ctx(db_session, world), _args(slack))
    assert asked.preview["summary"] == "Switch on the integration action “Slack → send_message”"
    assert asked.preview["targets"] == [
        "It runs Slack → send_message on every entry_published (message: “New: {{title}}”)",
        "Now off → on",
        "Installed by the acme-announce blueprint",
    ]
    assert db_session.get(type(slack), slack.id).enabled is False  # looking never writes


def test_no_card_for_a_no_op_or_an_id_it_cannot_find(db_session, world, slack):  # noqa: F811
    ask = get_tool(TOOL).ask_first
    ctx = _ctx(db_session, world)
    assert ask(ctx, _args(slack, enabled=False)) is None  # already off: the handler says so
    assert ask(ctx, {"kind": "integration_action", "id": str(uuid.uuid4()), "enabled": True}) is None


# ── What a switch does ──────────────────────────────────────────────────────


def test_switching_on_flips_enabled_only_and_is_audited_as_the_agent(db_session, world, slack, spy):  # noqa: F811
    out = _call(_ctx(db_session, world), **_args(slack, reason="announce publishes"))

    assert (out["enabled"], out["effective"], out["changed"]) == (True, True, True)
    row = db_session.get(type(slack), slack.id)
    assert row.enabled is True and row.args == {"text": "New: {{title}}"} and row.action == "send_message"
    [(name, entity, data, user)] = spy.events
    assert (name, entity, user) == ("integration_action_enabled", str(slack.id), world.ua)
    assert (data.via, data.reason, data.source_blueprint, data.reacts_to) == ("agent", "announce publishes", "acme-announce", "entry_published")


def test_an_action_under_a_switched_off_integration_says_it_still_wont_run(db_session, world, slack, spy):  # noqa: F811
    slack.integration.enabled = False
    db_session.commit()

    assert "integration is switched off" in get_tool(TOOL).ask_first(_ctx(db_session, world), _args(slack)).preview["targets"][-1]
    out = _call(_ctx(db_session, world), **_args(slack))

    assert out["enabled"] is True and out["effective"] is False and "switched off" in out["warning"]
    assert slack.integration.enabled is False  # never switches the integration itself
    assert spy.events[0][2].effective is False


def test_already_in_that_state_writes_and_sends_nothing(db_session, world, slack, spy):  # noqa: F811
    out = _call(_ctx(db_session, world), **_args(slack, enabled=False))
    assert out["changed"] is False and "already off" in out["note"] and spy.events == []


def test_another_workspaces_automation_is_not_found(db_session, world, spy):  # noqa: F811
    theirs = evc.isub(db_session, world.b, evc.integration(db_session, world.b), "entry_published", enabled=False)
    out = _call(_ctx(db_session, world), **_args(theirs))
    assert "no integration action with that id" in out["error"]
    assert db_session.get(type(theirs), theirs.id).enabled is False and spy.events == []


def test_a_workflow_switches_through_update_workflow(db_session, world, spy):  # noqa: F811
    flow = evc.workflow(db_session, world.a, "Tag new recipes", trigger={"type": "event", "event": "entry_published"}, enabled=False)

    out = _call(_ctx(db_session, world), kind="workflow", id=str(flow.id), enabled=True)

    assert out["changed"] and db_session.get(type(flow), flow.id).enabled is True
    assert [e[0] for e in spy.events] == ["automation_enabled"]


# ── In a conversation: parks, then runs only if approved ─────────────────────


def _agent_tool(db_session, world, *, can_park=True) -> AgentTool:  # noqa: F811
    spec = get_tool(TOOL)
    run, check = bulk_writes.bind(spec, _ctx(db_session, world), can_park=can_park)
    return AgentTool(
        name=spec.name, description=spec.description, input_schema=spec.input_schema, run=run, category="automation_manage", approval_check=check
    )


def _park(db_session, world, slack):  # noqa: F811
    call = ToolCall(id="c1", name=TOOL, arguments=_args(slack))
    provider = _Provider([_result(tool_calls=[call])])
    return run_agent_loop(provider, "m", [Message(role="user", content="turn on slack announcements")], [_agent_tool(db_session, world)])


@pytest.mark.parametrize("decision, enabled", [("approve", True), ("deny", False)])
def test_it_parks_and_switches_only_when_approved(db_session, world, slack, spy, decision, enabled):  # noqa: F811
    res = _park(db_session, world, slack)
    assert res.stopped_reason == "awaiting_approval" and "Slack → send_message" in res.pending_calls[0].preview["summary"]
    assert db_session.get(type(slack), slack.id).enabled is False

    done = run_agent_loop(
        _Provider([_result(content="ok")]),
        "m",
        [],
        [_agent_tool(db_session, world)],
        resume=ResumeState(convo=res.convo, pending=res.pending_calls, decisions={"c1": decision}),
    )

    assert done.stopped_reason == "complete"
    assert db_session.get(type(slack), slack.id).enabled is enabled
    assert len(spy.events) == (1 if enabled else 0)


def test_a_run_that_cannot_pause_is_refused(db_session, world, slack, spy):  # noqa: F811
    for run in (_agent_tool(db_session, world, can_park=False).run, bulk_writes.unattended(get_tool(TOOL), _ctx(db_session, world))):
        out = json.loads(run(_args(slack)))
        assert "cannot pause to ask" in out["error"]
    assert db_session.get(type(slack), slack.id).enabled is False and spy.events == []


# ── The pages: same events, via ui ───────────────────────────────────────────


def _logged(db_session, world, event_type):  # noqa: F811
    from marvin.db.models.platform.event_log import EventLogModel

    db_session.expire_all()
    return db_session.query(EventLogModel).filter(EventLogModel.workspace_id == world.a, EventLogModel.event_type == event_type).all()


def test_the_events_page_switch_is_audited_too(db_session, world, slack):  # noqa: F811
    client = evc._client(world, WorkspaceRole.ADMIN)

    res = client.patch(f"/api/groups/integrations/subscriptions/{slack.id}", json={"enabled": True})
    assert res.status_code == 200, res.text
    again = client.patch(f"/api/groups/integrations/subscriptions/{slack.id}", json={"enabled": True})
    assert again.status_code == 200

    [row] = _logged(db_session, world, "integration_action_enabled")  # the repeat sent nothing
    assert row.entity_id == slack.id


def test_the_workflows_page_switch_is_audited_and_a_rename_is_not(db_session, world):  # noqa: F811
    flow = evc.workflow(db_session, world.a, "Weekly digest", enabled=True)
    client = evc._client(world, WorkspaceRole.ADMIN)

    assert client.patch(f"/api/automations/{flow.id}", json={"name": "Weekly digest v2"}).status_code == 200
    assert client.patch(f"/api/automations/{flow.id}", json={"enabled": False}).status_code == 200

    assert len(_logged(db_session, world, "automation_disabled")) == 1
    assert _logged(db_session, world, "automation_enabled") == []
