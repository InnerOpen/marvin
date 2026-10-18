"""Per-step idempotency keys: a webhook or integration step that already made this call is not made again.

A step may carry a templated ``idempotency_key`` (``handoff-${entry.id}-${entry.updated_at}``). The call it makes is
identified by the workflow, where it calls (the webhook, or the integration action) and the key's resolved text.
Within the window (``idempotency_window_hours``, 24 by default) a second call with the same identity is not made: the
step reuses the output the first one recorded. Two duplicates racing deliver once — the first takes a claim before it
calls (``db/models/groups/workflow_step_idempotency.py``); the other finds it and calls nothing.

A call that fails gives its claim back, so a retry (``engine.run_retry`` resumes at the failed step) and the next event
still make it; a claim never completed (a crashed worker) runs out after ``CLAIM_LEASE_SECONDS``. A dry run claims
nothing: it says what a real run would do (``would``: ``call`` or ``skip (duplicate)``).
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from .actions.base import AutomationActionError
from .matcher import interpolate

DEFAULT_WINDOW_HOURS = 24
MAX_WINDOW_HOURS = 720
CLAIM_LEASE_SECONDS = 300  # longest a call holds its claim before a duplicate may take it over
MAX_OUTPUT_CHARS = 100_000  # a bigger output is not kept; a duplicate then reuses nothing but the fact of the call
SKIP = "skip (duplicate)"
CALL = "call"


def _now() -> datetime:
    return datetime.now(UTC)


def _model():
    from marvin.db.models.groups.workflow_step_idempotency import WorkflowStepIdempotencyModel

    return WorkflowStepIdempotencyModel


def window_hours(action: dict) -> int:
    """The step's window, clamped to 1..720 hours; 24 when it names none (or something that isn't a whole number)."""
    value = action.get("idempotency_window_hours")
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 1:
        return DEFAULT_WINDOW_HOURS
    return min(int(value), MAX_WINDOW_HOURS)


class Gate:
    """One step's idempotency check: ``duplicate`` says whether to skip the call, ``output`` is what a skip reuses."""

    def __init__(self, session, group_id, *, key: str, key_hash: str, workflow_slug, destination: str, hours: int, dry_run: bool) -> None:
        self.session, self.group_id = session, group_id
        self.key, self.hours, self.dry_run = key, hours, dry_run
        self.row_id = None
        self.duplicate = False
        self.in_progress = False
        self.recorded_at: datetime | None = None
        self.recorded: dict | None = None
        self._hash, self._slug, self._destination = key_hash, workflow_slug, destination
        self._check()

    # ── Deciding ──────────────────────────────────────────────────────────
    def _row(self):
        Model = _model()
        return self.session.query(Model).filter(Model.group_id == self.group_id, Model.key_hash == self._hash).first()

    def _seen(self, row) -> None:
        self.duplicate = True
        self.in_progress = row.status != "done"
        self.recorded = row.output if isinstance(row.output, dict) else None
        self.recorded_at = row.update_at or row.created_at

    def _check(self) -> None:
        """A dry run only looks; a real run takes the claim, or finds that someone has the call (or made it)."""
        now = _now()
        row = self._row()
        if row is not None and row.expires_at > now:
            self._seen(row)
            return
        if self.dry_run:
            return
        Model = _model()
        lease = now + timedelta(seconds=CLAIM_LEASE_SECONDS)
        if row is not None:  # a window that ran out, or a claim left behind: take it over — one taker wins
            took = self.session.execute(
                update(Model).where(Model.id == row.id, Model.expires_at == row.expires_at).values(status="claimed", output=None, expires_at=lease)
            ).rowcount
            self.session.commit()
            if took:
                self.row_id = row.id
                return
        else:
            fresh = Model(
                session=self.session,
                group_id=self.group_id,
                key_hash=self._hash,
                workflow_slug=self._slug,
                destination=self._destination,
                status="claimed",
                expires_at=lease,
            )
            try:
                with self.session.begin_nested():
                    self.session.add(fresh)
                    self.session.flush()
            except IntegrityError:
                fresh = None
            if fresh is not None:
                self.session.commit()  # held before the call is made: a crash after it never makes it twice
                self.row_id = fresh.id
                return
        self.session.expire_all()
        current = self._row()  # lost the race: the winner's claim (or its finished call) is what this one meets
        if current is not None:
            self._seen(current)
        else:  # it was released between the two looks: nothing stands in the way
            self.duplicate = False

    # ── What the step reports ─────────────────────────────────────────────
    def skipped(self, preview: dict | None = None) -> dict:
        """The output of a step that does not call: what the first call returned, marked as a duplicate."""
        mark = {"key": self.key, "duplicate": True, "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None}
        if self.in_progress:
            mark["in_progress"] = True
        out = {**(preview or {}), **(self.recorded or {}), "idempotency": mark}  # the recorded answer wins: later steps read it
        if preview is not None:  # a dry run: the same shape its plan shows for any step
            out |= {"dry_run": True, "idempotency_key": self.key, "would": SKIP}
        return out

    def preview(self) -> dict:
        """What a dry run adds to a step that would call."""
        return {"idempotency_key": self.key, "would": CALL}

    # ── After the call ────────────────────────────────────────────────────
    def complete(self, output) -> None:
        """The call succeeded: keep its output for the window."""
        if self.row_id is None:
            return
        kept = output if isinstance(output, dict) else None
        try:
            if kept is not None and len(json.dumps(kept, default=str)) > MAX_OUTPUT_CHARS:
                kept = None
            Model = _model()
            self.session.execute(
                update(Model)
                .where(Model.id == self.row_id)
                .values(
                    status="done",
                    output=json.loads(json.dumps(kept, default=str)) if kept is not None else None,
                    expires_at=_now() + timedelta(hours=self.hours),
                )
            )
            self.session.commit()
        except Exception:  # noqa: BLE001 — a bookkeeping fault must not fail a call that went through
            self.session.rollback()

    def release(self) -> None:
        """The call failed: give the claim back, so a retry (or the next event) makes it."""
        if self.row_id is None:
            return
        try:
            Model = _model()
            self.session.query(Model).filter(Model.id == self.row_id, Model.status == "claimed").delete(synchronize_session=False)
            self.session.commit()
        except Exception:  # noqa: BLE001 — the claim runs out on its own
            self.session.rollback()


def open_gate(session, group_id, action: dict, context: dict, *, destination: str, dry_run: bool) -> Gate | None:
    """The step's idempotency check, or None when it has no ``idempotency_key``."""
    template = action.get("idempotency_key")
    if template is None or (isinstance(template, str) and not template.strip()):
        return None
    key = interpolate(template, context)
    key = "" if key is None else str(key).strip()
    if not key:
        raise AutomationActionError(
            "idempotency_key is empty: what it reads has no value here, so every call would look like the same one. "
            "Name something that tells this call apart, e.g. ${entry.id}."
        )
    step = context.get("_step") or {}
    workflow = str(step.get("workflow") or step.get("workflow_slug") or "workflow")
    digest = hashlib.sha256(json.dumps([workflow, destination, key], ensure_ascii=False).encode()).hexdigest()
    return Gate(
        session,
        group_id,
        key=key,
        key_hash=digest,
        workflow_slug=step.get("workflow_slug"),
        destination=destination[:255],
        hours=window_hours(action),
        dry_run=dry_run,
    )


def purge_expired(session) -> int:
    """Delete the keys whose window has ended (a duplicate would no longer find them anyway). Platform-wide."""
    Model = _model()
    return session.query(Model).filter(Model.expires_at < _now()).delete(synchronize_session=False)
