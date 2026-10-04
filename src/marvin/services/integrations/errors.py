"""Integration-owned error handling — apply a provider's declared error policy to a failed call.

A provider names its failures (``IntegrationError.code``: "auth", "rate_limited", "invalid", …) and
declares how each code is handled (SDK 0.5.0 ``error_policy``: a ``Handle`` of review / notify /
succeed / retry, with ``then`` once retries run out). This module is the core side:

  * :func:`policy_for` resolves the Handle for a failure (as a JSON-safe dict, so it can be stored
    on a retry row and shown in the run history).
  * :func:`handle_failure` applies it to a failed **workflow** step — send the entry to review, open
    or bump the connection's alert, schedule a retry (``integration_retries``), or let the pipeline
    carry on as if the step succeeded. Two modes: ``MODE_POLICY`` (the provider's policy runs) and
    ``MODE_CONNECTION`` (only the connection-level ``notify`` — when the workflow has its own
    ``on_failure`` steps, opts out with ``integration_errors: "fail"``, or the failing step is itself
    an on_failure step).
  * :func:`notify` / :func:`resolve_alerts` keep ``integration_alerts`` — one open alert per
    connection + code, counted and sampled, announced (``integration_attention_needed``) when it opens
    and once per reminder window, and resolved (``integration_attention_resolved``) by a passing
    check, a successful action, or an admin. The resolved notice goes back through the channels that
    delivered the alert (``channels`` on the row), whatever the routing says by then.
  * :func:`connection_failed` / :func:`connection_succeeded` are the connection-scope hooks for
    callers outside workflows (event subscriptions, capabilities, the scheduled integration task):
    notify only — no review, no retry.

Degrades to today's behaviour: with SDK 0.4.0 (no ``resolve_policy``) or a provider that declares
no policy, :func:`policy_for` is None and a failed step fails as it always has.

Loop guard: delivering an alert never touches alert state. Alert events are dispatched with
``_delivering_alert`` set, the subscription listener skips its connection hooks for alert events,
and neither alert event is a workflow trigger.
"""

import dataclasses
import inspect
import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from marvin.core.root_logger import get_logger
from marvin.db.models.groups.integration_errors import RETRY_LIVE, IntegrationAlertModel, IntegrationRetryModel

try:  # SDK 0.5.0+. Older SDKs declare no policies, so every failure fails as it always has.
    from marvin_integration_sdk import policy_info as _policy_info
    from marvin_integration_sdk import resolve_policy as _resolve_policy
except ImportError:  # pragma: no cover — depends on the installed SDK
    _policy_info = _resolve_policy = None

logger = get_logger(__name__)

MODE_POLICY = "policy"
MODE_CONNECTION = "connection"

NEEDED = "integration_attention_needed"
RESOLVED = "integration_attention_resolved"
ALERT_EVENTS = (NEEDED, RESOLVED)

ERROR_METADATA_KEY = "integration_error"
"""Entry metadata the review path writes: ``integration_error.<slug> = {code, message, …}``; cleared when the step next succeeds."""

MAX_SAMPLES = 5  # failures an alert keeps for display
MAX_SNAPSHOT_BYTES = 256 * 1024  # a run too big to snapshot is not retried (it still fails, and is reviewed/notified)
RETRY_LEASE = timedelta(minutes=5)  # how long the sweep owns a claimed retry before another tick may reclaim it
PRUNE_AFTER = timedelta(days=30)

_delivering_alert: ContextVar[bool] = ContextVar("integration_alert_delivery", default=False)


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite hands datetimes back naive; every stored one is UTC."""
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


# ── policy ──────────────────────────────────────────────────────────────────────


def error_code(exc: BaseException) -> str:
    """The provider's stable code for a failure, or "unknown" (SDK 0.5.0's default too)."""
    code = getattr(exc, "code", None)
    return code if isinstance(code, str) and code else "unknown"


def error_partial(exc: BaseException) -> dict | None:
    partial = getattr(exc, "partial", None)
    return partial if isinstance(partial, dict) and partial else None


def error_retry_after(exc: BaseException) -> float | None:
    value = getattr(exc, "retry_after", None)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) and value > 0 else None


OVERRIDABLE = ("review", "notify")
"""The Handle flags an admin may adjust per connection; retries, backoff and `then` stay the provider's."""


def policy_for(provider, action_key: str, code: str, overrides: dict | None = None) -> dict | None:
    """The provider's Handle for ``code`` raised by ``action_key``, as ``Handle.to_dict()`` — or None
    (no policy declared, or an SDK without policies): the failure is handled as it always was.

    ``overrides`` is the connection's ``error_overrides``: ``{code: {review?, notify?}}``, applied to
    the declared Handle. A ``"*"`` override applies to codes the provider doesn't name itself."""
    if _resolve_policy is None:
        return None
    try:
        handle = _resolve_policy(provider, action_key, code)
        if handle is None:
            return None
        override = _override_for(provider, action_key, code, overrides)
        if override:
            handle = dataclasses.replace(handle, **override)
    except Exception as e:  # noqa: BLE001 — a malformed policy must not break the failure path
        logger.warning("error policy lookup failed for %s.%s (%s): %s", getattr(provider, "slug", "?"), action_key, code, e)
        return None
    return handle.to_dict()


def clean_overrides(overrides) -> dict:
    """Keep only well-formed adjustments: ``{code: {review?: bool, notify?: bool}}``, empty ones dropped."""
    if not isinstance(overrides, dict):
        return {}
    cleaned = {}
    for code, flags in overrides.items():
        if isinstance(code, str) and code and isinstance(flags, dict):
            kept = {k: v for k, v in flags.items() if k in OVERRIDABLE and isinstance(v, bool)}
            if kept:
                cleaned[code] = kept
    return cleaned


def declared_codes(provider, action_key: str | None = None) -> set[str]:
    """The codes the provider's policy names — for the provider, plus one action's (or every action's)."""
    info = policies(provider) or {}
    actions = info.get("actions") or {}
    codes = set(info.get("provider") or {})
    for key, policy in actions.items():
        if action_key is None or key == action_key:
            codes |= set(policy or {})
    return codes


def _override_for(provider, action_key: str, code: str, overrides: dict | None) -> dict:
    overrides = clean_overrides(overrides)
    if not overrides:
        return {}
    if code in overrides:
        return overrides[code]
    return overrides.get("*", {}) if code not in declared_codes(provider, action_key) else {}


def policies(provider) -> dict | None:
    """The provider's declared policies for the catalog's "How errors are handled" table (None on an old SDK)."""
    if _policy_info is None:
        return None
    try:
        return _policy_info(provider)
    except Exception:  # noqa: BLE001 — the catalog shows the provider without its table
        return None


@lru_cache(maxsize=8)
def _context_fields(context_cls) -> frozenset[str]:
    if dataclasses.is_dataclass(context_cls):
        return frozenset(f.name for f in dataclasses.fields(context_cls))
    try:
        return frozenset(inspect.signature(context_cls).parameters)
    except (TypeError, ValueError):
        return frozenset()


def build_context(context_cls, *, resume: dict | None = None, idempotency_seed: str | None = None, **base):
    """An IntegrationContext, with ``resume`` / ``idempotency_seed`` only when the installed SDK has
    them (0.5.0+) — so a 0.4.0 provider keeps getting exactly the context it knows."""
    supported = _context_fields(context_cls)
    extra = {k: v for k, v in (("resume", resume), ("idempotency_seed", idempotency_seed)) if k in supported}
    return context_cls(**base, **extra)


def _retry_attempts(retry: dict) -> int:
    attempts = retry.get("max_attempts")
    return int(attempts) if isinstance(attempts, int) and attempts > 0 else max(len(retry.get("backoff") or []), 1)


def _retry_delay(retry: dict, attempt: int) -> float:
    """Seconds before retry number ``attempt`` (1-based); past the end of the backoff the last delay repeats."""
    backoff = retry.get("backoff") or []
    return float(backoff[min(attempt, len(backoff)) - 1]) if backoff else 0.0


# ── workflow failures ───────────────────────────────────────────────────────────


@dataclass
class Handling:
    """What the policy did with one failed step: the run history's ``handling`` and the run message's words."""

    summary: str
    record: dict
    handled: bool
    """The provider's policy took the failure in hand (a run whose every failure is handled is "handled")."""
    succeed: bool = False
    """The step counts as a success and the pipeline carries on."""


def _entry_id(context: dict) -> str | None:
    entry = context.get("entry") or {}
    return entry.get("id") or (context.get("event") or {}).get("entry_id")


def _json_safe(value) -> Any:
    return json.loads(json.dumps(value, default=str))


def handle_failure(
    session,
    group_id,
    error,
    *,
    automation,
    context: dict,
    step_index: int,
    mode: str,
    run: dict,
    execution_id=None,
    user_id=None,
) -> Handling | None:
    """Apply the provider's policy to a failed workflow step (``error`` is an IntegrationStepError).

    Returns None when nothing applies (the step fails exactly as before). ``run`` describes the run
    for a retry snapshot: ``{target_ref, gated, trigger_kind}``. Best-effort — a fault in here is
    logged and the step simply fails."""
    try:
        return _handle_failure(
            session,
            group_id,
            error,
            automation=automation,
            context=context,
            step_index=step_index,
            mode=mode,
            run=run,
            execution_id=execution_id,
            user_id=user_id,
        )
    except Exception as e:  # noqa: BLE001 — error handling must never turn a failed step into a crashed run
        session.rollback()
        logger.warning("error policy for %s.%s could not be applied: %s", error.integration_slug, error.action_key, e, exc_info=True)
        return None


def _handle_failure(session, group_id, error, *, automation, context, step_index, mode, run, execution_id, user_id) -> Handling | None:
    policy = error.policy
    retry_ctx = context.get("_retry") or {}
    row = session.get(IntegrationRetryModel, retry_ctx["id"]) if retry_ctx.get("step_index") == step_index and retry_ctx.get("id") else None
    entry_id = _entry_id(context)
    alert_args = {"entry_id": entry_id, "automation_slug": getattr(automation, "slug", None), "source": "workflow"}

    if mode == MODE_CONNECTION or policy is None:
        if row is not None:  # a retry whose policy went away (provider downgraded) or was opted out of: stop the chain
            _refresh(row, error, context, execution_id)
            _finish(row, "failed", error=error.detail)
            session.commit()
        elif error.partial and entry_id:  # no policy to apply, but the progress is still worth resuming from
            _start_chain(
                session,
                group_id,
                error,
                None,
                row=None,
                automation=automation,
                context=context,
                step_index=step_index,
                run=run,
                execution_id=execution_id,
            )
            session.commit()
        if not (policy and policy.get("notify")):
            return None
        _notify_for(session, group_id, error, **alert_args)
        summary = f"{error.provider_name}: admins notified"
        return Handling(summary=summary, record=_record(error, policy, ["notify"], summary, mode), handled=False)

    if row is None:
        # A new failure: the policy's immediate effects, and a retry chain if it asks (taking over a
        # chain that is already live for this step, budget and all).
        applied, row = _apply(
            session,
            group_id,
            error,
            policy,
            row=None,
            automation=automation,
            context=context,
            step_index=step_index,
            run=run,
            execution_id=execution_id,
            user_id=user_id,
        )
    else:
        applied, row = _continue_chain(
            session,
            group_id,
            error,
            policy,
            row=row,
            automation=automation,
            context=context,
            step_index=step_index,
            run=run,
            execution_id=execution_id,
            user_id=user_id,
        )
    session.commit()

    if not applied:  # Handle() — "fail as usual", e.g. to override a broader "*" entry
        return None
    summary = _summary(error.provider_name, applied, row)
    return Handling(summary=summary, record=_record(error, policy, applied, summary, mode, row), handled=bool(applied), succeed="succeed" in applied)


def _effects(session, group_id, error, handle: dict, *, automation, context, user_id) -> list[str]:
    """A Handle's immediate effects: notify, review (a live entry is flagged and alerted instead), succeed."""
    applied: list[str] = []
    entry_id = _entry_id(context)
    alert_args = {"entry_id": entry_id, "automation_slug": getattr(automation, "slug", None), "source": "workflow"}
    if handle.get("notify"):
        _notify_for(session, group_id, error, **alert_args)
        applied.append("notify")
    if handle.get("review"):
        reviewed = _review(session, group_id, error, entry_id, automation=automation, context=context, user_id=user_id) if entry_id else None
        if reviewed:
            applied.append(reviewed)
        # Nothing to review, or a live entry that stays live — make sure a person hears about it.
        if reviewed != "review" and "notify" not in applied:
            _notify_for(session, group_id, error, **alert_args)
            applied.append("notify")
    if handle.get("succeed"):
        applied.append("succeed")
    return applied


_warned_succeed_retry: set[tuple[str, str]] = set()


def _retry_of(handle: dict, error) -> dict | None:
    """The Handle's retry — ignored alongside `succeed`: the pipeline already carried on past the step,
    so a retry would resume it and run the later steps a second time."""
    retry = handle.get("retry")
    if retry and handle.get("succeed"):
        key = (error.provider, error.code)
        if key not in _warned_succeed_retry:
            _warned_succeed_retry.add(key)
            logger.warning("%s's error policy for %r both succeeds and retries; the retry is ignored", error.provider, error.code)
        return None
    return retry


def _apply(
    session, group_id, error, handle: dict, *, row, automation, context, step_index, run, execution_id, user_id
) -> tuple[list[str], IntegrationRetryModel | None]:
    """A Handle's immediate effects plus starting its retry chain (or keeping the partial progress)."""
    applied = _effects(session, group_id, error, handle, automation=automation, context=context, user_id=user_id)
    retry = _retry_of(handle, error)
    if retry:
        row = _start_chain(
            session,
            group_id,
            error,
            handle,
            row=row,
            automation=automation,
            context=context,
            step_index=step_index,
            run=run,
            execution_id=execution_id,
        )
        if row is not None:
            applied.append(_chain_step(row))
    elif row is not None:
        if row.status in RETRY_LIVE:  # a chain whose latest failure isn't retried: it ends here
            _refresh(row, error, context, execution_id)
            _finish(row, "failed", error=error.detail)
    elif error.partial and _entry_id(context):
        # No retry, but progress worth keeping: the next run of this action for this entry resumes it.
        row = _start_chain(
            session,
            group_id,
            error,
            None,
            row=None,
            automation=automation,
            context=context,
            step_index=step_index,
            run=run,
            execution_id=execution_id,
        )
    return applied, row


FALLBACK_THEN = {"review": True, "notify": True, "succeed": False, "retry": None, "then": None, "summary": "send to review, notify admins"}
"""What ends a chain that mixed codes or ran out its time when the current code declares no `then`."""

MAX_CHAIN_AGE = timedelta(hours=24)
MIN_RETRY_DELAY = 60.0  # seconds between attempts, whatever the backoff says (the sweep ticks every minute)


def _chain_step(row) -> str:
    return "parked" if row.status == "parked" else "retry"


def _continue_chain(session, group_id, error, policy, *, row, automation, context, step_index, run, execution_id, user_id):
    """A retry failed again. One budget for the whole chain: the retries already made count whatever
    code they failed with, the limit is the largest `attempts` among the codes it has hit, and no chain
    runs past 24 hours. A code new to the chain applies its immediate effects; the same code again only
    counts on the alert. When the chain ends, the current code's `then` applies — or, for a chain that
    mixed codes or ran out of time, review + notify."""
    same = row.code == error.code
    handle = (row.handle or policy) if same else policy
    if same:
        applied = []
        if handle.get("notify"):
            _notify_for(session, group_id, error, entry_id=_entry_id(context), automation_slug=getattr(automation, "slug", None), source="workflow")
            applied.append("notify")
    else:
        applied = _effects(session, group_id, error, handle, automation=automation, context=context, user_id=user_id)
    _refresh(row, error, context, execution_id)
    retry = _retry_of(handle, error)
    if not retry:  # this code isn't retried: the chain ends here
        if row.status in RETRY_LIVE:
            _finish(row, "failed", error=error.detail)
        return applied, row

    row.codes = sorted({*(row.codes or [row.code]), error.code})
    row.code, row.handle = error.code, handle
    row.max_attempts = max(row.max_attempts or 0, _retry_attempts(retry))
    timed_out = _now() - (_aware(row.created_at) or _now()) >= MAX_CHAIN_AGE
    if row.attempt < row.max_attempts and not timed_out:
        _arm(session, row, retry, error)
        applied.append(_chain_step(row))
        return applied, row

    _finish(row, "exhausted", error=error.detail)
    applied.append("exhausted")
    then = handle.get("then") or (FALLBACK_THEN if timed_out or len(row.codes) > 1 else None)
    if then:
        then_applied, row = _apply(
            session,
            group_id,
            error,
            then,
            row=row,
            automation=automation,
            context=context,
            step_index=step_index,
            run=run,
            execution_id=execution_id,
            user_id=user_id,
        )
        applied += [a for a in then_applied if a not in applied]
    return applied, row


def _record(error, policy, applied: list[str], summary: str, mode: str, row=None) -> dict:
    record = {
        "code": error.code,
        "integration": error.integration_slug,
        "provider": error.provider,
        "provider_name": error.provider_name,
        "mode": mode,
        "policy": policy,
        "applied": applied,
        "summary": summary,
    }
    if row is not None and row.handle:
        record["retry"] = {
            "id": str(row.id),
            "status": row.status,
            "attempt": row.attempt,
            "max_attempts": row.max_attempts,
            "next_attempt_at": _aware(row.next_attempt_at).isoformat() if row.next_attempt_at else None,
        }
    return record


def _summary(provider_name: str, applied: list[str], row) -> str:
    words = {
        "review": "sent to review",
        "flagged": "flagged on the entry (left published)",
        "notify": "admins notified",
        "succeed": "ignored",
        "exhausted": "retries used up",
    }
    parts = []
    for item in applied:
        if item == "retry":
            parts.append(f"retry {row.attempt + 1} of {row.max_attempts} scheduled")
        elif item == "parked":
            parts.append("will retry when the connection recovers")
        else:
            parts.append(words.get(item, item))
    return f"handled by {provider_name}: {', '.join(parts)}" if parts else f"{provider_name}: fails as usual"


LIVE_STATUSES = ("published",)
"""Statuses where moving the entry to Needs review would take live content off the site."""


def review_reason(error) -> str:
    """The review reason an integration failure gives: "Square · invalid — price must be positive"."""
    message = (error.detail or "").strip()[:500]
    return f"{error.provider_name} · {error.code}" + (f" — {message}" if message else "")


def _review(session, group_id, error, entry_id, *, automation, context, user_id) -> str | None:
    """Say on the entry why it needs a look — ``integration_error.<slug>`` and the review reason — and
    move it to Needs review. A live (published) entry keeps its status: a failing shop or newsletter
    must never take content off the site; it is flagged instead ("flagged"), and the caller alerts
    admins so a person still hears. Returns "review", "flagged", or None when it couldn't be written."""
    from marvin.db.models.platform.entries import Entries
    from marvin.services.automation.actions.entry import REVIEW_REASONS_KEY, request_review
    from marvin.services.entries import EntryService

    try:
        entry = session.get(Entries, entry_id)
        if entry is None or entry.group_id != group_id:
            return None
        errors = dict((entry.metadata_json or {}).get(ERROR_METADATA_KEY) or {})
        errors[error.integration_slug] = {
            "provider": error.provider,
            "provider_name": error.provider_name,
            "code": error.code,
            "message": (error.detail or "").strip()[:500],
            "action": error.action_key,
            "workflow": getattr(automation, "slug", None),
            "at": _now().isoformat(timespec="seconds"),
        }
        reason, depth = review_reason(error), int(context.get("depth", 0)) + 1
        if entry.status not in LIVE_STATUSES:
            request_review(session, group_id, entry_id, reason=reason, metadata={ERROR_METADATA_KEY: errors}, user_id=user_id, depth=depth)
            return "review"
        metadata = dict(entry.metadata_json or {})
        reasons = [r for r in (metadata.get(REVIEW_REASONS_KEY) or []) if isinstance(r, str)]
        metadata[REVIEW_REASONS_KEY] = reasons if reason in reasons else [*reasons, reason]
        metadata[ERROR_METADATA_KEY] = errors
        EntryService(session, group_id, actor_id=user_id, integration_id="automation").update(
            entry_id, {"metadata_json": metadata}, reaction_depth=depth
        )
        return "flagged"
    except Exception as e:  # noqa: BLE001 — a review that can't be written leaves the step failed, not the run crashed
        session.rollback()
        logger.warning("could not send entry %s to review for %s: %s", entry_id, error.integration_slug, e)
        return None


def _live_key(automation_id, entry_id, step_index: int) -> str:
    return f"{automation_id}:{entry_id or '-'}:{step_index}"


def _snapshot(context: dict, run: dict) -> dict | None:
    """What a retry needs to resume the run: the triggering event, the entry as the run saw it, and the
    earlier steps' outputs. A retry re-reads the entry while it exists and falls back to these facts
    once it is gone (closing a listing after its entry was deleted). None when it is too big to keep."""
    snap = _json_safe(
        {
            "event": context.get("event") or {},
            "entry": context.get("entry"),
            "steps": context.get("steps") or {},
            "previous": context.get("previous") or {},
            "target_ref": run.get("target_ref"),
            "gated": bool(run.get("gated", True)),
            "trigger_kind": run.get("trigger_kind"),
        }
    )
    return snap if len(json.dumps(snap)) <= MAX_SNAPSHOT_BYTES else None


def _start_chain(
    session, group_id, error, handle: dict | None, *, row, automation, context, step_index, run, execution_id
) -> IntegrationRetryModel | None:
    """Create (or take over) the live retry row for this automation + entry + step and arm it.

    With no ``handle`` the row only keeps the failure's partial progress (status ``failed``). A fresh
    run failing the same way while a retry is already pending keeps that retry's schedule — every
    re-trigger mustn't reset the backoff — but takes the newer snapshot."""
    snapshot = _snapshot(context, run)
    if snapshot is None:
        logger.warning("run of '%s' is too large to snapshot; %s.%s will not be retried", automation.slug, error.integration_slug, error.action_key)
        return None
    entry_id = _entry_id(context)
    key = _live_key(automation.id, entry_id, step_index)
    if row is None:
        row = session.query(IntegrationRetryModel).filter_by(group_id=group_id, live_key=key).first()
    if row is not None and row.status in RETRY_LIVE and handle is not None:
        # A chain is already live for this step: it keeps its schedule and budget (every re-trigger
        # mustn't reset the backoff, and alternating codes mustn't make a chain endless).
        _refresh(row, error, context, execution_id, snapshot=snapshot)
        if row.code != error.code:
            row.codes = sorted({*(row.codes or [row.code]), error.code})
            row.code, row.handle = error.code, handle
            row.max_attempts = max(row.max_attempts or 0, _retry_attempts(handle["retry"]))
        return row
    if row is None:
        row = IntegrationRetryModel(
            session=session,
            group_id=group_id,
            automation_id=automation.id,
            entry_id=entry_id,
            step_index=step_index,
            origin_execution_id=execution_id,
            idempotency_seed=error.seed or uuid4().hex,
        )
        session.add(row)
    row.integration_id = error.integration_id
    row.integration_slug = error.integration_slug
    row.provider = error.provider
    row.action = error.action_key
    row.code = error.code
    row.codes = [error.code]
    row.handle = handle
    row.attempt = 0
    row.finished_at = None
    _refresh(row, error, context, execution_id, snapshot=snapshot)
    if handle is None:
        row.max_attempts = 0
        _finish(row, "failed", error=error.detail)
        return row
    row.max_attempts = _retry_attempts(_retry_of(handle, error) or handle["retry"])
    row.live_key = key
    _arm(session, row, handle["retry"], error)
    return row


def _refresh(row, error, context, execution_id, *, snapshot: dict | None = None) -> None:
    row.last_error = (error.detail or "")[:2000]
    row.last_execution_id = execution_id or row.last_execution_id
    if error.partial:
        row.partial = error.partial
    if snapshot is not None:
        row.snapshot = snapshot


def _arm(session, row, retry: dict, error) -> None:
    """Schedule the row's next attempt — or park it until the connection recovers. Parking needs an
    open alert to resolve it; without one the row is simply scheduled (a recovery nobody would see)."""
    attempt = row.attempt + 1
    if retry.get("on_recovery") and _has_open_alert(session, row.group_id, row.integration_id):
        row.status, row.next_attempt_at = "parked", None
    else:
        delay = max(_retry_delay(retry, attempt), error_retry_after(error) or 0, MIN_RETRY_DELAY)
        row.status, row.next_attempt_at = "pending", _now() + timedelta(seconds=delay)
    row.lease_until = None


def _finish(row, status: str, *, error: str | None = None) -> None:
    row.status = status
    row.live_key = None
    row.lease_until = None
    row.next_attempt_at = None
    row.finished_at = _now()
    if error:
        row.last_error = error[:2000]


def release_retry(session, row) -> None:
    """Hand a claimed retry back untouched (its workflow is disabled): pending again, the claim's attempt undone."""
    row.status, row.lease_until = "pending", None
    row.attempt = max((row.attempt or 1) - 1, 0)
    session.commit()


def resume_state(session, group_id, integration_id, action_key: str, context: dict) -> tuple[dict | None, str]:
    """``(ctx.resume, ctx.idempotency_seed)`` for one call. A retry gets its chain's partial and seed
    (the engine puts them in ``context["_resume"]``); a fresh run of an action that left partial
    progress for this entry gets that progress and a new seed; anything else, (None, a new seed)."""
    resume = context.get("_resume")
    if resume and resume.get("integration_id") == str(integration_id) and resume.get("action") == action_key:
        return resume.get("partial"), resume.get("seed") or uuid4().hex
    entry_id = _entry_id(context)
    if not entry_id:
        return None, uuid4().hex
    try:
        row = (
            session.query(IntegrationRetryModel)
            .filter(
                IntegrationRetryModel.group_id == group_id,
                IntegrationRetryModel.entry_id == entry_id,
                IntegrationRetryModel.integration_id == integration_id,
                IntegrationRetryModel.action == action_key,
                IntegrationRetryModel.partial.isnot(None),
                IntegrationRetryModel.status.notin_(("succeeded", "superseded")),
            )
            .order_by(IntegrationRetryModel.update_at.desc())
            .first()
        )
    except Exception:  # noqa: BLE001 — a lookup fault means no resume, not a failed call
        session.rollback()
        return None, uuid4().hex
    return (row.partial if row is not None else None), uuid4().hex


def action_succeeded(session, group_id, integration_id, action_key: str, context: dict) -> None:
    """A workflow's integration call succeeded: its leftover partial progress for this entry is spent,
    and the connection is evidently working (resolves its alerts)."""
    entry_id = _entry_id(context)
    try:
        if entry_id:
            session.query(IntegrationRetryModel).filter(
                IntegrationRetryModel.group_id == group_id,
                IntegrationRetryModel.entry_id == entry_id,
                IntegrationRetryModel.integration_id == integration_id,
                IntegrationRetryModel.action == action_key,
                IntegrationRetryModel.partial.isnot(None),
            ).update({"partial": None}, synchronize_session=False)
            session.commit()
    except Exception as e:  # noqa: BLE001
        session.rollback()
        logger.warning("could not clear partial progress for %s: %s", action_key, e)
    connection_succeeded(group_id, integration_id, session=session)


def step_succeeded(session, group_id, *, automation, context: dict, step_index: int, integration_slug: str | None) -> None:
    """An integration step passed: a retry of it is done (the one running now succeeded; any other live
    one for this automation + entry + step is superseded) and the entry's error note for it goes."""
    entry_id = _entry_id(context)
    retry_id = (context.get("_retry") or {}).get("id")
    try:
        query = session.query(IntegrationRetryModel).filter(
            IntegrationRetryModel.group_id == group_id,
            IntegrationRetryModel.automation_id == automation.id,
            IntegrationRetryModel.step_index == step_index,
            IntegrationRetryModel.status.in_(RETRY_LIVE),
        )
        query = query.filter(IntegrationRetryModel.entry_id == entry_id) if entry_id else query.filter(IntegrationRetryModel.entry_id.is_(None))
        rows = query.all()
        for row in rows:
            _finish(row, "succeeded" if str(row.id) == str(retry_id) else "superseded")
        if entry_id and integration_slug:
            _clear_entry_error(session, group_id, entry_id, integration_slug)
        session.commit()
    except Exception as e:  # noqa: BLE001
        session.rollback()
        logger.warning("could not settle retries after '%s' step %s passed: %s", automation.slug, step_index, e)


def _clear_entry_error(session, group_id, entry_id, slug: str) -> None:
    """Drop ``integration_error.<slug>`` once the step works again. A quiet metadata write (no
    entry_updated): it is the core's own bookkeeping, and an event here could re-trigger the workflow."""
    from marvin.db.models.platform.entries import Entries

    entry = session.get(Entries, entry_id)
    errors = (entry.metadata_json or {}).get(ERROR_METADATA_KEY) if entry is not None and entry.group_id == group_id else None
    if not isinstance(errors, dict) or slug not in errors:
        return
    remaining = {k: v for k, v in errors.items() if k != slug}
    metadata = {k: v for k, v in (entry.metadata_json or {}).items() if k != ERROR_METADATA_KEY}
    entry.metadata_json = {**metadata, ERROR_METADATA_KEY: remaining} if remaining else metadata


class _RowFailure:
    """A retry's failure rebuilt from its row, for applying `then` when the run never reached the policy."""

    def __init__(self, row, message: str):
        self.integration_id, self.integration_slug, self.provider = row.integration_id, row.integration_slug, row.provider
        self.provider_name = _provider_name(row.provider)
        self.action_key, self.code, self.detail = row.action, row.code, message
        self.partial, self.retry_after, self.seed = None, None, row.idempotency_seed


def retry_failed_plainly(session, row, message: str) -> None:
    """A retry run failed without reaching the policy (the connection was disabled or removed, the
    workflow broke before the step, or the run kept crashing): count the attempt, then retry again — or
    end the chain and apply its `then` (notify admins when it has none), so it never ends silently."""
    handle = row.handle or {}
    retry = handle.get("retry")
    timed_out = _now() - (_aware(row.created_at) or _now()) >= MAX_CHAIN_AGE
    if retry and row.attempt < row.max_attempts and not timed_out:
        row.last_error = message[:2000]
        delay = max(_retry_delay(retry, row.attempt + 1), MIN_RETRY_DELAY)
        row.status, row.next_attempt_at, row.lease_until = "pending", _now() + timedelta(seconds=delay), None
        session.commit()
        return
    _finish(row, "exhausted", error=message)
    session.commit()
    then = handle.get("then") or {"notify": True}
    try:
        from marvin.db.models.groups.automations import WorkspaceAutomationModel

        automation = session.get(WorkspaceAutomationModel, row.automation_id)
        entry = (row.snapshot or {}).get("entry") or ({"id": str(row.entry_id)} if row.entry_id else None)
        context = {"entry": entry, "event": (row.snapshot or {}).get("event") or {}, "depth": 0}
        _effects(session, row.group_id, _RowFailure(row, message), then, automation=automation, context=context, user_id=None)
        session.commit()
    except Exception as e:  # noqa: BLE001
        session.rollback()
        logger.warning("could not apply the end of retry chain %s: %s", row.id, e)


def finish_retry(session, row, status: str, reason: str | None = None) -> None:
    """Close a retry chain (succeeded / superseded / exhausted / failed), saying why."""
    _finish(row, status, error=reason)
    session.commit()


def claim_next(session, now: datetime | None = None) -> IntegrationRetryModel | None:
    """Claim the next due retry (or one whose lease ran out mid-run), one at a time so a tick can stop
    when its time is up and leave the rest pending. Retries of a disabled workflow wait (they run once
    it is enabled again). A reclaimed lease counts as an attempt, so a run that keeps crashing the
    process still runs out of retries."""
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    now = now or _now()
    enabled = (
        session.query(WorkspaceAutomationModel.id)
        .filter(WorkspaceAutomationModel.id == IntegrationRetryModel.automation_id, WorkspaceAutomationModel.enabled.is_(True))
        .exists()
    )
    row = (
        session.query(IntegrationRetryModel)
        .filter(
            ((IntegrationRetryModel.status == "pending") & (IntegrationRetryModel.next_attempt_at <= now))
            | ((IntegrationRetryModel.status == "running") & (IntegrationRetryModel.lease_until < now)),
            enabled,
        )
        .order_by(IntegrationRetryModel.next_attempt_at.asc())
        .first()
    )
    if row is None:
        return None
    row.attempt += 1
    row.status, row.lease_until = "running", now + RETRY_LEASE
    session.commit()
    return row


def claim_due(session, now: datetime | None = None, limit: int = 25) -> list[IntegrationRetryModel]:
    """Claim up to ``limit`` due retries (see :func:`claim_next`)."""
    claimed = []
    while len(claimed) < limit and (row := claim_next(session, now)) is not None:
        claimed.append(row)
    return claimed


def prune(session, now: datetime | None = None) -> int:
    """Delete retry history and resolved alerts older than 30 days."""
    cutoff = (now or _now()) - PRUNE_AFTER
    gone = (
        session.query(IntegrationRetryModel)
        .filter(IntegrationRetryModel.status.notin_(RETRY_LIVE), IntegrationRetryModel.finished_at < cutoff)
        .delete(synchronize_session=False)
    )
    gone += (
        session.query(IntegrationAlertModel)
        .filter(IntegrationAlertModel.status == "resolved", IntegrationAlertModel.resolved_at < cutoff)
        .delete(synchronize_session=False)
    )
    session.commit()
    return gone


# ── alerts ──────────────────────────────────────────────────────────────────────


def _has_open_alert(session, group_id, integration_id) -> bool:
    if integration_id is None:
        return False
    return session.query(IntegrationAlertModel.id).filter_by(group_id=group_id, integration_id=integration_id, status="open").first() is not None


def _notify_for(session, group_id, error, **sample) -> None:
    notify(
        session,
        group_id,
        integration_id=error.integration_id,
        integration_slug=error.integration_slug,
        provider=error.provider,
        code=error.code,
        message=error.detail,
        action=error.action_key,
        **sample,
    )


def notify(
    session,
    group_id,
    *,
    integration_id,
    integration_slug: str,
    provider: str,
    code: str,
    message: str,
    action: str | None = None,
    entry_id=None,
    automation_slug: str | None = None,
    source: str = "workflow",
) -> IntegrationAlertModel | None:
    """Open the connection's alert for ``code`` — or count another failure on the open one. Announced
    when it opens and when the reminder window has passed since it was last announced."""
    if _delivering_alert.get():
        return None
    now = _now()
    sample = {
        "at": now.isoformat(timespec="seconds"),
        "message": (message or "")[:500],
        "action": action,
        "entry_id": str(entry_id) if entry_id else None,
        "automation_slug": automation_slug,
        "source": source,
    }
    open_key = f"{integration_id}:{code}"
    alert = session.query(IntegrationAlertModel).filter_by(group_id=group_id, open_key=open_key).first()
    if alert is None:
        alert = IntegrationAlertModel(
            session=session,
            group_id=group_id,
            integration_id=integration_id,
            integration_slug=integration_slug,
            provider=provider,
            code=code,
            status="open",
            open_key=open_key,
            message=(message or "")[:2000],
            count=1,
            first_at=now,
            last_at=now,
            samples=[sample],
            notified_at=now,
            channels=alert_channels(session, group_id),
        )
        session.add(alert)
        try:
            session.commit()
        except IntegrityError:  # opened concurrently — count it on that one instead
            session.rollback()
            return notify(
                session,
                group_id,
                integration_id=integration_id,
                integration_slug=integration_slug,
                provider=provider,
                code=code,
                message=message,
                action=action,
                entry_id=entry_id,
                automation_slug=automation_slug,
                source=source,
            )
        _emit(session, alert, NEEDED)
        return alert

    alert.count = (alert.count or 0) + 1
    alert.last_at = now
    alert.message = (message or "")[:2000]
    alert.samples = [*(alert.samples or []), sample][-MAX_SAMPLES:]
    hours = _reminder_hours(session, group_id)
    remind = hours > 0 and (alert.notified_at is None or now - _aware(alert.notified_at) >= timedelta(hours=hours))
    if remind:
        alert.notified_at = now
        alert.channels = _merge_channels(alert.channels, alert_channels(session, group_id))
    session.commit()
    if remind:
        _emit(session, alert, NEEDED, reminder=True)
    return alert


def resolve_alerts(session, group_id, integration_id, *, resolution: str, user_id=None, alert_id=None) -> int:
    """Resolve the connection's open alerts (or just ``alert_id``), announce each, and re-arm the
    retries that were parked waiting for it to recover. Returns how many resolved."""
    if _delivering_alert.get():
        return 0
    query = session.query(IntegrationAlertModel).filter_by(group_id=group_id, integration_id=integration_id, status="open")
    if alert_id is not None:
        query = query.filter(IntegrationAlertModel.id == alert_id)
    alerts = query.all()
    if not alerts:
        return 0
    now = _now()
    for alert in alerts:
        alert.status, alert.open_key = "resolved", None
        alert.resolved_at, alert.resolved_by, alert.resolution = now, user_id, resolution
    if not _has_open_alert_except(session, group_id, integration_id, {a.id for a in alerts}):
        _rearm_parked(session, group_id, integration_id, now)
    session.commit()
    for alert in alerts:
        _emit(session, alert, RESOLVED)
    return len(alerts)


def _has_open_alert_except(session, group_id, integration_id, ids: set) -> bool:
    query = session.query(IntegrationAlertModel.id).filter_by(group_id=group_id, integration_id=integration_id, status="open")
    return query.filter(IntegrationAlertModel.id.notin_(ids)).first() is not None


def _rearm_parked(session, group_id, integration_id, now: datetime) -> None:
    rows = session.query(IntegrationRetryModel).filter_by(group_id=group_id, integration_id=integration_id, status="parked").all()
    for row in rows:
        retry = (row.handle or {}).get("retry") or {}
        row.status = "pending"
        row.next_attempt_at = now + timedelta(seconds=max(_retry_delay(retry, row.attempt + 1), MIN_RETRY_DELAY))


def rearm_orphaned_parked(session, now: datetime | None = None) -> int:
    """Parked retries whose connection has no open alert go back to pending — nothing would ever resolve
    them (the alert resolved between the failure and the parking, or was never opened)."""
    now = now or _now()
    open_alert = (
        session.query(IntegrationAlertModel.id)
        .filter(
            IntegrationAlertModel.group_id == IntegrationRetryModel.group_id,
            IntegrationAlertModel.integration_id == IntegrationRetryModel.integration_id,
            IntegrationAlertModel.status == "open",
        )
        .exists()
    )
    rows = session.query(IntegrationRetryModel).filter(IntegrationRetryModel.status == "parked", ~open_alert).all()
    for row in rows:
        retry = (row.handle or {}).get("retry") or {}
        row.status = "pending"
        row.next_attempt_at = now + timedelta(seconds=max(_retry_delay(retry, row.attempt + 1), MIN_RETRY_DELAY))
    if rows:
        session.commit()
    return len(rows)


def _reminder_hours(session, group_id) -> int:
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    prefs = session.query(GroupPreferencesModel).filter_by(group_id=group_id).first()
    hours = getattr(prefs, "integration_alert_reminder_hours", None)
    return hours if isinstance(hours, int) and hours >= 0 else 24


def alert_channels(session, group_id) -> dict:
    """The subscription rows an alert goes out through right now (the routing panel writes them)."""
    from marvin.db.models.groups.email_event_subscriptions import EmailEventSubscriptionModel
    from marvin.db.models.groups.integration_event_subscriptions import IntegrationEventSubscriptionModel

    def ids(model) -> list[str]:
        return [str(i) for (i,) in session.query(model.id).filter_by(group_id=group_id, event_type=NEEDED, enabled=True).all()]

    return {"email": ids(EmailEventSubscriptionModel), "integration": ids(IntegrationEventSubscriptionModel)}


def _merge_channels(old: dict | None, new: dict) -> dict:
    old = old or {}
    return {kind: sorted({*(old.get(kind) or []), *(new.get(kind) or [])}) for kind in ("email", "integration")}


def resolved_channel_rows(session, group_id, event, model, kind: str) -> list:
    """For an ``integration_attention_resolved`` event, the ``kind`` subscription rows that delivered
    its alert — they get the resolved notice even if the routing changed since (a disabled row too)."""
    if getattr(getattr(event, "event_type", None), "name", None) != RESOLVED:
        return []
    doc = getattr(event, "document_data", None)
    channels = getattr(doc, "channels", None) or {}
    wanted = [c for c in (channels.get(kind) or []) if c]
    if not wanted:
        return []
    from uuid import UUID

    try:
        ids = [UUID(str(c)) for c in wanted]
    except ValueError:
        return []
    return session.query(model).filter(model.group_id == group_id, model.id.in_(ids)).all()


def _provider_name(provider_key: str) -> str:
    try:
        from marvin.services.integrations import get_provider

        return getattr(get_provider(provider_key), "name", None) or provider_key
    except Exception:  # noqa: BLE001 — uninstalled provider or no SDK: the key will do
        return provider_key


def _emit(session, alert: IntegrationAlertModel, event_name: str, *, reminder: bool = False) -> None:
    """Dispatch an alert event (bell, plus whatever subscriptions route it). Never raises, and while it
    is being delivered no failure may open or bump an alert (the loop guard)."""
    from marvin.core.config import get_app_settings
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.services.event_bus_service.event_bus_service import EventBusService
    from marvin.services.event_bus_service.event_types import EventIntegrationAttentionData, EventTypes

    token = _delivering_alert.set(True)
    try:
        integration = session.get(IntegrationModel, alert.integration_id)
        name = getattr(integration, "name", None) or alert.integration_slug
        provider_name = _provider_name(alert.provider)
        first_at = _aware(alert.first_at)
        if event_name == NEEDED:
            title = f"{provider_name} needs attention"
            times = f" ({alert.count} failures since {first_at:%Y-%m-%d %H:%M} UTC)" if alert.count > 1 and first_at else ""
            summary = f"{provider_name} ({name}) needs attention — {alert.code}: {alert.message or 'failed'}{times}"
        else:
            how = {"check": "a passing health check", "action": "a successful action", "manual": "an admin"}.get(alert.resolution or "", "")
            title = f"{provider_name} is working again"
            summary = f"{provider_name} ({name}) is working again — {alert.code} resolved" + (f" by {how}" if how else "")
        base_url = (get_app_settings().BASE_URL or "").rstrip("/")
        EventBusService(bg_tasks=None).dispatch(
            integration_id="integrations",
            group_id=alert.group_id,
            event_type=EventTypes.integration_attention_needed if event_name == NEEDED else EventTypes.integration_attention_resolved,
            document_data=EventIntegrationAttentionData(
                alert_id=alert.id,
                integration_id=alert.integration_id,
                integration_slug=alert.integration_slug,
                integration_name=name,
                provider=alert.provider,
                provider_name=provider_name,
                code=alert.code,
                error=alert.message if event_name == NEEDED else None,
                count=alert.count,
                first_at=first_at,
                last_at=_aware(alert.last_at),
                reminder=reminder,
                resolution=alert.resolution if event_name == RESOLVED else None,
                title=title,
                summary=summary,
                channels=alert.channels or {},
                settings_url=f"{base_url}/workspace/settings/integrations" if base_url else None,
                workspace_id=alert.group_id,
            ),
            message=summary,
            entity_id=alert.integration_id,
            entity_type="integration",
        )
    except Exception as e:  # noqa: BLE001 — a lost announcement must not break the call that raised it
        logger.warning("could not announce integration alert %s: %s", alert.id, e)
    finally:
        _delivering_alert.reset(token)


# ── connection scope (callers outside workflows) ────────────────────────────────


@contextmanager
def _session_scope(session):
    if session is not None:
        yield session
        return
    from marvin.db.db_setup import session_context

    with session_context() as own:
        yield own


def connection_failed(group_id, integration_id, provider, action_key: str, exc: BaseException, *, source: str, session=None) -> None:
    """A provider call outside a workflow failed: apply only the policy's ``notify`` (no review, no
    retry — there is no entry or pipeline to act on). Best-effort, never raises."""
    if _delivering_alert.get() or integration_id is None:
        return
    try:
        code = error_code(exc)
        with _session_scope(session) as s:
            from marvin.db.models.groups.integrations import IntegrationModel

            row = s.get(IntegrationModel, integration_id)
            policy = policy_for(provider, action_key, code, row.error_overrides) if row is not None else None
            if not (policy and policy.get("notify")):
                return
            notify(
                s,
                group_id,
                integration_id=row.id,
                integration_slug=row.slug,
                provider=row.provider,
                code=code,
                message=str(exc),
                action=action_key,
                source=source,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("could not record %s failure for integration %s: %s", source, integration_id, e)


def connection_succeeded(group_id, integration_id, *, resolution: str = "action", session=None, user_id=None) -> int:
    """The connection worked (an action succeeded, or a check passed): resolve its open alerts. Cheap
    when there are none. Best-effort, never raises."""
    if _delivering_alert.get() or integration_id is None:
        return 0
    try:
        with _session_scope(session) as s:
            if not _has_open_alert(s, group_id, integration_id):
                return 0
            return resolve_alerts(s, group_id, integration_id, resolution=resolution, user_id=user_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("could not resolve alerts for integration %s: %s", integration_id, e)
        return 0


def open_alerts(session, group_id) -> dict:
    """Open alerts by integration id — what the integrations list shows as "Needs attention"."""
    rows = session.query(IntegrationAlertModel).filter_by(group_id=group_id, status="open").order_by(IntegrationAlertModel.last_at.desc()).all()
    by_integration: dict = {}
    for row in rows:
        by_integration.setdefault(row.integration_id, []).append(row)
    return by_integration
