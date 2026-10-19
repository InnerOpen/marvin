"""The email step: a workflow writes to a member of the workspace — and only to one.

Checked: who it may write to (a member, by id or email; never an outside address, a member of another workspace only, or a
word), the role gate, no SMTP, the rendered email (templates, markdown, the workspace's layout, the button), a dry run that
sends and claims nothing, and that the same event handled twice — or a retry — sends once."""

# ruff: noqa: F811 — `ws` is a fixture, not a redefinition
import uuid

import pytest

from marvin.db.models.groups import Groups
from marvin.db.models.groups.workflow_email_sends import WorkflowEmailSendModel
from marvin.db.models.users.roles import WorkspaceRole
from marvin.db.models.users.users import Users
from marvin.schemas.group.automation_definition import EmailAction
from marvin.services.automation.actions.base import AutomationActionError
from marvin.services.automation.actions.email import run_email
from marvin.services.automation.authoring import authoring_guide, draft_issues
from marvin.services.automation.authz import ROLE_AUTHOR
from marvin.services.email import email_senders
from tests.test_workflow_library import _fire, _install_workflow, _person, _runs, outbox, ws  # noqa: F401 — fixtures and helpers


def _step(**kw) -> dict:
    return {"kind": "email", "to": "${member.id}", "subject": "Hello ${member.name}", "body": "Welcome, **${member.name}**.", **kw}


def _ctx(person: Users, *, correlation: str | None = "c-1", index: int = 0) -> dict:
    return {
        "event": {"event_type": "member_added", "correlation_id": correlation},
        "member": {"id": str(person.id), "name": person.full_name, "email": person.email, "role": "EDITOR"},
        "previous": {},
        "steps": {},
        "_step": {"workflow": "wf-1", "index": index, "target": 0, "on_failure": False, "workflow_slug": "welcome", "step_id": None},
    }


def _run(ws, action: dict, context: dict, **kw) -> dict:
    return run_email(ws.session, ws.gid, action, context, authorizer_role=kw.pop("authorizer_role", None), **kw)


def _ledger(ws) -> list[WorkflowEmailSendModel]:
    return ws.session.query(WorkflowEmailSendModel).filter_by(group_id=ws.gid).all()


# ── Who it may write to ───────────────────────────────────────────────────────
def test_a_member_is_found_by_id_or_by_email_in_any_case(ws, outbox):
    ada = _person(ws, "ada", email="Ada.Lovelace@T.test")
    for to in (str(ada.id), "ada.lovelace@t.test", " ADA.LOVELACE@T.TEST "):
        out = _run(ws, _step(to=to, once_per=None), _ctx(ada, correlation=None))
        assert out["sent"] is True and out["user_id"] == str(ada.id) and out["role"] == "EDITOR"
    assert [m[0] for m in outbox] == ["Ada.Lovelace@T.test"] * 3  # to the address they have on file, whichever way they were named


def test_an_address_that_is_no_members_is_refused_and_nothing_is_sent(ws, outbox):
    ada = _person(ws, "ada")
    with pytest.raises(AutomationActionError, match="not a member of this workspace"):
        _run(ws, _step(to="someone@elsewhere.example"), _ctx(ada))
    assert outbox == [] and _ledger(ws) == []


def test_a_member_of_another_workspace_only_is_refused_like_a_stranger(ws, outbox):
    other = Groups(session=ws.session, name="Other", slug=f"other-{uuid.uuid4().hex[:6]}")
    ws.session.add(other)
    ws.session.flush()
    ws.groups.append(other.id)
    outsider = _person(ws, "olive", group_id=other.id)
    drifter = _person(ws, "drew", member=False)  # an account with no membership here
    for who in (outsider, drifter):
        for to in (str(who.id), who.email):
            with pytest.raises(AutomationActionError, match="not a member of this workspace") as exc:
                _run(ws, _step(to=to), _ctx(who))
            assert who.email not in str(exc.value)  # the refusal doesn't say whether the address has an account
    assert outbox == []


@pytest.mark.parametrize(("to", "message"), [("", "resolved to nothing"), ("nobody", "not a member id or an email"), (None, "resolved to nothing")])
def test_a_recipient_that_names_nobody_fails_the_step(ws, outbox, to, message):
    with pytest.raises(AutomationActionError, match=message):
        _run(ws, _step(to=to), _ctx(_person(ws, "ada")))
    assert outbox == []


def test_a_member_with_no_email_address_fails_the_step(ws, outbox):
    ada = _person(ws, "ada")
    ada.email = None
    ws.session.commit()
    with pytest.raises(AutomationActionError, match="has no email address"):
        _run(ws, _step(to=str(ada.id)), _ctx(ada))


# ── The gates ─────────────────────────────────────────────────────────────────
def test_an_author_below_admin_cant_email(ws, outbox):
    ada = _person(ws, "ada")
    with pytest.raises(AutomationActionError, match="requires role"):
        _run(ws, _step(), _ctx(ada), authorizer_role=ROLE_AUTHOR)
    assert outbox == []


def test_a_workspace_that_cant_send_mail_fails_the_step_and_claims_nothing(ws, monkeypatch):
    monkeypatch.setattr(email_senders, "email_ready", lambda *a, **k: False)
    ada = _person(ws, "ada")
    with pytest.raises(AutomationActionError, match="no way to send email") as exc:
        _run(ws, _step(), _ctx(ada))
    assert exc.value.code == "no_email" and _ledger(ws) == []


# ── The email ─────────────────────────────────────────────────────────────────
def test_subject_and_body_are_templates_and_the_body_is_markdown_in_the_workspace_layout(ws, outbox):
    ada = _person(ws, "ada")
    action = _step(
        subject="Welcome\n to ${member.name}",
        body="# Hi\n\nYou are **${member.role}**: [open it](https://app.example/x) <script>alert(1)</script>",
        heading="Welcome aboard",
        button_text="Open the workspace",
        button_link="https://app.example/workspace",
    )
    out = _run(ws, action, _ctx(ada))
    ((to, subject, html),) = outbox
    assert (to, subject, out["subject"]) == (ada.email, "Welcome to Ada", "Welcome to Ada")
    assert "<h1>Hi</h1>" in html and "<strong>EDITOR</strong>" in html and '<a href="https://app.example/x">open it</a>' in html
    assert "<script>" not in html and "&lt;script&gt;" in html  # nothing an entry says becomes markup
    assert "Welcome aboard" in html and 'href="https://app.example/workspace"' in html and "Open the workspace" in html
    assert ws.session.get(Groups, ws.gid).name in html  # the layout names the workspace


def test_a_button_needs_a_web_address(ws, outbox):
    ada = _person(ws, "ada")
    with pytest.raises(AutomationActionError, match="http"):
        _run(ws, _step(button_text="Go", button_link='javascript:alert("x")'), _ctx(ada))
    assert outbox == []
    with pytest.raises(ValueError, match="both"):
        EmailAction(**_step(button_text="Go"))


def test_an_empty_subject_or_body_fails_the_step(ws, outbox):
    ada = _person(ws, "ada")
    for key in ("subject", "body"):
        with pytest.raises(AutomationActionError, match=f"the {key} resolved to empty"):
            _run(ws, _step(**{key: "${member.nickname}"}), _ctx(ada))
    assert outbox == []


# ── Once ──────────────────────────────────────────────────────────────────────
def test_the_same_event_sends_once_and_another_event_sends_again(ws, outbox):
    ada = _person(ws, "ada")
    assert _run(ws, _step(), _ctx(ada, correlation="e-1"))["sent"] is True
    again = _run(ws, _step(), _ctx(ada, correlation="e-1"))
    assert again["sent"] is False and again["skipped"] is True and again["reason"] == "already sent"
    assert len(outbox) == 1 and len(_ledger(ws)) == 1
    _run(ws, _step(), _ctx(ada, correlation="e-2"))  # another event: another email
    _run(ws, _step(), _ctx(ada, correlation="e-1", index=1))  # another step in the workflow: another email
    assert len(outbox) == 3


def test_it_holds_per_person(ws, outbox):
    ada, bo = _person(ws, "ada"), _person(ws, "bo")
    for person in (ada, bo, ada, bo):
        _run(ws, _step(to="${member.id}"), _ctx(person, correlation="e-1"))
    assert sorted(m[0] for m in outbox) == sorted([ada.email, bo.email])


def test_once_per_sends_a_person_the_email_once_whatever_the_event(ws, outbox):
    ada = _person(ws, "ada")
    action = _step(once_per="welcome:${member.id}")
    for n in range(3):
        out = _run(ws, action, _ctx(ada, correlation=f"e-{n}"))
    assert len(outbox) == 1 and out["skipped"] is True
    assert _ledger(ws)[0].send_key.endswith(f"once:welcome:{ada.id}")


def test_no_event_to_tell_sends_apart_means_every_run_sends(ws, outbox):
    ada = _person(ws, "ada")
    ctx = _ctx(ada, correlation=None)
    _run(ws, _step(), ctx)
    _run(ws, _step(), ctx)
    assert len(outbox) == 2 and _ledger(ws) == []  # a manual run has no event: Run twice, send twice


def test_a_send_that_fails_gives_the_claim_back_so_a_retry_sends(ws, monkeypatch):
    ada = _person(ws, "ada")
    monkeypatch.setattr(email_senders, "email_ready", lambda *a, **k: True)
    state = {"up": False, "sent": []}

    def send(self, to, subject, html):
        if state["up"]:
            state["sent"].append(to)
        return state["up"]

    monkeypatch.setattr(email_senders.WorkspaceEmailSender, "send", send)
    with pytest.raises(AutomationActionError, match="did not accept") as exc:
        _run(ws, _step(), _ctx(ada, correlation="e-1"))
    assert exc.value.code == "send_failed" and _ledger(ws) == []
    state["up"] = True
    assert _run(ws, _step(), _ctx(ada, correlation="e-1"))["sent"] is True
    assert state["sent"] == [ada.email] and len(_ledger(ws)) == 1


def test_a_sender_that_raises_is_a_failed_step_too(ws, monkeypatch):
    ada = _person(ws, "ada")
    monkeypatch.setattr(email_senders, "email_ready", lambda *a, **k: True)

    def boom(self, *a):
        raise OSError("connection refused")

    monkeypatch.setattr(email_senders.WorkspaceEmailSender, "send", boom)
    with pytest.raises(AutomationActionError, match="connection refused"):
        _run(ws, _step(), _ctx(ada))
    assert _ledger(ws) == []


# ── Dry run ───────────────────────────────────────────────────────────────────
def test_a_dry_run_shows_the_email_and_sends_and_claims_nothing(ws, outbox):
    ada = _person(ws, "ada")
    out = _run(ws, _step(), _ctx(ada), dry_run=True)
    assert out["dry_run"] is True and out["would_send"] is True and out["already_sent"] is False and out["can_send"] is True
    assert (out["to"], out["name"], out["subject"]) == (ada.email, "Ada", "Hello Ada") and "<strong>Ada</strong>" in out["body_html"]
    assert outbox == [] and _ledger(ws) == []

    _run(ws, _step(), _ctx(ada))  # sent for real…
    again = _run(ws, _step(), _ctx(ada), dry_run=True)  # …so the next one wouldn't go
    assert again["already_sent"] is True and again["would_send"] is False and len(outbox) == 1


def test_a_dry_run_in_a_workspace_that_cant_send_says_so_instead_of_failing(ws, monkeypatch):
    monkeypatch.setattr(email_senders, "email_ready", lambda *a, **k: False)
    out = _run(ws, _step(), _ctx(_person(ws, "ada")), dry_run=True)
    assert out["can_send"] is False and out["would_send"] is False


def test_a_dry_run_still_refuses_a_non_member(ws, outbox):
    with pytest.raises(AutomationActionError, match="not a member"):
        _run(ws, _step(to="stranger@elsewhere.example"), _ctx(_person(ws, "ada")), dry_run=True)


def test_a_dry_run_names_where_a_step_fed_recipient_or_text_will_come_from(ws, outbox):
    ctx = _ctx(_person(ws, "ada"))
    out = _run(ws, _step(to="${steps.pick.output.id}", subject="${steps.draft.output.title}", body="${steps.draft.output.body}"), ctx, dry_run=True)
    assert out["to"] == "‹${steps.pick.output.id}›" and out["subject"] == "‹${steps.draft.output.title}›" and out["would_send"] is True


# ── In a workflow ─────────────────────────────────────────────────────────────
JOINED = {"operation": "create", "username": "x", "role": "EDITOR"}


def test_a_member_added_workflow_welcomes_the_new_member_once_per_event_and_a_real_run_is_recorded(ws, outbox):
    ada = _person(ws, "ada")
    _install_workflow(ws, "welcome", "member_added", [_step(id="mail")])

    for _ in range(2):  # the event, and the same event again
        _fire(ws, "member_added", JOINED, entity=ada.id, entity_type="member", correlation_id="join-1")
    assert [m[:2] for m in outbox] == [(ada.email, "Hello Ada")]
    first, second = _runs(ws, "welcome")
    assert first.status == "success" and second.status == "success"

    _fire(ws, "member_added", JOINED, entity=ada.id, entity_type="member", correlation_id="join-2")
    assert len(outbox) == 2  # another event is another email (once_per is how a workflow says "ever")


def test_a_role_gets_the_link_for_its_role(ws, outbox, monkeypatch):
    monkeypatch.setattr("marvin.services.ui_links.ui_base_url", lambda: "https://app.example")
    ada, ed = _person(ws, "ada", role=WorkspaceRole.ADMIN), _person(ws, "ed")
    mail = {"kind": "email", "to": "${member.id}", "subject": "Welcome"}
    writers = {"field": "member.role", "op": "in", "value": ["ADMIN", "EDITOR"]}
    readers = {"field": "member.role", "op": "eq", "value": "VIEWER"}
    steps = [
        {**mail, "body": "Write in the [workspace](${site.app_url}/workspace).", "when": [writers]},
        {**mail, "body": "Read the [site](https://site.example).", "when": [readers]},
    ]
    _install_workflow(ws, "welcome", "member_added", steps)
    _fire(ws, "member_added", {**JOINED, "role": "ADMIN"}, entity=ada.id, entity_type="member", correlation_id="j-1")
    _fire(ws, "member_added", {**JOINED, "role": "VIEWER"}, entity=ed.id, entity_type="member", correlation_id="j-2")
    assert [(to, "https://app.example/workspace" in html, "https://site.example" in html) for to, _, html in outbox] == [
        (ada.email, True, False),
        (ed.email, False, True),
    ]


def test_a_workflow_that_names_a_non_member_fails_its_run_and_sends_nothing(ws, outbox):
    ada = _person(ws, "ada")
    _install_workflow(ws, "welcome", "member_added", [_step(to="outside@elsewhere.example")])
    _fire(ws, "member_added", JOINED, entity=ada.id, entity_type="member", correlation_id="join-1")
    (run,) = _runs(ws, "welcome")
    assert run.status == "failed" and "not a member of this workspace" in (run.error or "")
    assert outbox == []


# ── Writing one ───────────────────────────────────────────────────────────────
def test_the_editor_and_validator_take_the_step_and_refuse_a_to_that_is_neither_id_nor_email(ws):
    good = {"trigger": {"type": "event", "event": "member_added"}, "actions": [_step()]}
    assert draft_issues(ws.session, ws.gid, good) == []
    bad = {"trigger": {"type": "event", "event": "member_added"}, "actions": [_step(to="ada"), _step(button_text="Go", button_link="ftp://x")]}
    issues = draft_issues(ws.session, ws.gid, bad)
    assert [(i["path"]) for i in issues] == ["actions[0].to", "actions[1].button_link"]


def test_the_guide_documents_the_step_and_keeps_the_rules_in_its_own_section(ws):
    actions = authoring_guide(ws.session, ws.gid, "actions")["actions"]
    assert "section=email" in actions["kinds"]["email"]["description"]  # one line in actions; the rest in its section
    email = authoring_guide(ws.session, ws.gid, "email")["email"]
    assert set(email["step"]["required"]) == {"to", "subject", "body"} and "once_per" in email["step"]["optional"]
    note = email["note"]
    assert "never an outside address" in note and "once_per" in note and "${site.app_url}" in note
