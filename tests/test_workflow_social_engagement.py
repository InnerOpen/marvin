"""Social engagement capabilities in a workflow: which need an Approval step, and that they name their integration.

`social.reply`, `social.message`, `social.repost` and `social.delete_comment` are approval-gated like `social.post` (at
save and at run time, whether or not the plugin said `requires_approval`); `social.comments`, `social.like` and
`social.hide` are not. None of them fans out to every network: a comment id means something to one network only.
"""

import uuid

import pytest

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

from marvin_integration_sdk import INTEGRATION_REGISTRY, IntegrationProvider, ProviderAction  # noqa: E402

from marvin.db.models.groups.groups import Groups  # noqa: E402
from marvin.db.models.groups.integrations import IntegrationModel  # noqa: E402
from marvin.services.automation.actions.base import AutomationActionError  # noqa: E402
from marvin.services.automation.actions.integration import run_integration_action  # noqa: E402
from marvin.services.automation.authoring import reference_issues  # noqa: E402
from marvin.services.automation.authz import ROLE_ADMIN  # noqa: E402
from marvin.services.integrations.alert_routing import GATED_CAPABILITIES, capabilities_of, capability_action  # noqa: E402

CAPS = {
    "social.comments": ("comments", False),
    "social.reply": ("reply", True),
    "social.like": ("like", False),
    "social.hide": ("hide", False),
    "social.delete_comment": ("delete", True),
    "social.repost": ("repost", True),
    "social.message": ("message", True),
}
ARGS = {
    "social.comments": {"limit": 5},
    "social.reply": {"comment_id": "c1", "text": "Thanks!"},
    "social.like": {"comment_id": "c1"},
    "social.hide": {"comment_id": "c1"},
    "social.delete_comment": {"comment_id": "c1"},
    "social.repost": {"post_id": "p1"},
    "social.message": {"to": {"handle": "alice"}, "text": "Hi"},
}
GATED = sorted(c for c, (_, gated) in CAPS.items() if gated)
OPEN = sorted(c for c, (_, gated) in CAPS.items() if not gated)
APPROVAL = {"kind": "approval", "message": "Send it?"}


def _network(*, flag_gated: bool = True):
    class _Net(IntegrationProvider):
        slug = "fake"
        name = "Fake"
        actions = tuple(
            ProviderAction(key=key, label=key, capability=cap, requires_approval=gated and flag_gated) for cap, (key, gated) in CAPS.items()
        )

        def __init__(self):
            self.calls: list[tuple[str, dict]] = []

        def run_action(self, key, args, ctx):
            self.calls.append((key, dict(args)))
            if args.get("dry_run"):
                return {"would_reply": {"text": args.get("text")}, "network": "fake"}
            return {"items": [], "cursor": "1", "replied": True, "reply_id": "r1", "network": "fake"}

    return _Net()


@pytest.fixture
def ws(db_session, monkeypatch):
    provider = _network()
    monkeypatch.setitem(INTEGRATION_REGISTRY, "fake", provider)
    monkeypatch.setattr("marvin.services.secrets.resolver.resolve_secret", lambda ref, gid=None: "tok")
    gid = uuid.uuid4()
    group = Groups(session=db_session, name=f"wfe-{gid.hex[:8]}", slug=f"wfe-{gid.hex[:8]}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    db_session.add(IntegrationModel(session=db_session, group_id=gid, provider="fake", name="net", slug="net", enabled=True, config={}))
    db_session.commit()
    yield type("WS", (), {"gid": gid, "session": db_session, "net": provider})
    db_session.rollback()
    from marvin.services.group.group_purge import purge_group_dependents

    db_session.query(IntegrationModel).filter(IntegrationModel.group_id == gid).delete()
    purge_group_dependents(db_session, gid)
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _step(capability, **extra):
    return {"kind": "integration", "integration": "net", "capability": capability, "args": ARGS[capability], **extra}


def _issues(ws, steps):
    definition = {"trigger": {"type": "manual"}, "actions": steps}
    return [(i["path"], i["message"]) for i in reference_issues(ws.session, ws.gid, definition)]


def _run(ws, step, *, approved=True, dry_run=False, role=ROLE_ADMIN, ahead=False):
    ctx = {"steps": {}, "depth": 0, **({"_approved": True} if approved else {}), **({"_approval_ahead": True} if ahead else {})}
    return run_integration_action(ws.session, ws.gid, step, ctx, authorizer_role=role, dry_run=dry_run)


# ── routing ──────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_gated_engagement_capabilities_are_reply_message_repost_and_delete():
    assert {"social.reply", "social.message", "social.repost", "social.delete_comment", "social.post"} == set(GATED_CAPABILITIES)
    assert GATED == ["social.delete_comment", "social.message", "social.reply", "social.repost"]


def test_every_engagement_capability_is_offered_but_a_gated_one_routes_only_once_approved():
    provider = _network()
    assert set(CAPS) <= capabilities_of(provider)
    for capability in GATED:
        assert capability_action(provider, capability, {}) is None
        assert capability_action(provider, capability, {}, approved=True) is not None
    for capability in OPEN:
        assert capability_action(provider, capability, {}) is not None


# ── at save ──────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("capability", GATED)
def test_save_refuses_a_gated_engagement_step_without_an_approval_step_before_it(ws, capability):
    [(path, message)] = _issues(ws, [_step(capability)])
    assert path == "actions[0].capability" and "needs a person's approval: put an Approval step before it" in message
    assert "Approval step before it" in _issues(ws, [_step(capability), APPROVAL])[0][1]  # one after it is no help
    assert _issues(ws, [APPROVAL, _step(capability)]) == []


@pytest.mark.parametrize("capability", OPEN)
def test_save_accepts_comments_like_and_hide_without_an_approval_step(ws, capability):
    assert _issues(ws, [_step(capability)]) == []


def test_save_refuses_an_engagement_step_that_names_no_integration(ws):
    for capability in ("social.like", "social.comments", "social.reply"):
        step = {k: v for k, v in _step(capability).items() if k != "integration"}
        issues = _issues(ws, [APPROVAL, step])
        assert any(path == "actions[1].integration" and "needs an `integration`" in message for path, message in issues), issues


def test_save_refuses_missing_arguments(ws):
    step = _step("social.reply", args={"text": "Thanks!"})
    [(path, message)] = _issues(ws, [APPROVAL, step])
    assert path == "actions[1].args" and "needs comment_id" in message
    [(_, message)] = _issues(ws, [APPROVAL, _step("social.message", args={"text": "x"})])
    assert "needs to" in message
    assert _issues(ws, [_step("social.like", args={"comment_id": "${steps.read.output.items[0].id}"})]) == []  # a template is a value


def test_save_still_refuses_a_named_action_that_is_gated_and_one_the_integration_cannot_do(ws):
    named = {"kind": "integration", "integration": "net", "action": "reply", "args": ARGS["social.reply"]}
    assert "needs a person's approval" in _issues(ws, [named])[0][1] and _issues(ws, [APPROVAL, named]) == []
    [(_, message)] = _issues(ws, [{**_step("social.like"), "capability": "social.bogus"}])
    assert "can't social.bogus" in message


# ── at run time ──────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("capability", GATED)
def test_a_gated_engagement_step_is_refused_before_an_approval_and_runs_after_it(ws, capability):
    with pytest.raises(AutomationActionError, match="needs a person's approval.*Approval step"):
        _run(ws, _step(capability), approved=False)
    assert ws.net.calls == []
    _run(ws, _step(capability))
    assert len(ws.net.calls) == 1


@pytest.mark.parametrize("capability", OPEN)
def test_comments_like_and_hide_run_without_approval(ws, capability):
    out = _run(ws, _step(capability), approved=False)
    assert out and len(ws.net.calls) == 1


def test_a_plugin_that_forgot_requires_approval_is_gated_anyway(ws, monkeypatch):
    monkeypatch.setitem(INTEGRATION_REGISTRY, "fake", lax := _network(flag_gated=False))
    for capability in GATED:
        with pytest.raises(AutomationActionError, match="approval"):
            _run(ws, _step(capability), approved=False)
    assert lax.calls == []


def test_an_engagement_step_without_an_integration_never_fans_out(ws):
    step = {k: v for k, v in _step("social.like").items() if k != "integration"}
    with pytest.raises(AutomationActionError, match="name its `integration`"):
        _run(ws, step)
    assert ws.net.calls == []


def test_a_workflow_dry_run_asks_a_reply_what_it_would_send_and_sends_nothing(ws):
    out = _run(ws, _step("social.reply", args={**ARGS["social.reply"], "dry_run": False}), dry_run=True, approved=False, ahead=True)
    assert out["would_reply"] == {"text": "Thanks!"} and out["dry_run"] is True
    [(key, args)] = ws.net.calls
    assert key == "reply" and args["dry_run"] is True  # the run decides, never the typed argument
    ws.net.calls.clear()
    _run(ws, _step("social.reply", args={**ARGS["social.reply"], "dry_run": True}))
    assert ws.net.calls[0][1]["dry_run"] is False


def test_a_dry_run_of_like_calls_nothing(ws):
    out = _run(ws, _step("social.like"), dry_run=True)
    assert out["dry_run"] is True and ws.net.calls == []


def test_a_step_with_missing_arguments_fails_naming_them(ws):
    with pytest.raises(AutomationActionError, match="social.reply needs `comment_id`"):
        _run(ws, _step("social.reply", args={"text": "x"}))
    with pytest.raises(AutomationActionError, match="`to` as an object"):
        _run(ws, _step("social.message", args={"to": {"name": "x"}, "text": "x"}))
