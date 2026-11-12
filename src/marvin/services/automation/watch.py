"""Following the worker job a workflow run started.

A workflow that needs real computation (a render, a check, an import) makes a ``job`` record and a worker picks it up (marvin-worker: the
record's ``data.kind`` names what to do and ``data.status`` goes ``queued`` -> ``claimed`` -> ``running`` -> ``done`` or ``failed``, with
``result`` and ``log`` written back). Running the workflow only starts it. This is how a caller that is not looking at a screen (the CLI, an
agent, an MCP host) gets the outcome too: it names the entry the run created or changed, waits a little, and says where the job stands.
Nothing here knows what a job does.
"""

import time
import uuid
from collections.abc import Callable
from typing import Any

ACTIVE = ("queued", "claimed", "running")
FINISHED = ("done", "failed")
MAX_WAIT = 55  # seconds: a tool call has to answer inside a client's timeout; a longer job is followed with get_entry
LOG_LIMIT = 8000  # characters of the job's log returned: the rest is on the record


def entry_of(run: dict | None) -> str | None:
    """The id of the entry a run's last step created or changed (`entry_id` in its result), when it says."""
    result = (run or {}).get("result")
    value = result.get("entry_id") if isinstance(result, dict) else None
    return str(value) if value else None


def outcome(slug: str, data: Any) -> dict | None:
    """Where a worker job stands, or None when the entry is not one (no kind, or a status that is not the worker's)."""
    if not isinstance(data, dict) or not data.get("kind") or data.get("status") not in ACTIVE + FINISHED:
        return None
    log = str(data.get("log") or "")
    return {
        "slug": slug,
        "kind": data["kind"],
        "status": data["status"],
        "finished": data["status"] in FINISHED,
        **({"result": data["result"]} if data.get("result") is not None else {}),
        **({"log": log[-LOG_LIMIT:]} if log else {}),
    }


def wait_for_job(
    read: Callable[[], tuple[str, Any] | None], seconds: float, *, poll: float = 1.0, sleep=time.sleep, clock=time.monotonic
) -> dict | None:
    """Follow a job for up to `seconds`: `read()` gives its (slug, data) as it is now. Returns the outcome when it finished, or where it had got to
    when the time was up (`finished` False); None when the entry is not a worker job at all."""
    deadline = clock() + max(0.0, min(float(seconds), MAX_WAIT))
    while True:
        now = read()
        if now is None:
            return None
        found = outcome(*now)
        if found is None or found["finished"] or clock() >= deadline:
            return found
        sleep(min(poll, max(0.0, deadline - clock())))


def follow(session, group_id, entry_id: str, seconds: float) -> dict | None:
    """`wait_for_job` on an entry of a workspace, read fresh each time (the worker writes it from another process)."""
    from marvin.db.models.platform.entries import Entries

    try:
        eid = uuid.UUID(str(entry_id))
    except ValueError:
        return None

    def read():
        session.expire_all()
        row = session.get(Entries, eid)
        return None if row is None or row.group_id != group_id else (row.slug, row.data_json)

    return wait_for_job(read, seconds)
