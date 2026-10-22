# ruff: noqa: F811 — the `ws` fixture is imported, then named as a parameter
"""The workflow `agent` step: hand a job to a named agent (services/automation/actions/agent.py).

Driven through the engine with a scripted model that records what it was offered and told, so the tools the agent got, the
Playbooks in its system frame, the drafts it left and what the step handed to later steps are all seen from outside.
"""

import uuid

import pytest
from pydantic import ValidationError

from marvin.db.models.groups.agents import WorkspaceAgentModel
from marvin.db.models.groups.ai_executions import AIExecutionModel
from marvin.db.models.groups.automation_executions import AutomationActionExecutionModel, AutomationExecutionModel
from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.users.roles import WorkspaceRole
from marvin.schemas.group.automation_definition import AutomationDefinition
from marvin.services.ai import factory
from marvin.services.ai.base import AIProvider, CompletionResult, ToolCall
from marvin.services.automation.actions import AutomationActionError, run_action
from marvin.services.automation.authoring import agent_step_warnings, draft_issues
from marvin.services.automation.context import event_context
from marvin.services.automation.engine import match_context, run_automations_for_event
from marvin.services.automation.recorder import ExecutionRecorder
from tests.test_playbooks import _playbook
from tests.test_workflow_library import _entry, _fire, _person, _reload, ws  # noqa: F401 — the fixture

DRAFT_ARGS = {"entry_type": "newsletter-issue", "title": "Launch post", "fields": {"body": "We shipped."}}
STEP = {"kind": "agent", "id": "work", "agent": "writer", "message": "Draft a post about ${entry.title}."}


class Scripted(AIProvider):
    """A model that plays its turns in order (the last one repeats) and records what it was offered and told."""

    provider_type = "fake"
    display_name = "Fake"
    supports_tool_calls = True

    def __init__(self, *turns):
        self.turns = list(turns)
        self.systems: list[str] = []
        self.offered: list[set[str]] = []
        self.users: list[str] = []

    def complete_with_tools(self, messages, model, tools, options=None, tool_choice="auto"):
        self.systems.append(messages[0].content)
        self.users.append(next(m for m in reversed(messages) if m.role == "user").content)
        self.offered.append({t["name"] if isinstance(t, dict) else t.name for t in tools})
        return self.turns.pop(0) if len(self.turns) > 1 else self.turns[0]

    def complete(self, messages, model, options=None):  # pragma: no cover
        raise NotImplementedError

    def complete_structured(self, messages, model, output_schema, options=None):  # pragma: no cover
        raise NotImplementedError

    def list_models(self):  # pragma: no cover
        return []

    def test_connection(self):  # pragma: no cover
        return True, ""


def _turn(content="", *calls):
    tool_calls = [ToolCall(id=f"c{i}", name=name, arguments=args) for i, (name, args) in enumerate(calls)]
    return CompletionResult(content=content, prompt_tokens=10, completion_tokens=5, total_tokens=15, model="m", tool_calls=tool_calls)


@pytest.fixture
def model(monkeypatch):
    def use(*turns) -> Scripted:
        fake = Scripted(*turns)
        monkeypatch.setattr(factory, "get_workspace_ai_provider", lambda *a, **k: fake)
        return fake

    return use


def _agent(ws, slug="writer", **kw) -> WorkspaceAgentModel:
    fields = {"kind": "persona", "enabled": True, "allow_writes": True, "tool_policy": {"entries_author": "allow"}, **kw}
    ws.session.query(WorkspaceAgentModel).filter_by(group_id=ws.gid, slug=slug).delete()  # the fixture's own writer, replaced
    row = WorkspaceAgentModel(session=ws.session, group_id=ws.gid, slug=slug, name=slug.title(), **fields)
    ws.session.add(row)
    ws.session.commit()
    return row


def _workflow(ws, *steps, trigger="entry_published", on_failure=None, author=None, slug="agent-flow") -> WorkspaceAutomationModel:
    author = author or _person(ws, "author", role=WorkspaceRole.ADMIN)
    definition = {
        "trigger": {"type": "event", "event": trigger},
        "conditions": [],
        "actions": list(steps),
        **({"on_failure": on_failure} if on_failure else {}),
    }
    row = WorkspaceAutomationModel(
        session=ws.session, group_id=ws.gid, name=slug, slug=slug, enabled=True, definition=definition, created_by=author.id
    )
    ws.session.add(row)
    ws.session.commit()
    return row


def _publish(ws, entry, **kw):
    doc = {"entry_id": str(entry.id), "entry_title": entry.title, "entry_type": None, "workspace_id": None}
    return _fire(ws, "entry_published", doc, entity=entry.id, entity_type="entry", user_id=ws.uid, **kw)


def _output(ws, slug="agent-flow", step="work") -> dict:
    run = (
        ws.session.query(AutomationExecutionModel)
        .filter_by(group_id=ws.gid, automation_slug=slug)
        .order_by(AutomationExecutionModel.started_at)
        .all()[-1]
    )
    rows = ws.session.query(AutomationActionExecutionModel).filter_by(execution_id=run.id, kind="agent").all()
    return rows[0].output_snapshot if rows else {}


def _run(ws, slug="agent-flow"):
    return (
        ws.session.query(AutomationExecutionModel)
        .filter_by(group_id=ws.gid, automation_slug=slug)
        .order_by(AutomationExecutionModel.started_at)
        .all()[-1]
    )


# ── the definition ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "change, message",
    [
        ({"message": "  "}, "needs a message"),
        ({"agent": ""}, "at least 1 character"),
        ({"max_steps": 16}, "less than or equal to 15"),
        ({"max_steps": 0}, "greater than or equal to 1"),
        ({"playbooks": ["a", "b", "c", "d"]}, "at most 3"),
    ],
)
def test_an_agent_step_is_held_to_its_shape(change, message):
    with pytest.raises(ValidationError, match=message):
        AutomationDefinition.model_validate({"trigger": {"type": "manual"}, "actions": [{**STEP, **change}]})


def test_the_step_defaults_to_eight_steps_and_the_trigger_entry():
    parsed = AutomationDefinition.model_validate({"trigger": {"type": "manual"}, "actions": [STEP]}).actions[0]
    assert (parsed.max_steps, parsed.on_entry, parsed.playbooks) == (8, True, [])


@pytest.mark.parametrize("wrapper", ["repeat", "parallel"])
def test_an_agent_step_is_refused_inside_repeat_and_parallel(wrapper):
    inner = {**STEP, "id": None}
    step = (
        {"kind": "repeat", "for_each": "${steps.rows.output.rows}", "steps": [inner]}
        if wrapper == "repeat"
        else {
            "kind": "parallel",
            "branches": [{"name": "a", "steps": [inner]}, {"name": "b", "steps": [{"kind": "wait", "for": "1h"}][:0] or [inner]}],
        }
    )
    with pytest.raises(ValidationError, match="an agent step can't run inside"):
        AutomationDefinition.model_validate({"trigger": {"type": "manual"}, "actions": [step]})


def test_a_draft_names_a_real_persona_agent_and_published_playbooks(ws):
    _agent(ws)
    _agent(ws, "chatty", kind="model")
    _agent(ws, "asleep", enabled=False)
    _playbook(ws.session, ws.gid, "social-post")
    _playbook(ws.session, ws.gid, "draft-only", status="draft")
    manual = _playbook(ws.session, ws.gid, "manual-one")
    manual.data_json = {**manual.data_json, "manual_only": True}
    ws.session.commit()

    def issues(**change):
        step = {**STEP, **change}
        return [i["message"] for i in draft_issues(ws.session, ws.gid, {"trigger": {"type": "manual"}, "actions": [step]})]

    assert issues(playbooks=["social-post"]) == []
    assert "No agent “nobody”" in issues(agent="nobody")[0]
    assert "No agent “chatty”" in issues(agent="chatty")[0]  # a plain model has no tools to work with
    assert "switched off" in issues(agent="asleep")[0]
    assert "No published Playbook “draft-only”" in issues(playbooks=["draft-only"])[0]
    assert "manual-only" in issues(playbooks=["manual-one"])[0]


def test_warnings_say_when_the_agent_cannot_do_the_job(ws):
    _agent(ws, "reader", allow_writes=False, tool_policy=None)
    _agent(ws, "asker", tool_policy={"entries_author": "ask"})
    admin = 50  # any role at or above editor

    def warnings(agent):
        definition = {"trigger": {"type": "manual"}, "actions": [{**STEP, "agent": agent}]}
        return [w["message"] for w in agent_step_warnings(ws.session, ws.gid, definition, admin)]

    assert "set Entries: author to Allow" in warnings("reader")[0]
    assert "set Entries: author to Allow" in warnings("asker")[0]
    _agent(ws, "writer")
    assert warnings("writer") == []


# ── a run ────────────────────────────────────────────────────────────────────


def test_the_agent_gets_only_its_allow_tools_and_its_drafts_come_back_as_entries(ws, model):
    _agent(ws, tool_policy={"entries_author": "allow", "entries_read": "block"})  # links and trash stay Ask-first: not offered
    fake = model(_turn("", ("create_draft", DRAFT_ARGS)), _turn("Drafted one post."))
    _workflow(ws, STEP)
    article = _entry(ws, "article", "Launch day", status="published", data={"body": "x"})

    _publish(ws, article)

    out = _output(ws)
    assert out["answer"] == "Drafted one post." and out["stopped"] == "complete" and out["playbooks"] == []
    (made,) = out["entries"]
    assert made["title"] == "Launch post" and made["id"] in made["reviewLink"] and made["status"] in ("draft", "inbox")
    assert _reload(ws, type("E", (), {"id": uuid.UUID(made["id"])})).status != "published"  # a draft, never live
    offered = fake.offered[0]
    assert {"create_draft", "update_draft"} <= offered
    assert not offered & {"attach_tag", "trash_entries", "archive_entries", "find_entries", "run_agent"}  # Ask-first, off, no recursion
    assert "Draft a post about Launch day." in fake.users[0] and str(article.id) in fake.users[0]  # the entry it is about
    assert "create_draft or update_draft" in fake.systems[0]  # steered away from compose_entry / revise_entry
    row = ws.session.query(AIExecutionModel).filter_by(id=uuid.UUID(out["execution_id"])).one()
    assert (row.trigger_type, row.operation_slug, row.status, row.total_tokens) == ("automation", "agent:writer", "completed", 30)
    assert out["tokens"] == 30 and out["steps"] == 1
    assert _run(ws).status == "success"


def test_always_load_and_step_playbooks_are_in_the_system_frame_and_reported(ws, model):
    _playbook(ws.session, ws.gid, "house-voice", body="Short sentences. No exclamation marks.")
    _playbook(ws.session, ws.gid, "social-post", body="Two posts: Bluesky under 300 characters, Mastodon under 500.")
    _agent(ws, playbooks={"names": None, "always": ["house-voice"]})
    fake = model(_turn("Done."))
    _workflow(ws, {**STEP, "playbooks": ["social-post"]})

    _publish(ws, _entry(ws, "article", "Launch day", status="published", data={"body": "x"}))

    system = fake.systems[0]
    assert "Short sentences. No exclamation marks." in system and "Bluesky under 300 characters" in system
    assert _output(ws)["playbooks"] == ["house-voice", "social-post"]
    row = ws.session.query(AIExecutionModel).filter_by(group_id=ws.gid, operation_slug="agent:writer").one()
    assert [p["name"] for p in row.metadata_json["playbooks"]] == ["house-voice", "social-post"]


def test_max_steps_is_respected(ws, model):
    _agent(ws, tool_policy={"entries_author": "allow"})
    fake = model(_turn("", ("list_entry_types", {})), _turn("", ("list_entry_types", {})), _turn("Gave up after two."))
    _workflow(ws, {**STEP, "max_steps": 2})

    _publish(ws, _entry(ws, "article", "Launch day", status="published", data={"body": "x"}))

    out = _output(ws)
    assert (out["stopped"], out["steps"], out["answer"]) == ("max_steps", 2, "Gave up after two.")
    assert len(fake.offered) == 3  # two tool turns, then the forced answer


def test_a_dry_run_shows_the_job_and_calls_no_model(ws, model):
    _playbook(ws.session, ws.gid, "social-post")
    _agent(ws)
    fake = model(_turn("never"))
    row = _workflow(ws, {**STEP, "playbooks": ["social-post"]})
    article = _entry(ws, "article", "Launch day", status="published", data={"body": "x"})
    context = match_context(ws.session, ws.gid, {"event_type": "entry_published", "entry_id": str(article.id)})
    context["_step"] = {"workflow": str(row.id), "author_id": row.created_by}

    out = run_action(ws.session, ws.gid, STEP | {"playbooks": ["social-post"]}, context, user_id=ws.uid, dry_run=True)

    assert out["dry_run"] and out["agent"] == "writer" and "Draft a post about Launch day." in out["message"]
    assert "create_draft" in out["tools"] and "attach_tag" not in out["tools"]
    assert out["playbooks"] == ["social-post"] and out["answer"].startswith("‹AI answer")
    assert fake.offered == [] and ws.session.query(AIExecutionModel).filter_by(group_id=ws.gid).count() == 0


@pytest.mark.parametrize(
    "agent, message",
    [
        ({"slug": "nobody"}, "no agent 'nobody'"),
        ({"enabled": False}, "is disabled"),
        ({"kind": "model"}, "plain model"),
    ],
)
def test_an_unknown_disabled_or_model_only_agent_fails_the_step_and_on_failure_runs(ws, model, agent, message):
    fake = model(_turn("never"))
    if agent.get("slug") != "nobody":
        _agent(ws, **agent)
    mark = {"kind": "entry", "op": "set_metadata", "metadata": {"agent_failed": "${error.message}"}}
    _workflow(ws, {**STEP, "agent": agent.get("slug", "writer")}, on_failure=[mark])
    article = _entry(ws, "article", "Launch day", status="published", data={"body": "x"})

    _publish(ws, article)

    run = _run(ws)
    assert run.status == "failed" and message in run.error and fake.offered == []
    assert message in _reload(ws, article).metadata_json["agent_failed"]


def test_a_bad_step_playbook_fails_the_step(ws, model):
    _agent(ws)
    model(_turn("never"))
    _workflow(ws, {**STEP, "playbooks": ["not-written"]})
    _publish(ws, _entry(ws, "article", "Launch day", status="published", data={"body": "x"}))
    assert "not a published Playbook" in _run(ws).error


def test_an_over_budget_workspace_fails_the_step_before_the_agent_runs(ws, model):
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    fake = model(_turn("never"))
    _agent(ws)
    settings = ws.session.query(WorkspaceAISettingsModel).filter_by(group_id=ws.gid).one()
    settings.budget_config = {"max_cost_per_month_usd": 1.0}
    ws.session.add(
        AIExecutionModel(
            session=ws.session, group_id=ws.gid, operation_slug="agent:marvin", provider_type="fake", model_id="m", status="completed",
            estimated_cost_usd=5.0, trigger_type="mcp",
        )
    )  # fmt: skip
    ws.session.commit()
    _workflow(ws, STEP)

    _publish(ws, _entry(ws, "article", "Launch day", status="published", data={"body": "x"}))

    run = _run(ws)
    assert run.status == "failed" and "AI budget: Monthly cost limit" in run.error and fake.offered == []


def test_a_failing_model_records_the_execution_and_fails_the_step(ws, monkeypatch):
    class Broken(Scripted):
        def complete_with_tools(self, *a, **k):
            raise RuntimeError("provider is down")

    monkeypatch.setattr(factory, "get_workspace_ai_provider", lambda *a, **k: Broken(_turn("never")))
    _agent(ws)
    _workflow(ws, STEP)
    _publish(ws, _entry(ws, "article", "Launch day", status="published", data={"body": "x"}))
    assert "provider is down" in _run(ws).error
    row = ws.session.query(AIExecutionModel).filter_by(group_id=ws.gid, operation_slug="agent:writer").one()
    assert (row.status, row.trigger_type) == ("failed", "automation")


def test_a_later_step_reads_the_agents_answer(ws, model):
    _agent(ws)
    model(_turn("Looks fine."))
    mark = {"kind": "entry", "op": "set_metadata", "metadata": {"review": "${steps.work.output.answer} (${steps.work.output.stopped})"}}
    _workflow(ws, STEP, mark)
    article = _entry(ws, "article", "Launch day", status="published", data={"body": "x"})

    _publish(ws, article)

    assert _reload(ws, article).metadata_json["review"] == "Looks fine. (complete)"


# ── loops ────────────────────────────────────────────────────────────────────


def test_the_step_never_runs_for_an_event_its_own_workflow_caused(ws, model):
    _agent(ws)
    fake = model(_turn("never"))
    row = _workflow(ws, STEP)
    article = _entry(ws, "article", "Launch day", status="published", data={"body": "x"})
    ctx = event_context(
        "entry_published", {"entry_id": str(article.id)}, entity_id=article.id, entity_type="entry", caused_by_workflows=[str(row.id)]
    )

    run_automations_for_event(ws.session, ws.gid, ctx, recorder=ExecutionRecorder(ws.session, ws.gid))

    out = _output(ws)
    assert out["stopped"] == "refused" and "own run" in out["skipped"] and fake.offered == []
    # another workflow's event still runs it
    ctx = event_context("entry_published", {"entry_id": str(article.id)}, entity_id=article.id, entity_type="entry", caused_by_workflows=["other"])
    run_automations_for_event(ws.session, ws.gid, ctx, recorder=ExecutionRecorder(ws.session, ws.gid))
    assert fake.offered


def test_what_the_agent_saves_counts_as_a_reaction_hop(ws, model, monkeypatch):
    from marvin.services.event_bus_service.event_bus_service import EventBusService

    seen: list[tuple[str, int]] = []
    monkeypatch.setattr(EventBusService, "_publish_event", lambda self, event, group_id: seen.append((event.event_type.name, event.reaction_depth)))
    _agent(ws)
    model(_turn("", ("create_draft", DRAFT_ARGS)), _turn("Done."))
    _workflow(ws, STEP)

    _publish(ws, _entry(ws, "article", "Launch day", status="published", data={"body": "x"}))

    created = [depth for name, depth in seen if name == "entry_created"]
    assert created and all(depth >= 1 for depth in created)  # the run was at depth 0: its work is one hop on
    from marvin.services.event_bus_service.correlation import reaction_depth_floor

    assert reaction_depth_floor.get() == 0  # and the floor is lifted when the step ends


def test_the_depth_guard_stops_a_chain_the_agent_started():
    from marvin.services.automation.engine import MAX_REACTION_DEPTH
    from marvin.services.event_bus_service.event_bus_listener import AutomationReactionListener
    from marvin.services.event_bus_service.event_types import EventTypes

    class _Event:
        reaction_depth = MAX_REACTION_DEPTH
        event_type = EventTypes.entry_created

    assert AutomationReactionListener(uuid.uuid4()).get_subscribers(_Event()) == []


def test_an_agent_of_another_workspace_is_not_there(ws, model):
    from marvin.db.models.groups import Groups

    other = Groups(session=ws.session, name="Other", slug=f"other-{uuid.uuid4().hex[:6]}")
    ws.session.add(other)
    ws.session.flush()
    ws.groups.append(other.id)
    ws.session.add(WorkspaceAgentModel(session=ws.session, group_id=other.id, slug="scout", name="Scout", kind="persona", enabled=True))
    ws.session.commit()
    fake = model(_turn("never"))

    with pytest.raises(AutomationActionError, match="no agent 'scout'"):
        run_action(ws.session, ws.gid, {**STEP, "agent": "scout"}, {"event": {}, "_step": {}}, dry_run=True)
    assert fake.offered == []


# ── the authoring guide ──────────────────────────────────────────────────────


def test_the_guide_teaches_the_agent_step_and_steers_away_from_compose_and_revise(ws):
    from marvin.services.automation.authoring import authoring_guide

    index = authoring_guide(ws.session, ws.gid)
    assert "agent" in index["step_kinds"] and "agent" in index["sections"]
    section = authoring_guide(ws.session, ws.gid, "agent")["agent"]
    assert set(section["step"]["required"]) == {"agent", "message"}
    assert set(section["step"]["optional"]) >= {"playbooks", "max_steps", "on_entry"}
    assert "create_draft / update_draft" in section["note"] and "compose_entry and revise_entry" in section["note"]
    assert "section=agent" in authoring_guide(ws.session, ws.gid, "actions")["actions"]["kinds"]["agent"]["description"]
    assert "writer" in authoring_guide(ws.session, ws.gid, "workspace")["workspace"]["agents"]
