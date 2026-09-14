"""Live progress of in-flight agent runs, for the Ask page's step timeline.

Process-local, like model_pull._JOBS: the run's own request thread pushes events under a lock and a
poller reads them back by run id. That is the whole design — no queue, no second session, no
background thread — which is exactly right for the one-replica deployment this ships to (SQLite
over NFS). With more than one backend replica a poll can land on a pod that never saw the run and
gets 404; the client treats that as "no live steps", nothing worse. Token streaming is a separate,
provider-level change.

The client mints the run id (a UUID it sends as `client_run_id`) so it can start polling while the
POST is still in flight. Entries are owned by (group, user): a guessed id from another user is a 404.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

_LOCK = threading.Lock()
_RUNS: dict[str, RunProgress] = {}
_MAX_RUNS = 100
_FINISHED_TTL_SECONDS = 600  # a finished run stays pollable for a while, then goes


@dataclass
class RunProgress:
    id: str
    owner: tuple[str, str]  # (group_id, user_id)
    status: str = "running"  # running | completed | failed | awaiting_approval
    events: list[dict] = field(default_factory=list)
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None

    @property
    def done(self) -> bool:
        return self.finished_at is not None

    def to_dict(self) -> dict:
        return {"id": self.id, "status": self.status, "events": list(self.events)}


def normalize_run_id(value: str | None) -> str | None:
    """A client-supplied run id, or None when absent/junk — the registry only keys on real UUIDs."""
    if not value:
        return None
    try:
        return str(uuid.UUID(str(value).strip()))
    except (ValueError, TypeError, AttributeError):
        return None


def start(run_id: str, owner: tuple) -> RunProgress:
    run = RunProgress(id=run_id, owner=(str(owner[0]), str(owner[1])))
    with _LOCK:
        _RUNS[run_id] = run
        _prune_locked()
    return run


def push(run_id: str, event: dict) -> None:
    with _LOCK:
        run = _RUNS.get(run_id)
        if run is not None:
            run.events.append({**event, "at": time.time()})


def finish(run_id: str, status: str) -> None:
    with _LOCK:
        run = _RUNS.get(run_id)
        if run is not None:
            run.status = status
            run.finished_at = time.monotonic()


def get(run_id: str, owner: tuple) -> RunProgress | None:
    """The run's progress for its owner; None when unknown, expired, or someone else's."""
    key = (str(owner[0]), str(owner[1]))
    with _LOCK:
        _prune_locked()
        run = _RUNS.get(run_id)
        if run is None or run.owner != key:
            return None
        return RunProgress(
            id=run.id, owner=run.owner, status=run.status, events=list(run.events), started_at=run.started_at, finished_at=run.finished_at
        )


def _prune_locked() -> None:
    """Drop finished runs past their TTL, then the oldest finished ones beyond the cap (under _LOCK)."""
    now = time.monotonic()
    for rid in [rid for rid, r in _RUNS.items() if r.done and now - (r.finished_at or now) > _FINISHED_TTL_SECONDS]:
        _RUNS.pop(rid, None)
    if len(_RUNS) <= _MAX_RUNS:
        return
    finished = sorted((r for r in _RUNS.values() if r.done), key=lambda r: r.finished_at or 0)
    for r in finished[: len(_RUNS) - _MAX_RUNS]:
        _RUNS.pop(r.id, None)


def _reset_for_tests() -> None:
    with _LOCK:
        _RUNS.clear()
