"""`email` step — write to a person in the workspace. No AI.

`to`: the person — a member's user id (${member.id}, ${steps.<id>.output.rows.0.id}) or the email address they signed up
with (${member.email}, ${entry.data.owner}). They must be a member of this workspace: an address that is no member's —
or a member of another workspace only — is refused, never mailed. (A workflow can't write to an outside address; a fixed
outside recipient is an email subscription's job: Settings → Email, recipient `specific`.)

`subject` and `body` are templates; `body` is markdown (headings, bold, italic, links, bare addresses; HTML is escaped)
and goes into the workspace's email layout — its own Jinja layout file, else Marvin's — through the workspace's SMTP
profile. `heading` (default the subject) is the layout's title; `button_text` + `button_link` add its button.

Sent once: the step claims a row in `workflow_email_sends` (models/groups/workflow_email_sends.py) before it sends, keyed on
the run's event, the step and the person — the same event handled twice, a retry and a re-run send nothing the second
time — or on `once_per`, a template naming what the email is for (`welcome:${member.id}`: this workflow's step writes
that person once, ever). A send that fails gives the claim back.

A dry run resolves the person, renders the email and says whether it would go (`would_send`: false when it was already
sent, or when the workspace has no way to send mail) — and sends and claims nothing.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from marvin.db.locking import begin_write

from ..matcher import interpolate
from .base import AutomationActionError, register_action

MAX_SUBJECT_CHARS = 200
MAX_BODY_CHARS = 20_000
MAX_KEY_CHARS = 120  # of `once_per`; the whole key is held to 400
_STEP_REF = re.compile(r"\$\{\s*steps\.")
_LINK = re.compile(r"https?://[^\s\"'<>]+")


def find_member(session, group_id, ref) -> tuple[object, str]:
    """(user, role) for `ref` — a member's id or email address; AutomationActionError when it is none of this workspace's members."""
    from marvin.db.models.users.users import Users
    from marvin.db.models.users.workspace_members import WorkspaceMembers

    text = str(ref or "").strip()
    if not text:
        raise AutomationActionError("email step: `to` resolved to nothing — name a member by id or email (e.g. ${member.id})")
    user = None
    try:
        user = session.get(Users, uuid.UUID(text))
    except ValueError:
        if "@" in text:
            user = session.query(Users).filter(func.lower(Users.email) == text.lower()).first()
        else:
            raise AutomationActionError(f"email step: “{text[:80]}” is not a member id or an email address") from None
    membership = (
        session.query(WorkspaceMembers).filter(WorkspaceMembers.user_id == user.id, WorkspaceMembers.group_id == group_id).first() if user else None
    )
    if user is None or membership is None:
        # One message for "no such person" and "a person elsewhere": whether an address has an account is not for a workflow to learn.
        raise AutomationActionError("email step: the recipient is not a member of this workspace — a workflow only writes to the workspace's members")
    if not user.email:
        raise AutomationActionError(f"email step: {user.full_name or user.username or 'that member'} has no email address")
    return user, getattr(membership.workspace_role, "value", str(membership.workspace_role))


def _text(raw, context, dry_run: bool, what: str, limit: int) -> str:
    value = interpolate(raw, context)
    value = "" if value is None else str(value)
    if dry_run and not value.strip() and isinstance(raw, str) and _STEP_REF.search(raw):
        value = f"‹{raw.strip()}›"  # an earlier step only previewed: show where it comes from
    value = value.strip()
    if not value:
        raise AutomationActionError(f"email step: the {what} resolved to empty")
    return value[:limit]


def _send_key(action: dict, context: dict, user_id) -> str:
    step = context.get("_step") or {}
    once = interpolate(action.get("once_per"), context) if action.get("once_per") else None
    if once not in (None, ""):
        what = f"once:{str(once)[:MAX_KEY_CHARS]}"
    else:
        from marvin.services.event_bus_service.correlation import current_correlation_id

        correlation = (context.get("event") or {}).get("correlation_id") or current_correlation_id.get()
        if not correlation or not step:
            return ""  # nothing to tell two sends of one event apart by: the step sends every time it runs
        what = f"event:{correlation}:{step.get('target')}:{step.get('index')}{':on_failure' if step.get('on_failure') else ''}"
    return f"{step.get('workflow') or 'workflow'}:{step.get('step_id') or step.get('index')}:{user_id}:{what}"[:400]


def _already_sent(session, group_id, key: str) -> bool:
    from marvin.db.models.groups.workflow_email_sends import WorkflowEmailSendModel as Sent

    return bool(key) and session.query(Sent.id).filter(Sent.group_id == group_id, Sent.send_key == key).first() is not None


def _claim(session, group_id, key: str, user_id, context: dict, subject: str):
    """Take the send for this key — the row, or None when someone already has it."""
    from marvin.db.models.groups.workflow_email_sends import WorkflowEmailSendModel as Sent

    begin_write(session)  # SQLite: the claim is a write; take the lock first so a rival waits for it rather than failing
    row = Sent(
        session=session,
        group_id=group_id,
        user_id=user_id,
        send_key=key,
        workflow_slug=(context.get("_step") or {}).get("workflow_slug"),
        subject=subject[:300],
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        session.rollback()  # ends the transaction begin_write opened
        return None
    session.commit()  # held before it is sent: a crash after the send never sends it again
    return row


def _release(session, row) -> None:
    session.delete(row)
    session.commit()


def _button(action: dict, context: dict) -> tuple[str, str]:
    text = str(interpolate(action.get("button_text") or "", context) or "").strip()[:60]
    link = str(interpolate(action.get("button_link") or "", context) or "").strip()
    if not text or not link:
        return "", ""
    if not _LINK.fullmatch(link):
        raise AutomationActionError("email step: button_link must be one http:// or https:// address")
    return text, link


def render_email(session, group_id, action: dict, context: dict, dry_run: bool):
    """(service, subject, html) — the email as the recipient would get it, in the workspace's layout."""
    from marvin.db.models.groups import Groups
    from marvin.services.email.email_service import EmailService, EmailTemplate

    subject = " ".join(_text(action.get("subject"), context, dry_run, "subject", MAX_SUBJECT_CHARS).split())
    body = _text(action.get("body"), context, dry_run, "body", MAX_BODY_CHARS)
    heading = " ".join(str(interpolate(action.get("heading") or "", context) or "").split())[:MAX_SUBJECT_CHARS] or subject
    button_text, button_link = _button(action, context)
    group = session.get(Groups, group_id)
    service = EmailService(group_id=str(group_id))
    template = EmailTemplate(
        subject=subject,
        header_text=heading,
        message_top=EmailService._markdown_to_html(body),
        button_text=button_text,
        button_link=button_link,
        workspace_name=getattr(group, "name", "") or "",
    )
    return service, subject, service.render(template)


@register_action("email")
def run_email(session, group_id, action, context, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    from marvin.services.email.email_senders import email_ready

    from ..authz import EMAIL_MIN_ROLE, ROLE_OWNER, require_role

    require_role(ROLE_OWNER if authorizer_role is None else authorizer_role, EMAIL_MIN_ROLE, "email step")
    raw_to = interpolate(action.get("to"), context)
    if dry_run and not str(raw_to or "").strip() and isinstance(action.get("to"), str) and _STEP_REF.search(action["to"]):
        recipient = {"to": f"‹{action['to'].strip()}›"}  # the person comes from a step that only previewed
        user = None
    else:
        user, role = find_member(session, group_id, raw_to)
        recipient = {"to": user.email, "user_id": str(user.id), "name": user.full_name or user.username, "role": role}
    service, subject, html = render_email(session, group_id, action, context, dry_run)
    key = _send_key(action, context, user.id if user else "preview")
    can_send = email_ready(group_id, session)

    if dry_run:
        done = _already_sent(session, group_id, key) if user else False
        return {
            "dry_run": True,
            "kind": "email",
            **recipient,
            "subject": subject,
            "body_html": html,
            "once": bool(key),
            "already_sent": done,
            "can_send": can_send,
            "would_send": bool(can_send and not done),
        }

    if not can_send:
        raise AutomationActionError(
            "email step: this workspace has no way to send email — add an SMTP profile (Settings → Email) or set up the platform's", code="no_email"
        )
    row = None
    if key:
        row = _claim(session, group_id, key, user.id, context, subject)
        if row is None:
            return {"sent": False, "skipped": True, "reason": "already sent", **recipient, "subject": subject}
    sent = False
    try:
        sent = bool(service.sender.send(user.email, subject, html))
    except Exception as e:  # noqa: BLE001 — a sender's failure is the step's
        if row is not None:
            _release(session, row)
        raise AutomationActionError(f"email step: sending to {user.email} failed: {e}", code="send_failed") from e
    if not sent:
        if row is not None:
            _release(session, row)
        raise AutomationActionError(f"email step: the mail server did not accept the email to {user.email}", code="send_failed")
    return {"sent": True, **recipient, "subject": subject}
