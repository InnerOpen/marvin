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
    return {"_truncated": True, "bytes": len(s), "preview": s[:1000]}


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
    ) -> None:
        self.plan.append(
            {
                "target_index": target_index,
                "target": target_ref,
                "action_index": action_index,
                "kind": action.get("kind"),
                "label": _action_label(action),
                "status": status,  # "success" = would run; "failed" = a gate/resolve error
                "resolved": output,  # the executor's dry-run preview (or None on a gate failure)
                "error": error,
            }
        )

    def finish(self, *args, **kwargs) -> None:
        pass


class ExecutionRecorder:
    """Persists a run and its per-(target, action) steps. Best-effort — never raises to the engine."""

    def __init__(self, session, group_id) -> None:
        self.session = session
        self.group_id = group_id

    def start(self, automation, trigger_type: str, *, targets_matched: int, capped: bool, user_id=None, correlation_id: str | None = None):
        from marvin.db.models.groups.automation_executions import AutomationExecutionModel

        try:
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
                label=_action_label(action),
                status=status,
                error=(error[:2000] if error else None),
                duration_ms=duration_ms,
                output_snapshot=_truncate(output),
            )
            self.session.add(row)
            self.session.commit()
        except Exception:
            self.session.rollback()

    def finish(self, exec_id, *, status: str, error: str | None = None, targets_run: int = 0, steps_ok: int = 0, steps_failed: int = 0) -> None:
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
            if row.started_at:
                started = row.started_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=UTC)
                row.duration_ms = int((now - started).total_seconds() * 1000)
            self.session.commit()
        except Exception:
            self.session.rollback()
