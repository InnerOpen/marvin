"""Why a due entry hasn't gone out: the record behind entries.scheduled_publish_blocked.

The Publish Scheduled Entries task runs every few minutes. When it holds a due entry back — the publish
gate refuses it, or the workspace only publishes approved entries on schedule — it records why on the
entry, so the editor can show it next to Scheduled Publish, and it notifies once per distinct block
(`notified`), not on every run. The record is shaped as:

    {"waiting_for": "requirements" | "approval", "reason": str, "issues": [str, ...],
     "at": ISO timestamp (first held back for this reason), "notified": bool}

It ends when the entry publishes, is archived, or its publish_at changes (`after_edit`). Any other edit
keeps it (the notice stays) but re-arms the notification, so a save that doesn't fix it is told again.
"""

from datetime import datetime

from marvin.services.entries.completeness import as_utc

WAITING_FOR_REQUIREMENTS = "requirements"
WAITING_FOR_APPROVAL = "approval"
APPROVAL_REASON = "Waiting for approval"
# Statuses that end the wait whatever else the edit does: the entry went out, or was put away.
_ENDS_WAIT = ("published", "archived")


def approval_issue(status: str) -> str:
    label = status.replace("_", " ").capitalize()
    return f"This workspace publishes only approved entries on schedule, and this one is '{label}'. Approve it to let it go out."


def block_record(waiting_for: str, reason: str, issues: list[str], previous: dict | None, now: datetime) -> dict:
    """The record for a block found now. The same block as `previous` (same kind, same issues) keeps
    its `at` and `notified`; a different one starts over, so it is notified again."""
    same = bool(previous) and previous.get("waiting_for") == waiting_for and previous.get("issues") == list(issues)
    return {
        "waiting_for": waiting_for,
        "reason": reason,
        "issues": list(issues),
        "at": previous.get("at") if same else now.isoformat(),
        "notified": bool(previous.get("notified")) if same else False,
    }


def after_edit(block: dict | None, changes: dict, publish_at) -> tuple[bool, dict | None]:
    """(changed, new record) for an entry update whose field changes are `changes` and whose stored
    publish_at is `publish_at`. Publishing, archiving or rescheduling ends the wait; any other edit
    re-arms the notification."""
    if not block:
        return False, block
    rescheduled = "publish_at" in changes and as_utc(changes["publish_at"]) != as_utc(publish_at)
    if changes.get("status") in _ENDS_WAIT or rescheduled:
        return True, None
    if block.get("notified"):
        return True, {**block, "notified": False}
    return False, block
