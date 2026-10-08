"""One-tap Approve / Deny on an AI-approval push (services/push_notifications.py sends it).

Chromium (desktop and Android) shows a notification's action buttons; iOS and the rest don't, and tapping the
notification opens the Ask thread as always. Approve is offered only when everything the run waits on can be
undone in Marvin — the tools in ``RESTORABLE_TOOLS``: the Trash and restoring from it (a ``match`` included),
archiving, attaching or detaching tags, adding to or removing from a collection. Anything else — publishing,
email, an integration's actions, a workflow, compose/revise, a hand-off's specialist doing any of those — gets
no buttons: the person opens the thread and looks first. Decided from the parked record, server-side, at send
time and again when the button is used; never from what the push or the request says.

The buttons need no session cookie (a service worker may have none): the push carries a token that decides
exactly that one approval (the root thread, and the park it was minted for) as that one user, approve or deny,
once, for ``TOKEN_TTL``. Only its SHA-256 is stored (``push_action_tokens``). It stops working as soon as the
approval is decided any other way (the park it names is gone), when used, and when it expires. Attempts per
approval are rate-limited. Using it runs the same resume the Ask page does (routes/users/push_controller.py
builds the Ask controller as that user), recorded the same way: ``approval_granted`` / ``approval_rejected``
and the execution's approvals audit, with the surface ``push``.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from marvin.core.root_logger import get_logger

logger = get_logger(__name__)

APPROVE, DENY = "approve", "deny"
DECISIONS = (APPROVE, DENY)
SURFACE = "push"
"""How the approvals audit and the approval events name a decision taken from a notification."""
TOKEN_TTL = timedelta(minutes=15)
MAX_TOKEN = 128
RATE_LIMIT = (10, 15)
"""At most this many attempts per approval in this many minutes."""

RESTORABLE_TOOLS = frozenset(
    {
        "trash_entries",
        "restore_entries",
        "archive_entries",
        "attach_tag",
        "detach_tag",
        "add_to_collection",
        "remove_from_collection",
    }
)
"""Tools whose every effect a person can undo in Marvin (restore, unarchive, detach, remove)."""

_DONE = {
    "attach_tag": "attached the tags",
    "detach_tag": "removed the tags",
    "add_to_collection": "added to the collection",
    "remove_from_collection": "removed from the collection",
    "trash_entries": "moved to the Trash",
    "restore_entries": "restored from the Trash",
    "archive_entries": "archived",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def calls_of(record: dict | None) -> list[dict]:
    """Every call the user decides on a parked root, a hand-off's specialists' included."""
    from marvin.services.ai.agent import flatten_pending

    return flatten_pending((record or {}).get("calls"))


def restorable(record: dict | None) -> bool:
    """Whether one tap may approve this parked record: it waits on something, and only on restorable tools (a
    hand-off is flattened to its specialist's own calls; one without them stays ``run_agent``, never restorable)."""
    calls = calls_of(record)
    return bool(calls) and all(c.get("tool") in RESTORABLE_TOOLS for c in calls)


# --------------------------------------------------------------------------------------------------
# Minting
# --------------------------------------------------------------------------------------------------


def mint(session: Session, root, user_id) -> str | None:
    """A token for the push about ``root``'s park, for ``user_id`` — or None when one tap mustn't approve it
    (not parked, not restorable, not that user's). Sweeps expired tokens. Commits."""
    from marvin.db.models.users.push_action_tokens import PushActionTokenModel
    from marvin.services.ai.threads import pending_state

    record = pending_state(root)
    if record is None or not record.get("parked_at") or str(root.created_by) != str(user_id) or not restorable(record):
        return None
    now = _now()
    session.query(PushActionTokenModel).filter(PushActionTokenModel.expires_at < now - timedelta(hours=1)).delete(synchronize_session=False)
    token = secrets.token_urlsafe(32)
    session.add(
        PushActionTokenModel(
            session=session,
            user_id=user_id,
            thread_id=root.id,
            parked_at=str(record["parked_at"]),
            token_hash=_hash(token),
            expires_at=now + TOKEN_TTL,
        )
    )
    session.commit()
    return token


# --------------------------------------------------------------------------------------------------
# Using one
# --------------------------------------------------------------------------------------------------


class Refused(Exception):
    """The button can't decide the approval; ``message`` says why, for the notification."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


INVALID = "This button no longer works. Open the conversation to decide."
DECIDED = "This approval was already decided."
EXPIRED = "This button expired. Open the conversation to decide."
NEEDS_A_LOOK = "This one needs a look first. Open the conversation to decide."


@dataclass
class Claim:
    thread: object
    user_id: uuid.UUID
    calls: list[dict]


def _uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def claim(session: Session, approval_id, token: str, decision: str) -> Claim:
    """Check ``token`` against approval ``approval_id`` and use it up (whoever claims it first wins). Raises
    ``Refused`` when it can't decide: unknown, another approval's, tampered (404), used or the approval decided
    already (409), expired (410), the approval isn't restorable (403), too many attempts (429). Commits."""
    from marvin.db.models.groups.ai_threads import AIThreadModel
    from marvin.db.models.users.push_action_tokens import PushActionTokenModel
    from marvin.services.ai.threads import pending_state
    from marvin.services.security.rate_limit_service import RateLimitService

    if decision not in DECISIONS:
        raise Refused(404, INVALID)
    approval = _uuid(approval_id)
    if approval is None or not isinstance(token, str) or not token or len(token) > MAX_TOKEN:
        raise Refused(404, INVALID)
    attempts, minutes = RATE_LIMIT
    if not RateLimitService(session).check_subject_limit(approval, "push-action", attempts, minutes):
        raise Refused(429, "Too many attempts. Open the conversation to decide.")
    row = session.query(PushActionTokenModel).filter_by(token_hash=_hash(token)).first()
    if row is None or _uuid(row.thread_id) != approval:
        raise Refused(404, INVALID)
    if row.used_at is not None:
        raise Refused(409, DECIDED)
    if row.expires_at <= _now():
        raise Refused(410, EXPIRED)
    thread = session.get(AIThreadModel, row.thread_id)
    record = pending_state(thread) if thread is not None else None
    if record is None or str(record.get("parked_at")) != row.parked_at:
        raise Refused(409, DECIDED)
    if str(thread.created_by) != str(row.user_id):
        raise Refused(404, INVALID)
    if not restorable(record):
        raise Refused(403, NEEDS_A_LOOK)
    used = session.execute(
        update(PushActionTokenModel)
        .where(PushActionTokenModel.id == row.id, PushActionTokenModel.used_at.is_(None))
        .values(used_at=_now())
        .execution_options(synchronize_session=False)
    )
    session.commit()
    if used.rowcount != 1:
        raise Refused(409, DECIDED)
    return Claim(thread=thread, user_id=_uuid(row.user_id), calls=calls_of(record))


# --------------------------------------------------------------------------------------------------
# The confirmation
# --------------------------------------------------------------------------------------------------


def _plural(n: int, word: str) -> str:
    if n == 1:
        return f"1 {word}"
    if word.endswith("y") and word[-2:-1] not in "aeiou":
        return f"{n} {word[:-1]}ies"
    return f"{n} {word}s"


def _result(call: dict, steps: list) -> dict | None:
    """The tool's answer to this approved call, from the resumed run's steps (same tool and arguments)."""
    for step in steps or []:
        if not isinstance(step, dict) or step.get("tool") != call.get("tool") or (step.get("arguments") or {}) != (call.get("arguments") or {}):
            continue
        raw = step.get("result")
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


_MOVED = {
    "trash_entries": (("trashed", "trashedAssets", "trashedResources"), "moved {} to the Trash"),
    "restore_entries": (("restored", "restoredAssets", "restoredResources"), "restored {} from the Trash"),
    "archive_entries": (("archived",), "archived {}"),
}


def _done(call: dict, steps: list) -> str:
    tool = str(call.get("tool") or "")
    result = _result(call, steps)
    if result is not None and result.get("error"):
        return f"{tool}: {str(result['error'])[:120]}"
    if tool in _MOVED and result is not None:
        keys, text = _MOVED[tool]
        n = sum(len(result.get(k) or []) for k in keys)
        noun = "entry" if not any(result.get(k) for k in keys[1:]) else "item"
        return text.format(_plural(n, noun))
    preview = call.get("preview") if isinstance(call.get("preview"), dict) else {}
    if preview.get("action") in ("attach", "detach") and preview.get("items"):
        attach = preview["action"] == "attach"
        items = _plural(len(preview["items"]), str(preview.get("itemKind") or "item"))
        targets = _plural(int(preview.get("targetCount") or 0), str(preview.get("targetType") or "item"))
        return f"{'attached' if attach else 'detached'} {items} {'to' if attach else 'from'} {targets}"
    return _DONE.get(tool, "done")


def confirmation(decision: str, calls: list[dict], response: dict | None) -> str:
    """The confirmation notification's line: "Approved — moved 78 entries to the Trash", or "Denied"."""
    if decision == DENY:
        return "Denied — nothing was changed."
    steps = (response or {}).get("steps") if isinstance((response or {}).get("steps"), list) else []
    done = "; ".join(dict.fromkeys(_done(c, steps) for c in calls))
    line = f"Approved — {done}" if done else "Approved"
    return line[:1].upper() + line[1:]


def inbox_count(session: Session, group_id) -> int | None:
    """The workspace's inbox count — what the installed app's icon badge shows."""
    from sqlalchemy import func

    from marvin.db.models.platform.entries import Entries

    try:
        return int(session.query(func.count(Entries.id)).filter(Entries.group_id == group_id, Entries.status == "inbox").scalar() or 0)
    except Exception:  # noqa: BLE001 — the badge is a nicety
        session.rollback()
        return None
