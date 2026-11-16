"""Approval steps: a workflow run that waits for a person (``{"kind": "approval", …}``).

**Park.** The engine reaches the step (actions/approval.py hands it a park request) and calls ``park``: the run's
snapshot (the event, the entry, the earlier steps' outputs, the target row — what a retry keeps,
services/integrations/errors.py) goes into a ``workflow_approvals`` row with the entry's version, the step is recorded
``waiting``, the run ends ``waiting``, and ``workflow_approval_requested`` tells the approvers (members at the step's
role or above: the push goes to them, Automation → Approvals lists it).

**Decide.** ``decide`` (a member at that role) or ``expire_due`` (the hourly sweep) settles it — approved, denied,
expired — and ``engine.resume_after_approval`` runs the steps after it in a new run (``retry_of`` the parked one), with
``${steps.<id>.output.decision}``. Approving an entry that has changed since it was asked settles it ``stale`` instead:
what the person approved isn't what would be acted on. A run resumed ``approved`` may call integration actions that
require approval (actions/integration.py); nothing else may.

**Boxes to change.** A step's `fields` are asked with their text (``starting_fields``: the step's `value`, or what a
Redo with changes carried to this entry). Approving may change them (``decide(fields=…)``, checked by ``edited_values``:
a person's text is data, never a Secret reference or a template); the run reads ``fields.<name>`` (``field_output``).
Approved with the step's `redo` choice, the changed boxes are kept on the row (``carry``) for the next approval on the
same entry with a box of that name, which takes them once.
"""

from __future__ import annotations

import re
import threading
from datetime import UTC, datetime, timedelta

from marvin.db.models.groups.workflow_approvals import APPROVAL_PENDING, WorkflowApprovalModel
from marvin.services.event_bus_service.event_types import EventTypes

from .actions.base import AutomationActionError
from .authz import ROLE_ADMIN, ROLE_EDITOR

ROLE_OF_APPROVERS = {"editor": ROLE_EDITOR, "admin": ROLE_ADMIN}
DECISIONS = {"approve": "approved", "deny": "denied"}
MAX_PENDING_LIST = 100
MAX_DECIDED_LIST = 50
MAX_MESSAGE = 600  # characters of the question a card, a list row and a push show
MAX_DETAIL = 20_000  # characters kept folded away under it (a whole image or voice prompt)
MAX_ENTRY_FILTER = 50  # entries one list request may name (the route refuses more)
MAX_FIELD_TEXT = 20_000  # characters of one box (schemas/group/automation_definition.MAX_FIELD_TEXT)
CARRY_LOOKBACK = 20  # the latest approvals of an entry searched for a Redo's carried text
# What a changed box may not bring in that its text did not have: a Secret reference (an integration argument whose
# whole value is {{NAME}} is replaced by that Secret) or a template (never resolved again, but never meant either).
_INJECTED = re.compile(r"\{\{\s*[A-Za-z0-9_]+\s*\}\}|\$\{")


class ApprovalError(Exception):
    """A decision that can't be taken (the message says why); ``status`` is the HTTP status that fits."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(UTC)  # NaiveDateTime stores UTC and reads it back aware


def _entry_version(session, entry_id) -> str | None:
    from marvin.db.models.platform.entries import Entries

    entry = session.get(Entries, entry_id) if entry_id else None
    stamp = getattr(entry, "update_at", None) or getattr(entry, "created_at", None)
    return stamp.isoformat() if stamp else None


def question(message: str, detail: str | None = None) -> tuple[str, str | None]:
    """What is asked, as it is kept: a `message` short enough to read at a glance and the `detail` folded away under it.
    A message over MAX_MESSAGE is not lost: its start stays as the message and the whole of it goes first in the detail."""
    message, detail = message.strip(), (detail or "").strip()
    if len(message) > MAX_MESSAGE:
        detail = f"{message}\n\n{detail}" if detail else message
        message = message[: MAX_MESSAGE - 1] + "…"
    return message, detail[:MAX_DETAIL] or None


def park(session, group_id, automation, context: dict, *, exec_id, step_index: int, target_index: int, step_id, spec: dict, run: dict):
    """Keep the run at this step and tell the approvers. Raises AutomationActionError when it can't wait (an unsaved
    workflow, a run too large to keep)."""
    from marvin.services.integrations.errors import _snapshot

    from .engine import approval_default_hours

    automation_id = getattr(automation, "id", None)
    if automation_id is None:
        raise AutomationActionError("an approval step needs a saved workflow to come back to")
    snapshot = _snapshot(context, run)
    if snapshot is None:
        raise AutomationActionError("this run is too large to wait for an approval")
    entry_id = (context.get("entry") or {}).get("id")  # the entry the run acts on, if any: its version is checked on approval
    message, detail = question(spec["message"], spec.get("detail"))
    row = WorkflowApprovalModel(
        session=session,
        group_id=group_id,
        automation_id=automation_id,
        execution_id=exec_id if exec_id is not None and not isinstance(exec_id, str) else None,
        step_index=step_index,
        step_id=step_id,
        target_index=target_index,
        message=message,
        detail=detail,
        min_role=ROLE_OF_APPROVERS.get(spec.get("approvers") or "editor", ROLE_EDITOR),
        status=APPROVAL_PENDING,
        snapshot=snapshot,
        entry_id=entry_id,
        entry_version=_entry_version(session, entry_id),
        expires_at=_now() + timedelta(hours=int(spec.get("expires_in_hours") or approval_default_hours(session, group_id))),
        choices=spec.get("choices") or None,
        image_url=spec.get("image") or None,
        fields=spec.get("fields") or None,
        carry={"redo": spec["redo"]} if spec.get("redo") else None,
    )
    session.add(row)
    session.commit()
    _emit(session, row, automation, EventTypes.workflow_approval_requested, user_id=(context.get("event") or {}).get("user_id"))
    return row


def _narrowed(query, group_id, *, automation: str | None = None, entry_ids=None, execution_id=None):
    """A list narrowed to one workflow (its slug), some entries, or the run that asked. In the query, before the list's
    cap: a page asking for its own cards finds them however many others wait."""
    if automation:
        from sqlalchemy import select

        from marvin.db.models.groups.automations import WorkspaceAutomationModel

        ids = select(WorkspaceAutomationModel.id).where(WorkspaceAutomationModel.group_id == group_id, WorkspaceAutomationModel.slug == automation)
        query = query.filter(WorkflowApprovalModel.automation_id.in_(ids))
    if entry_ids:
        query = query.filter(WorkflowApprovalModel.entry_id.in_(list(entry_ids)))
    if execution_id:
        query = query.filter(WorkflowApprovalModel.execution_id == execution_id)
    return query


def pending(session, group_id, role: int, **only) -> list[WorkflowApprovalModel]:
    """The approvals waiting in this workspace that a member at `role` may decide, oldest first. `only` narrows the
    list (`automation`, `entry_ids`, `execution_id`: see `_narrowed`)."""
    query = session.query(WorkflowApprovalModel).filter(
        WorkflowApprovalModel.group_id == group_id, WorkflowApprovalModel.status == APPROVAL_PENDING, WorkflowApprovalModel.min_role <= role
    )
    return _narrowed(query, group_id, **only).order_by(WorkflowApprovalModel.created_at).limit(MAX_PENDING_LIST).all()


def decide(
    session,
    group_id,
    approval_id,
    decision: str,
    *,
    user_id,
    role: int,
    note: str | None = None,
    choice=None,
    fields: dict | None = None,
    logger=None,
    background: bool | None = False,
) -> WorkflowApprovalModel:
    """A person approves or denies; the run goes on. An approval with choices is approved with one of them (`choice`:
    its label, or its index); one with boxes may be approved with them changed (`fields`: {name: text}, see
    `edited_values`; a deny ignores them). Raises ApprovalError (404 unknown, 403 not theirs to decide, 409 already
    decided or expired, 422 no such choice or a box that can't be taken). With `background` the decision is recorded
    and returned at once and the run goes on behind it (a request handler passes it: the steps after an approval can
    take a minute, an image say); `background=None` only records it, for a caller that resumes it itself (decide_many)."""
    row = session.get(WorkflowApprovalModel, approval_id)
    if row is None or str(row.group_id) != str(group_id):
        raise ApprovalError("No such approval.", 404)
    if role < row.min_role:
        raise ApprovalError("This approval needs a member at a higher workspace role.", 403)
    if row.status != APPROVAL_PENDING:
        raise ApprovalError(f"It was already decided: {row.status}.")
    if row.expires_at <= _now():
        raise ApprovalError("It has expired; the workflow goes on as expired.")
    if decision not in DECISIONS:
        raise ApprovalError("Decide approve or deny.", 422)
    outcome = DECISIONS[decision]
    picked = _picked(row, choice) if outcome == "approved" else None
    changed = edited_values(row.fields, fields) if outcome == "approved" else {}
    if outcome == "approved" and row.entry_id and row.entry_version and _entry_version(session, row.entry_id) != row.entry_version:
        outcome = "stale"  # the entry changed after it was asked: nothing approved is applied to other content
    return settle(session, row, outcome, user_id=user_id, note=note, choice=picked, changed=changed, logger=logger, background=background)


MAX_DECIDE_MANY = 50  # approvals one "Approve all" may answer


def decide_many(session, group_id, items: list[dict], decision: str, *, user_id, role: int, note: str | None = None, logger=None) -> list[dict]:
    """Answer several waiting approvals at once ("Approve all 20"): each `{id, choice?, fields?}` is decided as `decide` would,
    with its own boxes, and the runs go on one after another on a thread of their own (twenty paid calls are made in turn, not
    all at once). One that can't be taken (already decided, a box refused) says why and the rest still go: ``[{id, status} |
    {id, error, code}]``, in the order given. Raises ApprovalError (422) for more than MAX_DECIDE_MANY or none."""
    if not items:
        raise ApprovalError("Name the approvals to decide.", 422)
    if len(items) > MAX_DECIDE_MANY:
        raise ApprovalError(f"At most {MAX_DECIDE_MANY} approvals at once.", 422)
    results: list[dict] = []
    settled: list = []
    for item in items:
        try:
            row = decide(
                session,
                group_id,
                item["id"],
                decision,
                user_id=user_id,
                role=role,
                note=note,
                choice=item.get("choice"),
                fields=item.get("fields"),
                logger=logger,
                background=None,
            )
        except ApprovalError as e:
            session.rollback()
            results.append({"id": str(item["id"]), "error": str(e), "code": e.status})
            continue
        settled.append(row.id)
        results.append({"id": str(row.id), "status": row.status})
    if settled:
        threading.Thread(target=_resume_many, args=(settled, user_id), name=f"approvals-{len(settled)}", daemon=True).start()
    return results


def _resume_many(approval_ids: list, user_id) -> None:
    """Go on with each settled approval's run in turn (see _resume_job): one failing never stops the others."""
    for approval_id in approval_ids:
        _resume_job(approval_id, user_id)


def _as_text(value) -> str:
    """A box's text as a template resolved it: nothing is empty, a list or an object is its JSON (as embedding it in a
    longer template would give), anything else its string. Never stripped: the box holds what the step would send."""
    import json

    if value is None:
        return ""
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def starting_fields(session, group_id, entry_id, raw, context: dict, *, take: bool) -> list[dict]:
    """An approval step's boxes as they are asked: each `value` resolved, or — when a Redo with changes carried a text
    of that name to this entry — that text instead. `take` (a real run) removes what it used, so it is used once."""
    from .actions.base import AutomationActionError
    from .matcher import interpolate

    specs = [f.model_dump() if hasattr(f, "model_dump") else dict(f) for f in raw or [] if f]
    if not specs:
        return []
    carried = _carried(session, group_id, entry_id, {str(f.get("name")) for f in specs}, take=take)
    fields = []
    for spec in specs:
        name = str(spec.get("name") or "")
        value = carried[name] if name in carried else _as_text(interpolate(spec.get("value") or "", context))
        if len(value) > MAX_FIELD_TEXT:
            raise AutomationActionError(f"the approval's field “{name}” is {len(value):,} characters: at most {MAX_FIELD_TEXT:,} can be shown")
        fields.append(
            {
                "name": name,
                "label": str(spec.get("label") or name.replace("_", " ").capitalize()),
                "type": spec.get("type") or "textarea",
                "value": value,
                "max_length": int(spec.get("max_length") or MAX_FIELD_TEXT),
                "required": spec.get("required", True) is not False,
                **({"carried": True} if name in carried else {}),
            }
        )
    return fields


def _carried(session, group_id, entry_id, names: set[str], *, take: bool) -> dict:
    """The texts a Redo with changes left for these box names on this entry: from its latest approvals, newest first.
    `take` removes them from where they were left (committed), so the next try is the only one to start from them."""
    from sqlalchemy.orm.attributes import flag_modified

    if not entry_id or not names:
        return {}
    rows = (
        session.query(WorkflowApprovalModel)
        .filter(WorkflowApprovalModel.group_id == group_id, WorkflowApprovalModel.entry_id == entry_id, WorkflowApprovalModel.status == "approved")
        .order_by(WorkflowApprovalModel.decided_at.desc().nullslast())
        .limit(CARRY_LOOKBACK)
        .all()
    )
    found: dict = {}
    for row in rows:
        left = dict((row.carry or {}).get("values") or {})
        hits = {k: v for k, v in left.items() if k in names and k not in found and isinstance(v, str)}
        if not hits:
            continue
        found.update(hits)
        if take:
            rest = {k: v for k, v in left.items() if k not in hits}
            row.carry = {**(row.carry or {}), "values": rest} if rest else {k: v for k, v in (row.carry or {}).items() if k != "values"}
            flag_modified(row, "carry")
    if take and found:
        session.commit()
    return found


def auto_approved(fields: list[dict], choices: list[str] | None) -> dict:
    """The output of an approval whose `approved_when` holds: approved without asking (nobody decided), its boxes as
    they are. Not a person's approval: it lets nothing run that needs one (the run is not marked approved)."""
    out: dict = {"decision": "approved", "approved": True, "auto": True, "decided_by": None, "decided_by_name": None, "note": None}
    if choices:
        out.update({"choice": None, "choice_index": None})
    if fields:
        out.update({"fields": {f["name"]: f["value"] for f in fields}, "edited": []})
    return out


def _normal(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def edited_values(fields: list[dict] | None, given: dict | None) -> dict:
    """The boxes a person changed, checked: {name: text} for each whose text differs from what it was asked with. Line
    ends are taken as \\n, and a text that only lost the one leading line break a browser's text box drops is the same
    text. Raises ApprovalError (422): an unknown box, a non-text, too long, blank when required, or a change that brings
    in a Secret reference ({{NAME}}) or a template (${…}) the asked text did not have."""
    if not given:
        return {}
    if not isinstance(given, dict):
        raise ApprovalError("fields must be an object of {name: text}.", 422)
    asked = {f["name"]: f for f in fields or []}
    changed: dict = {}
    for name, raw in given.items():
        field = asked.get(name)
        if field is None:
            raise ApprovalError(f"This approval has no field “{name}”." if asked else "This approval has no fields to change.", 422)
        if not isinstance(raw, str):
            raise ApprovalError(f"“{field['label']}” must be text.", 422)
        before, text = field.get("value") or "", _normal(raw)
        if text == before or "\n" + text == before or text == _normal(before):
            continue
        if len(text) > int(field.get("max_length") or MAX_FIELD_TEXT):
            raise ApprovalError(f"“{field['label']}” is {len(text):,} characters: at most {int(field.get('max_length') or MAX_FIELD_TEXT):,}.", 422)
        if field.get("required", True) and not text.strip():
            raise ApprovalError(f"“{field['label']}” can't be empty.", 422)
        brought = {m.group(0) for m in _INJECTED.finditer(text)} - {m.group(0) for m in _INJECTED.finditer(before)}
        if brought:
            raise ApprovalError(f"“{field['label']}” can't take {sorted(brought)[0]}: a changed text is sent as written, never filled in.", 422)
        changed[name] = text
    return changed


def field_output(row: WorkflowApprovalModel) -> dict:
    """What the steps after a settled approval with boxes read: `fields` {name: text} — as approved, else as asked (a
    deny, an expiry, a stale approval) — and `edited` (the names changed)."""
    if not row.fields:
        return {}
    asked = {f["name"]: f.get("value", "") for f in row.fields}
    approved = row.field_values if row.status == "approved" and isinstance(row.field_values, dict) else {}
    return {"fields": {**asked, **{k: v for k, v in approved.items() if k in asked}}, "edited": edited_names(row)}


def edited_names(row: WorkflowApprovalModel) -> list[str]:
    """The boxes a person changed on approving (none unless approved)."""
    if not row.fields or row.status != "approved" or not isinstance(row.field_values, dict):
        return []
    return [f["name"] for f in row.fields if f["name"] in row.field_values and row.field_values[f["name"]] != f.get("value", "")]


def _picked(row: WorkflowApprovalModel, choice) -> str | None:
    """The chosen label of an approval with choices (given as the label, or its index); None for one without."""
    offered = row.choices or []
    if not offered:
        return None
    if choice in (None, ""):
        raise ApprovalError("Pick one of the choices to approve.", 422)
    if isinstance(choice, int) and not isinstance(choice, bool) and 0 <= choice < len(offered):
        return offered[choice]
    if isinstance(choice, str) and choice.strip() in offered:
        return choice.strip()
    raise ApprovalError(f"No such choice. The choices are: {', '.join(offered)}.", 422)


def settle(
    session,
    row: WorkflowApprovalModel,
    outcome: str,
    *,
    user_id=None,
    note: str | None = None,
    choice: str | None = None,
    changed: dict | None = None,
    logger=None,
    background: bool | None = False,
) -> WorkflowApprovalModel:
    """Record the outcome — claimed first, so two deciders can't both resume it — and resume the run (on a thread of
    its own when `background`, so the caller isn't held while the steps after the approval run). `changed`: the boxes
    an approval was approved with changed ({name: text}); kept only when it was approved."""
    from sqlalchemy import update

    values: dict = {"status": outcome, "decided_by": user_id, "decided_at": _now(), "note": (note or "").strip() or None, "choice": choice}
    if row.fields and outcome == "approved":
        values["field_values"] = {**{f["name"]: f.get("value", "") for f in row.fields}, **(changed or {})}
        redo = (row.carry or {}).get("redo")
        if redo and choice == redo and changed:  # a Redo with changes: the next try starts from them
            values["carry"] = {"redo": redo, "values": dict(changed)}
    claimed = session.execute(
        update(WorkflowApprovalModel).where(WorkflowApprovalModel.id == row.id, WorkflowApprovalModel.status == APPROVAL_PENDING).values(**values)
    ).rowcount
    session.commit()
    if not claimed:
        session.refresh(row)
        raise ApprovalError(f"It was already decided: {row.status}.")
    session.refresh(row)
    _stamp_picture(session, row, logger=logger)
    if background is None:  # the caller goes on with the run itself (decide_many: one after another)
        return row
    if background:
        threading.Thread(target=_resume_job, args=(row.id, user_id), name=f"approval-{str(row.id)[:8]}", daemon=True).start()
        return row
    from .engine import resume_after_approval

    resume_after_approval(session, row, logger=logger)
    _emit(session, row, None, EventTypes.workflow_approval_decided, user_id=user_id)
    return row


def _resume_job(approval_id, user_id) -> None:
    """Go on with a settled approval's run on its own database session (the request that decided it has finished with
    its own). The run records its own outcome; anything that escapes is logged, since nobody is waiting to be told."""
    from marvin.core.root_logger import get_logger
    from marvin.db.db_setup import session_context

    from .engine import resume_after_approval

    logger = get_logger(__name__)
    try:
        with session_context() as session:
            row = session.get(WorkflowApprovalModel, approval_id)
            if row is None:
                return
            resume_after_approval(session, row, logger=logger)
            _emit(session, row, None, EventTypes.workflow_approval_decided, user_id=user_id)
    except Exception:  # noqa: BLE001 — nobody is waiting on this thread
        logger.error("resuming the run after approval %s failed", approval_id, exc_info=True)


# Written onto the pictured asset's metadata when an approval that showed it is settled (see _stamp_picture).
DECISIONS_KEPT = ("approved", "denied", "expired", "stale")


def _stamp_picture(session, row: WorkflowApprovalModel, *, logger=None) -> None:
    """An approval that showed a picture leaves its outcome on that asset: ``metadata.approval`` = the decision, who
    and when, the note, and the approval's id. A denied generated image is kept in the library like any other, so
    without this nothing would tell it from one that was kept — the asset page says it, the library filters on it
    (``decision`` in services/item_query.py), and a housekeeping workflow can trash denied pictures later. The URL
    must be one of this workspace's assets (its storage key in it); any other picture is left alone. Best-effort: a
    failure here never undoes the decision."""
    import logging

    from sqlalchemy.orm.attributes import flag_modified

    from marvin.db.models.platform import Assets
    from marvin.db.models.users.users import Users

    if not row.image_url or row.status not in DECISIONS_KEPT:
        return
    try:
        asset = next(
            (
                a
                for a in session.query(Assets).filter(Assets.group_id == row.group_id, Assets.storage_key.isnot(None))
                if a.storage_key in row.image_url
            ),
            None,
        )
        if asset is None:
            return
        decider = session.get(Users, row.decided_by) if row.decided_by else None
        meta = dict(asset.metadata_json or {})
        meta["approval"] = {
            "decision": row.status,
            "decided_by": str(row.decided_by) if row.decided_by else None,
            "decided_by_name": getattr(decider, "full_name", None) or getattr(decider, "username", None),
            "decided_at": row.decided_at.isoformat() if row.decided_at else None,
            "note": row.note,
            "approval_id": str(row.id),
        }
        asset.metadata_json = meta
        flag_modified(asset, "metadata_json")
        session.commit()
    except Exception:  # noqa: BLE001 — the decision stands either way
        session.rollback()
        (logger or logging.getLogger(__name__)).warning("approval %s: could not record the decision on its picture", row.id, exc_info=True)


def expire_due(session, *, logger=None, now: datetime | None = None) -> int:
    """Settle every pending approval past its time as `expired` (the run goes on, so it can act on that)."""
    due = (
        session.query(WorkflowApprovalModel)
        .filter(WorkflowApprovalModel.status == APPROVAL_PENDING, WorkflowApprovalModel.expires_at <= (now or _now()))
        .limit(MAX_PENDING_LIST)
        .all()
    )
    done = 0
    for row in due:
        try:
            settle(session, row, "expired", logger=logger)
            done += 1
        except ApprovalError:
            continue  # decided meanwhile
    return done


def decided(session, group_id, role: int, *, limit: int = MAX_DECIDED_LIST, **only) -> list[WorkflowApprovalModel]:
    """The approvals already settled in this workspace that a member at `role` may see (the ones they could have decided),
    newest decision first: who decided, when, what they said, the note. `only` narrows the list as it does `pending`."""
    query = session.query(WorkflowApprovalModel).filter(
        WorkflowApprovalModel.group_id == group_id, WorkflowApprovalModel.status.in_(DECISIONS_KEPT), WorkflowApprovalModel.min_role <= role
    )
    return (
        _narrowed(query, group_id, **only)
        .order_by(WorkflowApprovalModel.decided_at.desc().nullslast(), WorkflowApprovalModel.created_at.desc())
        .limit(limit)
        .all()
    )


def count_pending(session, group_id, role: int) -> int:
    from sqlalchemy import func

    return (
        session.query(func.count(WorkflowApprovalModel.id))
        .filter(WorkflowApprovalModel.group_id == group_id, WorkflowApprovalModel.status == APPROVAL_PENDING, WorkflowApprovalModel.min_role <= role)
        .scalar()
        or 0
    )


def _emit(session, row: WorkflowApprovalModel, automation, event_type, *, user_id=None) -> None:
    """workflow_approval_requested / _decided — best-effort: a failed dispatch never undoes the park or the decision."""
    import logging

    try:
        from marvin.db.models.groups.automations import WorkspaceAutomationModel
        from marvin.services.event_bus_service.event_bus_service import EventBusService
        from marvin.services.event_bus_service.event_types import EventWorkflowApprovalData

        automation = automation or session.get(WorkspaceAutomationModel, row.automation_id)
        data = EventWorkflowApprovalData(
            approval_id=row.id,
            automation_id=row.automation_id,
            automation_name=getattr(automation, "name", None),
            automation_slug=getattr(automation, "slug", None),
            message=row.message,
            min_role=row.min_role,
            status=row.status,
            entry_id=row.entry_id,
            expires_at=row.expires_at.isoformat(),
            note=row.note,
            image_url=row.image_url,
            edited_fields=edited_names(row) or None,
        )
        verb = "is waiting for approval" if event_type == EventTypes.workflow_approval_requested else f"approval: {row.status}"
        EventBusService(bg_tasks=None).dispatch(
            integration_id="automations",
            group_id=row.group_id,
            event_type=event_type,
            document_data=data,
            message=f"{getattr(automation, 'name', 'A workflow')} {verb} — {row.message}",
            user_id=user_id,
            entity_id=row.id,
            entity_type="workflow_approval",
        )
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning(f"workflow approval event {event_type.name} not sent: {e}")


def post_preview(session, row) -> dict | None:
    """When the step after this pending approval posts to social networks (an integration step with `capability: social.post`),
    what it will post — its `text` and `link` interpolated as the approved run will — checked for each network
    (services/integrations/caption_check.py): ``{text, results}``. None for anything else; never raises (a preview must not break
    the approvals list)."""
    try:
        return _post_preview(session, row)
    except Exception:  # noqa: BLE001 — a preview is a convenience
        return None


def _post_preview(session, row) -> dict | None:
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.services.integrations import INTEGRATIONS_AVAILABLE

    from .engine import _parked_step, resumed_context
    from .matcher import interpolate

    if row.status != APPROVAL_PENDING or not INTEGRATIONS_AVAILABLE:
        return None
    automation = session.get(WorkspaceAutomationModel, row.automation_id)
    parked = _parked_step(automation, row, "approval") if automation is not None else None
    if parked is None:
        return None
    index, _ = parked
    actions = (automation.definition or {}).get("actions") or []
    step = actions[index + 1] if index + 1 < len(actions) else None
    if not (isinstance(step, dict) and step.get("kind") == "integration" and step.get("capability") == "social.post"):
        return None
    output = {"decision": "approved", "approved": True}
    context = resumed_context(session, row, index, output)
    context["steps"], context["previous"] = context.pop("_steps"), output
    args = step.get("args") if isinstance(step.get("args"), dict) else {}
    text = str(interpolate(args.get("text") or "", context) or "")
    link = interpolate(args.get("link"), context) if args.get("link") else None
    integration = str(interpolate(step.get("integration") or "", context) or "").strip()
    from marvin.services.integrations.caption_check import check_for_networks

    results = check_for_networks(session, row.group_id, text, link=str(link) if link else None, integrations=[integration] if integration else None)
    return {"text": text, "results": results}
