"""Approve / Deny on an AI-approval push (services/push_actions.py, POST /api/self/push/approvals/{id}/{decision}).

One tap may approve only what can be undone (the Trash and restoring, archiving, tags, collections), decided from
the parked record on the server; anything else gets no buttons and no token, and the endpoint refuses it even
with a token row forged into the database. The token decides one approval, for one user, once, for 15 minutes,
and dies when the approval is decided any other way. Using it runs the Ask page's own resume (a scripted loop
here, as in tests/test_agent_approval.py), audited with the surface ``push``.
"""

import json
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from fastapi.testclient import TestClient

from marvin.app import app
from marvin.db.models.users.roles import WorkspaceRole
from marvin.routes.ai import operations_controller as oc
from marvin.routes.users import push_controller
from marvin.schemas.group.ai_execution import AIAgentRequest
from marvin.schemas.user.push import PushApprovalAction
from marvin.services import push_actions, push_notifications, web_push
from marvin.services.ai import agent as loop_mod
from marvin.services.ai.agent import AgentStep, AgentTool, PendingCall
from marvin.services.event_bus_service.event_types import EventAIApprovalData, EventTypes
from tests.test_agent_approval import _awaiting, _Bus, _done, _Loop

TRASH_MATCH = PendingCall(
    id="c1",
    tool="trash_entries",
    arguments={"match": {"kind": "entries", "query": {"statuses": ["inbox"]}}},
    preview={"summary": "Move 78 entries to the Trash", "action": "trash", "targetType": "entry", "targetCount": 78},
)


def _tool(name: str) -> AgentTool:
    return AgentTool(name=name, description="", input_schema={}, run=lambda a: "{}", category="links", requires_approval=True)


@pytest.fixture
def env(db_session, monkeypatch):
    """A workspace, its editor (a real user, with one push device) and an Ask controller whose provider-facing
    parts are stubbed on the class — so the controller the endpoint builds runs the same stubs."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users
    from marvin.db.models.users.workspace_members import WorkspaceMembers

    gid, uid = uuid.uuid4(), uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"pa-{marker}", slug=f"pa-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    db_session.execute(
        sa.insert(Users.__table__).values(
            id=uid, group_id=gid, active_group_id=gid, full_name="Ed Itor", username=f"ed-{marker}", email=f"ed-{marker}@example.test",
            password="x", auth_method="MARVIN", is_superuser=False, platform_role="NONE", admin=False,
        )
    )  # fmt: skip
    db_session.execute(sa.insert(WorkspaceMembers.__table__).values(id=uuid.uuid4(), user_id=uid, group_id=gid, workspace_role=WorkspaceRole.EDITOR))
    monkeypatch.setattr(db_session, "commit", db_session.flush)

    loop = _Loop()
    tools: list[str] = ["trash_entries"]
    monkeypatch.setattr(loop_mod, "run_agent_loop", loop)
    C = oc.AIOperationsController
    monkeypatch.setattr(C, "group", property(lambda self: SimpleNamespace(name="ws")))
    stubs = {
        "_agent_context_block": lambda self, t, i: None,
        "_bounded_history": lambda self, turns: [],
        "_completion_opts": lambda self: None,
        "_emit_budget_thresholds": lambda self, execution: None,
        "_maybe_emit_quota": lambda self, execution, error: None,
        "_check_budget": lambda self: None,
        "_agent_provider": lambda self: SimpleNamespace(provider_type="fake"),
        "_default_model": lambda self: "m-default",
        "_require_tool_capable": lambda self, provider, model: None,
        "_external_mcp_tools": lambda self: [],
        "_bind_agent_tools": lambda self, provider, agent=None, role=None, *, depth=0, park_allowed=False: (
            [_tool(t) for t in tools],
            SimpleNamespace(depth=depth, referrals=[], execution_id=None, delegate=None),
        ),
    }
    for name, fn in stubs.items():
        monkeypatch.setattr(C, name, fn, raising=False)

    me = SimpleNamespace(
        id=uid,
        admin=False,
        active_group_id=gid,
        group_id=gid,
        workspace_memberships=[SimpleNamespace(group_id=gid, workspace_role=WorkspaceRole.EDITOR)],
    )
    ctl = C(session=db_session, user=me, event_bus=_Bus())
    ctl._logger = None

    pushes: list[dict] = []
    monkeypatch.setattr(web_push, "_post", lambda sub, data, message, vapid: pushes.append(json.loads(data)) or 201)
    yield SimpleNamespace(gid=gid, uid=uid, ctl=ctl, loop=loop, tools=tools, pushes=pushes, session=db_session)
    db_session.rollback()


@pytest.fixture
def vapid(monkeypatch):
    from marvin.core.config import get_app_settings
    from marvin.scripts.vapid import generate

    public, private = generate()
    settings = get_app_settings()
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", public)
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", private)
    monkeypatch.setattr(settings, "VAPID_SUBJECT", "mailto:ops@example.test")


def _park(env, *calls: PendingCall):
    """Park a run on a new thread of the editor's, waiting on ``calls``; returns the thread."""
    env.loop.results.append(_awaiting(*(calls or (TRASH_MATCH,))))
    env.tools[:] = sorted({c.tool for c in calls or (TRASH_MATCH,)})
    body = AIAgentRequest(message="trash the inbox", source="ask_page", threadId="new")
    res = env.ctl._run_agent_core(
        provider=SimpleNamespace(provider_type="fake"),
        model="m1",
        system="sys",
        body=body,
        entity_id=None,
        tools=[_tool(t) for t in env.tools],
        max_steps=6,
        operation_slug="agent:marvin",
        agent_slug="marvin",
        ctx=SimpleNamespace(depth=0, referrals=[], execution_id=None, delegate=None),
    )
    return env.ctl._thread_or_404(res["threadId"])


def _decide(env, thread, decision: str, token: str, *, result: str | None = None):
    """The endpoint, called as FastAPI would (the request's session, a bus), with the resumed run scripted."""
    trashed = result or json.dumps({"trashed": [{"id": str(i)} for i in range(78)], "skipped": []})
    env.loop.results.append(_done(answer="Done.", steps=[AgentStep(tool=TRASH_MATCH.tool, arguments=TRASH_MATCH.arguments, result=trashed)]))
    bus = _Bus()
    res = push_controller.decide_from_notification(thread.id, decision, PushApprovalAction(token=token), session=env.session, event_bus=bus)
    return res, bus


def _refused(env, approval_id, token, decision="approve") -> push_actions.Refused:
    with pytest.raises(push_actions.Refused) as e:
        push_actions.claim(env.session, approval_id, token, decision)
    return e.value


# ── what one tap may approve ──────────────────────────────────────────────────


def test_only_restorable_actions_may_be_approved_with_one_tap():
    def record(*calls):
        return {"calls": [dict(c) for c in calls], "parked_at": "x"}

    for tool in ("trash_entries", "restore_entries", "archive_entries", "attach_tag", "detach_tag", "add_to_collection", "remove_from_collection"):
        assert push_actions.restorable(record({"id": "c1", "tool": tool, "arguments": {}})), tool
    for tool in ("run_workflow", "compose_entry", "revise_entry", "import_asset", "attach_asset", "run_agent", "mcp__mail__send", "publish_entry"):
        assert not push_actions.restorable(record({"id": "c1", "tool": tool, "arguments": {}})), tool
    mixed = record({"id": "c1", "tool": "trash_entries", "arguments": {}}, {"id": "c2", "tool": "run_workflow", "arguments": {}})
    assert not push_actions.restorable(mixed)
    assert not push_actions.restorable(record()) and not push_actions.restorable(None)
    # a hand-off counts as its specialist's own calls
    handoff = {"id": "c1", "tool": "run_agent", "kind": "handoff", "arguments": {}}
    assert push_actions.restorable(record({**handoff, "child": {"agent": "tidy", "calls": [{"id": "c7", "tool": "attach_tag", "arguments": {}}]}}))
    assert not push_actions.restorable(
        record({**handoff, "child": {"agent": "mail", "calls": [{"id": "c7", "tool": "compose_entry", "arguments": {}}]}})
    )
    assert not push_actions.restorable(record(handoff))


def _event(env, thread):
    data = EventAIApprovalData(agent_slug="marvin", thread_id=thread.id, workspace_id=env.gid, calls=[])
    return SimpleNamespace(
        event_type=EventTypes.approval_requested,
        workspace_id=env.gid,
        user_id=env.uid,
        entity_id=thread.id,
        entity_type="ai_thread",
        document_data=data,
        message=SimpleNamespace(body="Marvin is waiting for your approval: trash_entries"),
    )


def _subscribe(env):
    from marvin.db.models.users.users import Users

    user = env.session.get(Users, env.uid)
    web_push.subscribe(env.session, user, endpoint="https://push.example.test/ed/1", p256dh="p", auth="a", user_agent=None, label=None)


def test_a_restorable_approval_push_carries_buttons_and_a_token_others_dont(env, vapid):
    from marvin.db.models.users.push_action_tokens import PushActionTokenModel

    _subscribe(env)
    thread = _park(env, TRASH_MATCH)
    push_notifications.deliver(env.session, env.gid, _event(env, thread))
    [payload] = env.pushes
    assert payload["approval"]["id"] == str(thread.id) and len(payload["approval"]["token"]) >= 40
    # + the icon count and the workspace a tap switches to; still far under Web Push's ~4 KB
    assert set(payload) == {"title", "body", "url", "tag", "approval", "badge", "workspace"} and len(json.dumps(payload)) < 500
    assert payload["workspace"] == str(env.gid)
    row = env.session.query(PushActionTokenModel).filter_by(thread_id=thread.id).one()
    assert row.token_hash != payload["approval"]["token"] and row.user_id == env.uid  # only the hash is kept

    env.pushes.clear()
    publish = _park(env, PendingCall(id="c1", tool="run_workflow", arguments={"slug": "publish-all"}))
    push_notifications.deliver(env.session, env.gid, _event(env, publish))
    [payload] = env.pushes
    assert "approval" not in payload and payload["url"].endswith(str(publish.id))
    assert env.session.query(PushActionTokenModel).filter_by(thread_id=publish.id).count() == 0


def test_no_token_without_a_device_that_takes_approvals(env, vapid):
    from marvin.db.models.users.push_action_tokens import PushActionTokenModel

    thread = _park(env, TRASH_MATCH)
    push_notifications.deliver(env.session, env.gid, _event(env, thread))
    assert env.pushes == [] and env.session.query(PushActionTokenModel).filter_by(thread_id=thread.id).count() == 0


# ── the token ─────────────────────────────────────────────────────────────────


def test_token_scope_tampering_and_single_use(env):
    thread = _park(env, TRASH_MATCH)
    other = _park(env, TRASH_MATCH)
    token = push_actions.mint(env.session, thread, env.uid)
    assert token and push_actions.mint(env.session, thread, uuid.uuid4()) is None  # someone else's run: none

    assert _refused(env, other.id, token).status == 404  # another approval
    assert _refused(env, thread.id, token[:-1] + ("A" if token[-1] != "A" else "B")).status == 404  # tampered
    assert _refused(env, thread.id, "").status == 404 and _refused(env, "not-a-uuid", token).status == 404
    assert _refused(env, thread.id, token, decision="publish").status == 404  # only approve | deny

    claim = push_actions.claim(env.session, thread.id, token, "deny")
    assert claim.user_id == env.uid and [c["id"] for c in claim.calls] == ["c1"]
    assert _refused(env, thread.id, token).status == 409  # used up


def test_token_expires(env):
    from marvin.db.models.users.push_action_tokens import PushActionTokenModel

    thread = _park(env, TRASH_MATCH)
    token = push_actions.mint(env.session, thread, env.uid)
    row = env.session.query(PushActionTokenModel).filter_by(thread_id=thread.id).one()
    assert row.expires_at - push_actions._now() <= push_actions.TOKEN_TTL
    row.expires_at = push_actions._now() - timedelta(seconds=1)
    assert _refused(env, thread.id, token).status == 410


def test_token_dies_when_the_approval_is_decided_another_way(env):
    from marvin.services.ai.threads import clear_pending

    thread = _park(env, TRASH_MATCH)
    token = push_actions.mint(env.session, thread, env.uid)
    clear_pending(thread)  # decided on the Ask page (or abandoned, or expired)
    assert _refused(env, thread.id, token).status == 409

    # parked again later: a new approval, which the old token doesn't decide
    again = _park(env, TRASH_MATCH)
    token = push_actions.mint(env.session, again, env.uid)
    pending = dict(again.pending_json)
    pending["parked_at"] = "2099-01-01T00:00:00+00:00"
    again.pending_json = pending
    assert _refused(env, again.id, token).status == 409


def test_token_is_the_runs_owners_only(env):
    thread = _park(env, TRASH_MATCH)
    token = push_actions.mint(env.session, thread, env.uid)
    thread.created_by = uuid.uuid4()
    assert _refused(env, thread.id, token).status == 404


def test_a_forged_token_for_a_non_restorable_approval_is_refused(env):
    from marvin.db.models.users.push_action_tokens import PushActionTokenModel

    thread = _park(env, PendingCall(id="c1", tool="run_workflow", arguments={"slug": "publish-all"}))
    assert push_actions.mint(env.session, thread, env.uid) is None
    forged = "forged-token-0123456789abcdefghij"
    env.session.add(
        PushActionTokenModel(
            session=env.session,
            user_id=env.uid,
            thread_id=thread.id,
            parked_at=thread.pending_json["parked_at"],
            token_hash=push_actions._hash(forged),
            expires_at=push_actions._now() + timedelta(minutes=5),
        )
    )
    env.session.flush()
    for decision in ("approve", "deny"):
        assert _refused(env, thread.id, forged, decision).status == 403
    assert thread.status == "awaiting_approval"


def test_attempts_are_rate_limited_per_approval(env):
    thread = _park(env, TRASH_MATCH)
    token = push_actions.mint(env.session, thread, env.uid)
    attempts, _ = push_actions.RATE_LIMIT
    for _ in range(attempts):
        assert _refused(env, thread.id, "wrong-token-0123456789abcdef").status == 404
    assert _refused(env, thread.id, token).status == 429


# ── deciding ──────────────────────────────────────────────────────────────────


def test_approve_runs_the_ask_resume_and_is_audited(env):
    from marvin.db.models.groups.ai_executions import AIExecutionModel

    thread = _park(env, TRASH_MATCH)
    execution_id = thread.pending_json["execution_id"]
    token = push_actions.mint(env.session, thread, env.uid)

    res, bus = _decide(env, thread, "approve", token)

    resumed = env.loop.calls[-1]["resume"]
    assert resumed.decisions == {"c1": "approve"} and [c.id for c in resumed.pending] == ["c1"]
    assert res.decision == "approve" and res.message == "Approved — moved 78 entries to the Trash"
    assert res.url == f"/workspace/settings/ai-ask?thread={thread.id}" and res.badge == 0
    env.session.refresh(thread)
    assert thread.status == "open" and [m.role for m in thread.messages] == ["user", "assistant"]  # the result is in the thread
    execution = env.session.get(AIExecutionModel, uuid.UUID(execution_id))
    assert execution.status == "completed"
    [audit] = execution.metadata_json["approvals"]
    assert (
        audit["surface"] == "push"
        and audit["decided_by"] == str(env.uid)
        and audit["calls"] == [{"id": "c1", "tool": "trash_entries", "decision": "approve"}]
    )
    granted = [e for e in bus.events if e["event_type"] == EventTypes.approval_granted]
    assert len(granted) == 1 and granted[0]["document_data"].surface == "push" and granted[0]["document_data"].decided_by == env.uid

    with pytest.raises(HTTPException) as e:  # once
        _decide(env, thread, "approve", token)
    assert e.value.status_code == 409


def test_deny_is_the_ask_pages_deny(env):
    thread = _park(env, TRASH_MATCH)
    token = push_actions.mint(env.session, thread, env.uid)
    res, bus = _decide(env, thread, "deny", token)
    assert env.loop.calls[-1]["resume"].decisions == {"c1": "deny"}
    assert res.message == "Denied — nothing was changed."
    types = [e["event_type"] for e in bus.events]
    assert EventTypes.approval_rejected in types and EventTypes.approval_granted not in types


def test_a_member_who_left_the_workspace_cant_decide(env):
    from marvin.db.models.users.workspace_members import WorkspaceMembers

    thread = _park(env, TRASH_MATCH)
    token = push_actions.mint(env.session, thread, env.uid)
    env.session.query(WorkspaceMembers).filter_by(user_id=env.uid).delete()
    env.session.expire_all()
    with pytest.raises(HTTPException) as e:
        _decide(env, thread, "approve", token)
    assert e.value.status_code == 403
    assert env.session.get(type(thread), thread.id).status == "awaiting_approval"


def test_the_endpoint_needs_no_session_and_says_why_it_refuses(db_session):
    from marvin.db.models.platform.submission_rate_limits import SubmissionRateLimits

    client = TestClient(app)
    approval = uuid.uuid4()
    res = client.post(f"/api/self/push/approvals/{approval}/approve", json={"token": "n" * 24})
    assert res.status_code == 404 and res.json()["detail"] == push_actions.INVALID
    assert client.post(f"/api/self/push/approvals/{uuid.uuid4()}/publish", json={"token": "x"}).status_code == 422
    db_session.query(SubmissionRateLimits).filter_by(subject_id=approval).delete()
    db_session.commit()


def test_confirmation_lines():
    tag = {
        "id": "c1",
        "tool": "attach_tag",
        "arguments": {},
        "preview": {"action": "attach", "items": ["a", "b"], "itemKind": "tag", "targetCount": 30, "targetType": "entry"},
    }
    assert push_actions.confirmation("approve", [tag], {"steps": []}) == "Approved — attached 2 tags to 30 entries"
    archive = {"id": "c1", "tool": "archive_entries", "arguments": {"entries": ["a"]}}
    steps = [{"tool": "archive_entries", "arguments": {"entries": ["a"]}, "result": json.dumps({"archived": [{"id": 1}]})}]
    assert push_actions.confirmation("approve", [archive], {"steps": steps}) == "Approved — archived 1 entry"
    mixed = {"id": "c1", "tool": "trash_entries", "arguments": {}}
    steps = [{"tool": "trash_entries", "arguments": {}, "result": json.dumps({"trashed": [1], "trashedAssets": [2, 3], "trashedResources": []})}]
    assert push_actions.confirmation("approve", [mixed], {"steps": steps}) == "Approved — moved 3 items to the Trash"
    assert push_actions.confirmation("approve", [{"id": "c1", "tool": "add_to_collection"}], None) == "Approved — added to the collection"
