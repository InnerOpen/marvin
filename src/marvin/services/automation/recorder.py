"""Execution recording for the automation engine — turns a run into an audit trail.

The engine calls a recorder around each run and each action. Two implementations:

  * :class:`NullRecorder` — the default; no-ops everything (used by unit tests and any caller that
    doesn't want persistence). Keeps the engine testable without a real DB.
  * :class:`ExecutionRecorder` — writes ``automation_executions`` + ``automation_action_executions``
    rows (production call sites: the reaction listener, the /run route, the scheduled handler).

Snapshots are truncated at a fixed cap so a run can never persist unbounded content, and resolved
secrets are never recorded (the engine only hands over action *outputs*, not credentials). Recording
is best-effort: a recorder failure is swallowed so it can never break an automation run.
"""

import json
from datetime import UTC, datetime

from marvin.services.event_bus_service.correlation import new_correlation_id  # re-export (one generator)

__all__ = ["NullRecorder", "CollectingRecorder", "ExecutionRecorder", "new_correlation_id"]

_SNAPSHOT_CAP = 4096  # bytes; larger outputs are stored as a truncated preview


def _truncate(value) -> dict | None:
    """Bound an action's output before persisting it. Returns a JSON-safe dict (or None)."""
    if value is None:
        return None
    if not isinstance(value, dict):
        value = {"value": value}
    try:
        s = json.dumps(value, default=str)
    except (TypeError, ValueError):
        return {"_unserializable": True}
    if len(s) <= _SNAPSHOT_CAP:
        return value
    # The entry a step made or changed is kept whatever the size: it is how a run is followed on to the worker job it
    # started (services/automation/run_state.py).
    kept = {"entry_id": value["entry_id"]} if isinstance(value.get("entry_id"), str) else {}
    return {"_truncated": True, "bytes": len(s), "preview": s[:1000], **kept}


def _step_label(action: dict, on_failure: bool) -> str | None:
    """A step's label, marked when it is an on_failure step (run because an earlier step failed)."""
    label = _action_label(action)
    return f"on failure: {label or action.get('kind') or 'step'}" if on_failure else label


def _action_label(action: dict) -> str | None:
    """A short human label for a step, by kind."""
    kind = action.get("kind")
    if kind == "operation":
        return action.get("op")
    if kind == "emit_event":
        return action.get("event")
    if kind == "handler":
        return action.get("task")
    if kind == "webhook":
        return action.get("webhook_id") or action.get("url")
    if kind == "entry":
        return action.get("op")
    if kind == "integration":
        return f"{action.get('integration')}.{action.get('action')}"
    return None


class NullRecorder:
    """No-op recorder. `start` returns None; everything else is ignored."""

    def start(self, *args, **kwargs):
        return None

    def action(self, *args, **kwargs) -> None:
        pass

    def finish(self, *args, **kwargs) -> None:
        pass


class CollectingRecorder:
    """In-memory recorder for **dry runs** — captures the resolved plan, persists nothing.

    Each step's ``output`` is the executor's resolved-but-not-executed preview (see the executors'
    ``dry_run`` branch), so ``.plan`` is exactly "what this automation *would* do" per target×action.
    """

    def __init__(self) -> None:
        self.plan: list[dict] = []

    def start(self, *args, **kwargs):
        return "dry"  # non-None so action() records against it

    def action(
        self,
        exec_id,
        *,
        target_index: int,
        target_ref: dict | None,
        action_index: int,
        action: dict,
        status: str,
        output=None,
        error: str | None = None,
        duration_ms: int | None = None,
        on_failure: bool = False,
        handling: dict | None = None,
    ) -> None:
        self.plan.append(
            {
                "target_index": target_index,
                "target": target_ref,
                "action_index": action_index,
                "kind": action.get("kind"),
                "label": _step_label(action, on_failure),
                "on_failure": on_failure,
                "status": status,  # "success" = would run; "failed" = a gate/resolve error; "skipped" = its `when` is false
                "resolved": output,  # the executor's dry-run preview (or None on a gate failure)
                "error": error,
            }
        )

    def finish(self, *args, **kwargs) -> None:
        pass


class ExecutionRecorder:
    """Persists a run and its per-(target, action) steps. Best-effort — never raises to the engine.

    A caller that tells someone the run's id before the run begins (the Run button answers with it, then may run after
    the response) records the run first with ``reserve``; the next ``start`` begins the run in that row. ``execution_id``
    names a row another recorder reserved (the background run has a session of its own)."""

    def __init__(self, session, group_id, execution_id=None) -> None:
        self.session = session
        self.group_id = group_id
        self._reserved = execution_id

    def reserve(self, automation, *, user_id=None):
        """Record a run before it begins and return its id (None when it could not be recorded)."""
        self._reserved = self.start(
            automation, getattr(automation, "trigger_type", None) or "event", targets_matched=1, capped=False, user_id=user_id
        )
        return self._reserved

    def close_unstarted(self, error: str) -> None:
        """End a reserved run that never began (its workflow went away, its target could not be read) as failed, so
        the id that was given out does not read as running for good. Nothing to do once the run has started."""
        exec_id, self._reserved = self._reserved, None
        if exec_id is not None:
            self.session.rollback()  # whatever stopped the run may have left the session unusable
            self.finish(exec_id, status="failed", error=error)

    def _begin_reserved(self, *, targets_matched: int, capped: bool, correlation_id: str | None):
        """Begin the run in the row reserved for it; None when that row is gone (the run is then recorded afresh)."""
        from marvin.db.models.groups.automation_executions import AutomationExecutionModel

        exec_id, self._reserved = self._reserved, None
        row = self.session.get(AutomationExecutionModel, exec_id)
        if row is None:
            return None
        row.targets_matched, row.capped, row.correlation_id = targets_matched, capped, correlation_id
        self.session.commit()
        return row.id

    def start(
        self, automation, trigger_type: str, *, targets_matched: int, capped: bool, user_id=None, correlation_id: str | None = None, retry_of_id=None
    ):
        from marvin.db.models.groups.automation_executions import AutomationExecutionModel

        try:
            if self._reserved is not None:
                reserved = self._begin_reserved(targets_matched=targets_matched, capped=capped, correlation_id=correlation_id)
                if reserved is not None:
                    return reserved
            row = AutomationExecutionModel(
                session=self.session,
                group_id=self.group_id,
                automation_id=getattr(automation, "id", None),
                automation_slug=getattr(automation, "slug", "") or "",
                trigger_type=trigger_type,
                status="running",
                started_at=datetime.now(UTC),
                targets_matched=targets_matched,
                capped=capped,
                definition_snapshot=(getattr(automation, "definition", None) or {}),
                correlation_id=correlation_id,
                triggered_by=user_id,
                retry_of_id=retry_of_id,
            )
            self.session.add(row)
            self.session.commit()
            return row.id
        except Exception:
            self.session.rollback()
            return None

    def action(
        self,
        exec_id,
        *,
        target_index: int,
        target_ref: dict | None,
        action_index: int,
        action: dict,
        status: str,
        output=None,
        error: str | None = None,
        duration_ms: int | None = None,
        on_failure: bool = False,
        handling: dict | None = None,
    ) -> None:
        if exec_id is None:
            return
        from marvin.db.models.groups.automation_executions import AutomationActionExecutionModel

        ref = target_ref or {}
        try:
            row = AutomationActionExecutionModel(
                session=self.session,
                execution_id=exec_id,
                group_id=self.group_id,
                target_index=target_index,
                target_entity_type="entry" if ref.get("id") else None,
                target_entity_id=ref.get("id"),
                action_index=action_index,
                kind=action.get("kind", "?"),
                label=_step_label(action, on_failure),
                status=status,
                error=(error[:2000] if error else None),
                duration_ms=duration_ms,
                output_snapshot=_truncate(output),
                handling=handling,
            )
            self.session.add(row)
            self.session.commit()
        except Exception:
            self.session.rollback()

    def finish(
        self, exec_id, *, status: str, error: str | None = None, targets_run: int = 0, steps_ok: int = 0, steps_failed: int = 0, handled: bool = False
    ) -> None:
        if exec_id is None:
            return
        from marvin.db.models.groups.automation_executions import AutomationExecutionModel

        try:
            row = self.session.get(AutomationExecutionModel, exec_id)
            if not row:
                return
            now = datetime.now(UTC)
            row.status = status
            row.error = error[:2000] if error else None
            row.finished_at = now
            row.targets_run = targets_run
            row.steps_total = steps_ok + steps_failed
            row.steps_ok = steps_ok
            row.steps_failed = steps_failed
            row.handled = handled
            if row.started_at:
                started = row.started_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=UTC)
                row.duration_ms = int((now - started).total_seconds() * 1000)
            self.session.commit()
        except Exception:
            self.session.rollback()
