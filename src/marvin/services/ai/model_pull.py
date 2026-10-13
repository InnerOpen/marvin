"""Track in-progress Ollama model pulls so the UI can show a progress bar without holding an HTTP
request open for the whole (multi-minute, multi-GB) download.

A pull runs in a daemon thread that streams Ollama's /api/pull progress into an in-memory job
record; the API exposes start (returns a job id) + poll (returns the record). This is deliberately
process-local and non-durable — it's an admin convenience, not a queue. In a multi-worker/replica
deployment a job is only visible on the worker that started it; a restart forgets in-flight pulls
(the pull itself continues in Ollama regardless — re-pulling is idempotent). Good enough for the
single-process dev/self-host case; see the note before productionising.
"""

import threading
import uuid
from dataclasses import asdict, dataclass

_LOCK = threading.Lock()
_JOBS: dict[str, "PullJob"] = {}
_MAX_JOBS = 50  # keep the most recent handful; prune oldest beyond this


@dataclass
class PullJob:
    id: str
    name: str
    status: str = "pulling"  # pulling | success | error
    detail: str = ""  # latest Ollama status line, e.g. "pulling manifest"
    completed: int = 0  # bytes downloaded so far (current layer)
    total: int = 0  # bytes expected (current layer)
    error: str | None = None
    done: bool = False

    @property
    def percent(self) -> int:
        return int(self.completed * 100 / self.total) if self.total else 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["percent"] = self.percent
        return d


def start_pull(provider, name: str) -> PullJob:
    """Kick off a background pull of `name` on `provider`; returns the tracking job immediately."""
    job = PullJob(id=uuid.uuid4().hex, name=name)
    with _LOCK:
        _JOBS[job.id] = job
        _prune_locked()

    def _run() -> None:
        def on_progress(update: dict) -> None:
            with _LOCK:
                job.detail = update.get("status", job.detail)
                job.completed = int(update.get("completed", job.completed) or 0)
                job.total = int(update.get("total", job.total) or 0)

        try:
            provider.pull_model(name, on_progress=on_progress)
            with _LOCK:
                job.status, job.detail, job.done = "success", "success", True
        except Exception as e:  # noqa: BLE001 — surface any pull failure to the poller
            with _LOCK:
                job.status, job.error, job.done = "error", str(e), True

    threading.Thread(target=_run, name=f"ollama-pull-{name}", daemon=True).start()
    return job


def get_job(job_id: str) -> PullJob | None:
    with _LOCK:
        return _JOBS.get(job_id)


def _prune_locked() -> None:
    """Drop the oldest finished jobs once we exceed the cap (called under _LOCK)."""
    if len(_JOBS) <= _MAX_JOBS:
        return
    finished = [jid for jid, j in _JOBS.items() if j.done]
    for jid in finished[: len(_JOBS) - _MAX_JOBS]:
        _JOBS.pop(jid, None)
