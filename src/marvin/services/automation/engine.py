"""Run a workspace's Flavor B automations for one event.

The listener normalizes an :class:`Event` into a small ``event_ctx`` dict and calls
:func:`run_automations_for_event`. The engine loads the group's enabled automations, builds the
match context (event + the referenced entry), evaluates trigger + conditions, and runs each matching
automation's action pipeline in order — threading ``$previous`` between steps.

Actions dispatch through the action-executor registry (`actions.run_action`) — one executor per
`kind` (operation/emit_event/handler/webhook). The dispatcher is injected (default = the registry) so
the engine is unit-testable without real executors.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from marvin.services.event_bus_service.correlation import correlation_scope, current_correlation_id

from .actions import AutomationActionError
from .actions import run_action as _registry_run_action
from .authz import resolve_authorizer_role
from .matcher import explain, matches
from .recorder import CollectingRecorder, NullRecorder
from .summary import collapse, failed_step, run_message, step_summary, trigger_ref

MAX_ACTIONS = 10  # per-automation guardrail against a runaway pipeline
MAX_REACTION_DEPTH = 3  # how many automation/emit_event hops a single chain may span before we stop


def _ms_since(started: datetime) -> int:
    return int((datetime.now(UTC) - started).total_seconds() * 1000)


def _entry_context(session, group_id, entry_id) -> dict | None:
    """Load the entry facts conditions and actions reference: type slug, status, title, slug, summary,
    the schema fields (`data`), `metadata` (ids an earlier workflow stored, e.g. a Square link),
    `image` (the featured image's public URL) and `url` (its page on the site)."""
    from marvin.db.models.platform.entries import Entries

    entry = session.get(Entries, entry_id)
    if not entry or entry.group_id != group_id:
        return None
    etype = entry.entry_type.slug if entry.entry_type else None
    return {
        "id": str(entry.id),
        "entry_type": etype,
        "status": entry.status,
        "title": entry.title,
        "slug": entry.slug,
        "summary": getattr(entry, "summary", None),
        # Schema fields, so an action can forward content (`${entry.data.body}` → a newsletter API).
        "data": data if isinstance(data := getattr(entry, "data_json", None), dict) else {},
        "metadata": meta if isinstance(meta := getattr(entry, "metadata_json", None), dict) else {},
        # The featured image's public URL, so an action can hand it on (Square shows it at checkout).
        "image": _featured_image_url(entry),
        # Where the site shows the entry, so an action can link back to it (a newsletter's canonical URL).
        "url": _entry_page_url(session, group_id, entry),
    }


def _entry_page_url(session, group_id, entry) -> str | None:
    """The entry's page on the workspace's site — absolute when the Canonical URL is set, else the site
    path; None when its type has no page URL pattern (then no site lookup is made)."""
    if not getattr(entry.entry_type, "page_url_pattern", None):
        return None
    from marvin.services.entry_urls import best_entry_url, site_base_url

    return best_entry_url(entry, site_base_url(session, group_id))


def target_entry_context(session, group_id, entity) -> dict:
    """The `entry` a target row is matched and acted on as — the same full facts an event-triggered
    run sees (`data`, `metadata`, `image`), so a condition like `entry.data.status` works per row."""
    from .selector import entity_ref

    return _entry_context(session, group_id, entity.id) or entity_ref(entity)


def _featured_image_url(entry) -> str | None:
    """Same pick as the publishing API's featured asset — a hero/featured image first, else the first
    image by position — skipping pending AI suggestions, which never reach published output."""
    links = sorted(
        (
            ea
            for ea in (getattr(entry, "entry_assets", None) or [])
            if getattr(ea, "asset", None) is not None
            and str(getattr(ea.asset, "mime_type", "") or "").startswith("image/")
            and not (ea.metadata_json or {}).get("suggested")
        ),
        key=lambda ea: ea.position or 0,
    )
    chosen = next((ea for ea in links if ea.role in ("hero", "featured")), links[0] if links else None)
    if chosen is None:
        return None
    from marvin.services.storage.provider_factory import get_storage_provider

    try:
        return get_storage_provider().get_public_url(chosen.asset.storage_key)
    except Exception:  # noqa: BLE001 — a missing image must never break the workflow context
        return None


def _site_context(session, group_id) -> dict:
    """The workspace's site, so a step can hand it on: `${site.url}` is the Canonical URL (None when unset)
    — e.g. the base a newsletter integration makes an issue's relative links absolute against."""
    from marvin.services.entry_urls import site_base_url

    return {"url": site_base_url(session, group_id)}


def match_context(session, group_id, event_ctx: dict) -> dict:
    """The context an event's automations match and act on: the event, the entry it refers to, and the site."""
    context: dict = {
        "event": event_ctx,
        "previous": {},
        "depth": int(event_ctx.get("reaction_depth", 0)),
        "site": _site_context(session, group_id),
    }
    if event_ctx.get("entry_id"):
        entry_ctx = _entry_context(session, group_id, event_ctx["entry_id"])
        if entry_ctx:
            context["entry"] = entry_ctx
    return context


def run_automations_for_event(
    session,
    group_id,
    event_ctx: dict,
    *,
    logger=None,
    run_action: Callable = _registry_run_action,
    recorder=None,
    dry_run: bool = False,
) -> int:
    """Run every enabled automation matching this event. Returns how many ran (best-effort).

    ``event_ctx`` = ``{"event_type", "entry_id"?, "user_id"?, "reaction_depth"?}``. A single automation
    failing (bad action, provider error) is logged and skipped — never raised, so it can't break
    event dispatch. ``reaction_depth`` is threaded into the context so re-emitting executors bound the
    chain (the listener already refuses past MAX_REACTION_DEPTH).

    ``dry_run=True`` resolves each matching automation's actions without executing them and fires no
    ``automation_ran`` event (used to preview what an event *would* trigger).
    """
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    recorder = recorder or NullRecorder()
    automations = session.query(WorkspaceAutomationModel).filter_by(group_id=group_id, enabled=True).all()
    if not automations:
        return 0

    context = match_context(session, group_id, event_ctx)
    depth = context["depth"]

    user_id = event_ctx.get("user_id")
    ran = 0
    # Open the triggering event's chain (or mint one) so every automation that reacts, and everything
    # they re-emit, threads under one correlation id.
    with correlation_scope(event_ctx.get("correlation_id")):
        for automation in automations:
            defn = automation.definition or {}
            trig = defn.get("trigger") or {}
            if not _trigger_matches(trig, event_ctx):
                continue
            ran_this, ok, run_id = _run_targets(
                session,
                group_id,
                automation,
                context,
                user_id=user_id,
                authorizer_role=resolve_authorizer_role(session, group_id, getattr(automation, "created_by", None)),
                logger=logger,
                run_action=run_action,
                gate_conditions=True,
                recorder=recorder,
                dry_run=dry_run,
                trigger_kind=trig.get("type", "event"),
            )
            if ran_this:
                if not dry_run:
                    _announce(session, group_id, automation, ok, depth, user_id, context, run_id=run_id)
                ran += 1

    return ran


def _target_context(base_context: dict, entity_ref: dict) -> dict:
    """A per-target match context: bind the resolved entity as `entry` and as `$event.entry_id`
    (so entry-defaulting actions target it) while carrying the rest of the base context."""
    base_event = base_context.get("event", {})
    return {**base_context, "event": {**base_event, "entry_id": entity_ref["id"]}, "entry": entity_ref}


def _run_targets(
    session,
    group_id,
    automation,
    base_context: dict,
    *,
    user_id,
    authorizer_role,
    logger,
    run_action,
    gate_conditions: bool,
    recorder,
    dry_run: bool = False,
    trigger_kind: str | None = None,
) -> tuple[int, bool, Any]:
    """Run the automation's pipeline over its target set (the `target` selector) — or, with no
    target, over the single trigger context — recording the run + each step.

    Returns ``(ran_count, all_ok, run_id)``; ``run_id`` is the execution row's id (a fresh one when
    the recorder keeps none), the id `automation_started` and the closing ran/failed event share.
    With a `target`, conditions are always applied as the WHERE over the resolved set. With no
    target, `gate_conditions` decides (events gate; a manual Run does not). Capped by the selector —
    a matched set larger than the cap is truncated and logged.
    """
    defn = automation.definition or {}
    conditions = defn.get("conditions")
    target = defn.get("target")
    trigger_type = (defn.get("trigger") or {}).get("type", "event")

    if target:
        from .selector import entity_ref, resolve_target_entities

        try:
            entities, total = resolve_target_entities(session, group_id, target, base_context)
        except Exception as e:
            if logger:
                logger.warning("automation '%s' target query failed: %s", automation.slug, e)
            return 0, True, None
        capped = total > len(entities)
        if logger and capped:
            logger.warning(
                "automation '%s' target matched %d entities; acting on the first %d (cap)",
                automation.slug,
                total,
                len(entities),
            )
        pairs: list[tuple[dict, Any]] = [
            (_target_context(base_context, target_entry_context(session, group_id, ent)), entity_ref(ent)) for ent in entities
        ]
        gate = True  # a target's conditions are its WHERE clause — always applied
    else:
        # Non-target: single context. If gated and conditions fail, it's a non-run — don't record.
        if gate_conditions and not matches(conditions, base_context):
            return 0, True, None
        pairs = [(base_context, base_context.get("entry"))]
        total, capped, gate = 1, False, gate_conditions

    exec_id = recorder.start(
        automation,
        trigger_type,
        targets_matched=total,
        capped=capped,
        user_id=user_id,
        correlation_id=current_correlation_id.get(),
    )
    run_id = exec_id or uuid4()

    # Every per-target context is built before any step runs, so gating up front picks the same rows
    # as gating one by one — and tells the "running" announcement how many entries the run acts on.
    runnable = [(i, ctx, ref) for i, (ctx, ref) in enumerate(pairs) if not gate or matches(conditions, ctx)]
    if runnable and not dry_run:
        _announce_start(
            group_id,
            automation,
            run_id,
            trigger_kind or trigger_type,
            target_count=len(runnable) if target else None,
            depth=int(base_context.get("depth", 0)),
            user_id=user_id,
            context=base_context,
        )

    ran, ok_all, steps_ok, steps_failed = 0, True, 0, 0
    # What each step did, across every target — the run's automation_ran / automation_failed names them.
    step_log: list[dict] = []
    base_context["_step_log"] = step_log
    for target_index, ctx, ref in runnable:
        ok, s_ok, s_failed = _run_pipeline(
            session,
            group_id,
            automation,
            ctx,
            user_id=user_id,
            authorizer_role=authorizer_role,
            logger=logger,
            run_action=run_action,
            recorder=recorder,
            exec_id=exec_id,
            target_index=target_index,
            target_ref=ref,
            dry_run=dry_run,
            step_log=step_log,
        )
        ok_all = ok_all and ok
        steps_ok += s_ok
        steps_failed += s_failed
        ran += 1

    status = "success" if ok_all else ("partial" if steps_ok else "failed")
    recorder.finish(exec_id, status=status, error=base_context.get("_error"), targets_run=ran, steps_ok=steps_ok, steps_failed=steps_failed)
    return ran, ok_all, run_id


def _trigger_matches(trig: dict, event_ctx: dict) -> bool:
    """Does this event fire this trigger? Event triggers match by event name; chained/on-error
    triggers match the automation lifecycle events (optionally targeting a specific automation)."""
    ttype = trig.get("type", "event")
    etype = event_ctx.get("event_type")
    if ttype == "event":
        return trig.get("event") == etype
    if ttype == "incoming_webhook":
        # Fire on an incoming_webhook event; an empty/"any" target matches any webhook, else the slug.
        if etype != "incoming_webhook":
            return False
        target = trig.get("webhook")
        return not target or target == "any" or target == event_ctx.get("webhook_slug")
    if ttype == "chained":
        return etype == "automation_ran" and _target_ok(trig, event_ctx)
    if ttype == "on_error":
        return etype == "automation_failed" and _target_ok(trig, event_ctx)
    return False  # manual / schedule — not event-driven


def _target_ok(trig: dict, event_ctx: dict) -> bool:
    """chained/on-error may target a specific source automation (by slug or id); empty/"any" = all."""
    target = trig.get("automation")
    if not target or target == "any":
        return True
    return target in (event_ctx.get("automation_slug"), event_ctx.get("automation_id"))


def _announce(session, group_id, automation, ok: bool, depth: int, user_id, context: dict, *, run_id=None) -> None:
    """Emit automation_ran / automation_failed so chained + on-error triggers can react.

    The event is about the workflow; it names what triggered the run (``trigger_entity_*``) and, in
    its message and ``steps``, what each step did. Dispatched at reaction_depth+1 so chains stay
    bounded (the listener refuses past MAX_REACTION_DEPTH). Best-effort — never breaks the run.
    """
    from marvin.services.event_bus_service.event_bus_service import EventBusService
    from marvin.services.event_bus_service.event_types import EventAutomationData, EventTypes

    event_type = EventTypes.automation_ran if ok else EventTypes.automation_failed
    try:
        steps = collapse(context.get("_step_log") or [])
        failed = failed_step(steps)
        EventBusService(bg_tasks=None).dispatch(
            integration_id="automation",
            group_id=group_id,
            event_type=event_type,
            document_data=EventAutomationData(
                automation_id=automation.id,
                automation_slug=automation.slug,
                automation_name=getattr(automation, "name", None),
                execution_id=run_id,
                ok=ok,
                error=None if ok else context.get("_error") or (failed or {}).get("error"),
                workspace_id=group_id,
                steps=steps,
                **trigger_ref(context),
            ),
            message=run_message(automation.slug, ok, steps),
            user_id=user_id,
            entity_id=automation.id,
            entity_type="automation",
            reaction_depth=depth + 1,
        )
    except Exception:
        pass


def _announce_start(group_id, automation, run_id, trigger: str, *, target_count: int | None, depth: int, user_id, context: dict) -> None:
    """Emit automation_started so the admin sees a run in progress; its ran/failed event carries the same run id.

    Nothing reacts to it (it isn't a workflow trigger), but it goes out at depth+1 like the other
    lifecycle events. Best-effort — never breaks the run.
    """
    from marvin.services.event_bus_service.event_bus_service import EventBusService
    from marvin.services.event_bus_service.event_types import EventAutomationData, EventTypes

    try:
        EventBusService(bg_tasks=None).dispatch(
            integration_id="automation",
            group_id=group_id,
            event_type=EventTypes.automation_started,
            document_data=EventAutomationData(
                automation_id=automation.id,
                automation_slug=automation.slug,
                automation_name=getattr(automation, "name", None),
                execution_id=run_id,
                trigger=trigger,
                target_count=target_count,
                workspace_id=group_id,
                **trigger_ref(context),
            ),
            message=f"Automation '{automation.slug}' started",
            user_id=user_id,
            entity_id=automation.id,
            entity_type="automation",
            reaction_depth=depth + 1,
        )
    except Exception:
        pass


@dataclass
class _StepRunner:
    """Runs and records one step at a time for a pipeline, threading its outputs into the context."""

    session: Any
    group_id: Any
    automation: Any
    context: dict
    user_id: Any
    authorizer_role: Any
    logger: Any
    run_action: Callable
    recorder: Any
    exec_id: Any
    target_index: int
    target_ref: Any
    dry_run: bool
    step_log: list | None

    def run(self, action: dict, action_index: int, *, on_failure: bool = False) -> AutomationActionError | None:
        """Run one step; returns its error (already recorded and logged), or None when it succeeded."""
        started = datetime.now(UTC)
        record = {"target_index": self.target_index, "target_ref": self.target_ref, "action_index": action_index, "action": action}
        if on_failure:
            record["on_failure"] = True
        try:
            out = self.run_action(
                self.session, self.group_id, action, self.context, user_id=self.user_id, authorizer_role=self.authorizer_role, dry_run=self.dry_run
            )
        except AutomationActionError as e:
            self.recorder.action(self.exec_id, **record, status="failed", error=str(e), duration_ms=_ms_since(started))
            if self.step_log is not None:
                self.step_log.append(step_summary(self.session, action, error=str(e), on_failure=on_failure))
            if self.logger:
                what = "on_failure step" if on_failure else "action"
                self.logger.warning("automation '%s' %s kind=%s failed: %s", self.automation.slug, what, action.get("kind"), e)
            return e
        self.recorder.action(self.exec_id, **record, status="success", output=out, duration_ms=_ms_since(started))
        if self.step_log is not None:
            self.step_log.append(step_summary(self.session, action, output=out, on_failure=on_failure))
        out_dict = out if isinstance(out, dict) else {}
        self.context["previous"] = out_dict
        step_entry = {"output": out_dict}
        self.context["steps"][str(action_index)] = step_entry
        if action.get("id"):
            self.context["steps"][str(action["id"])] = step_entry  # $steps.<id>.output.*
        return None


def _run_pipeline(
    session,
    group_id,
    automation,
    context: dict,
    *,
    user_id,
    authorizer_role,
    logger,
    run_action,
    recorder=None,
    exec_id=None,
    target_index: int = 0,
    target_ref=None,
    dry_run: bool = False,
    step_log: list | None = None,
) -> tuple[bool, int, int]:
    """Run one automation's action pipeline in order, recording each step. Returns
    ``(all_ok, steps_ok, steps_failed)`` — counting the workflow's own steps, not its on_failure ones.

    A fresh `previous` is set so pipelines don't leak into each other; a failing step stops the rest
    (later steps usually depend on it) and runs the definition's `on_failure` steps, once, with the
    failure as ``${error.*}``. Each step's summary is appended to ``step_log`` when given.
    """
    recorder = recorder or NullRecorder()
    defn = automation.definition or {}
    actions = (defn.get("actions") or [])[:MAX_ACTIONS]
    if logger and len(defn.get("actions") or []) > MAX_ACTIONS:
        logger.warning("automation '%s' has %d steps; only the first %d run (MAX_ACTIONS)", automation.slug, len(defn["actions"]), MAX_ACTIONS)
    # Fresh per-run scratch so pipelines don't leak. `steps` is addressable by position ("0") and by
    # an action's optional `id`; `previous` is the last step's output (an alias for the common case).
    context["previous"] = {}
    context["steps"] = {}
    context.pop("_error", None)
    context.pop("error", None)
    step = _StepRunner(
        session=session,
        group_id=group_id,
        automation=automation,
        context=context,
        user_id=user_id,
        authorizer_role=authorizer_role,
        logger=logger,
        run_action=run_action,
        recorder=recorder,
        exec_id=exec_id,
        target_index=target_index,
        target_ref=target_ref,
        dry_run=dry_run,
        step_log=step_log,
    )
    for action_index, action in enumerate(actions):
        error = step.run(action, action_index)
        if error is not None:
            context["_error"] = str(error)
            _run_on_failure(step, defn.get("on_failure") or [], error, action, action_index, first_index=len(actions))
            return False, action_index, 1
    return True, len(actions), 0


def _run_on_failure(step: _StepRunner, handlers: list, error: AutomationActionError, action: dict, action_index: int, *, first_index: int) -> None:
    """Run the definition's `on_failure` steps after a step failed — same run, same entry, with
    ``${error.message}``, ``${error.code}`` (the integration's stable reason, when it gave one),
    ``${error.step}`` (the failed step's id, else its position), ``${error.kind}`` and ``${error.at}``.

    They run once: a failing on_failure step stops the rest and has no handler of its own, so a
    broken handler can never loop. Recorded after the workflow's steps, labelled as on-failure."""
    if not handlers:
        return
    step.context["error"] = {
        "message": str(error),
        "code": error.code,
        "step": str(action.get("id") or action_index),
        "kind": action.get("kind"),
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    for offset, handler in enumerate(handlers[:MAX_ACTIONS]):
        if step.run(handler, first_index + offset, on_failure=True) is not None:
            return


def run_automation_now(
    session,
    group_id,
    automation,
    *,
    user_id=None,
    logger=None,
    run_action: Callable = _registry_run_action,
    recorder=None,
    dry_run: bool = False,
    trigger_kind: str = "manual",
) -> dict:
    """Run one automation on demand (the Manual trigger / Run button) — skips the trigger + condition
    gates (the human explicitly asked for it). No event, so `$event.*` resolves to None; best for
    automations whose steps don't need a specific entry (webhook, handler, reindex, …).
    ``trigger_kind`` says who asked (manual, schedule, chat) on the run's lifecycle events.

    ``dry_run=True`` evaluates the target + conditions and resolves each action's inputs but executes
    nothing (no AI call, no mutation, no webhook POST). It records nothing to the execution history and
    fires no ``automation_ran`` event; instead it returns ``plan`` — the resolved per-step preview.
    """
    context: dict = {
        "event": {"event_type": "manual", "user_id": str(user_id) if user_id else None},
        "previous": {},
        "depth": 0,
        "site": _site_context(session, group_id),
    }
    # A dry run captures the resolved plan in memory and persists nothing; a real run uses the caller's
    # recorder (or none).
    dry_recorder = CollectingRecorder() if dry_run else None
    # A manual run roots a fresh chain (no triggering event) so its execution + any re-emitted events
    # share one correlation id.
    with correlation_scope():
        # Manual run skips conditions when acting on the single (implicit) context — the human asked
        # for it. But when a `target` selects a set, its conditions are the WHERE over that set and
        # DO apply.
        ran, ok, run_id = _run_targets(
            session,
            group_id,
            automation,
            context,
            user_id=user_id,
            authorizer_role=resolve_authorizer_role(session, group_id, getattr(automation, "created_by", None)),
            logger=logger,
            run_action=run_action,
            gate_conditions=False,
            recorder=dry_recorder or recorder or NullRecorder(),
            dry_run=dry_run,
            trigger_kind=trigger_kind,
        )
        if dry_run:
            assert dry_recorder is not None  # set whenever dry_run is True
            return {"ok": ok, "ran": ran, "dry_run": True, "plan": dry_recorder.plan}
        _announce(session, group_id, automation, ok, 0, user_id, context, run_id=run_id)
        return {"ok": ok, "ran": ran, "result": context.get("previous", {})}


def dry_run_for_event(
    session,
    group_id,
    automation,
    event_ctx: dict,
    *,
    logger=None,
    run_action: Callable = _registry_run_action,
) -> dict:
    """Preview what one automation would do for one event, without doing it.

    ``event_ctx`` is the `event` the listener would build (see :mod:`.context`) — a logged event
    replayed, or one synthesized for an entry. The match context is built exactly as the event path
    builds it, and the result reports the trigger match, every condition with the values it compared,
    and ``would_fire``. Steps are resolved against that context even when a gate fails, so the plan
    still shows what a run *would* send. With a `target`, conditions are the per-row WHERE (as on a
    real run), so ``conditions`` is empty and ``would_fire`` means "a row matched".

    Executes nothing, records nothing, fires no events.
    """
    defn = automation.definition or {}
    trig = defn.get("trigger") or {}
    conditions = defn.get("conditions")
    has_target = bool(defn.get("target"))
    context = match_context(session, group_id, event_ctx)
    trigger_matched = _trigger_matches(trig, event_ctx)
    checks = [] if has_target else explain(conditions, context)
    conditions_pass = True if has_target else matches(conditions, context)

    recorder = CollectingRecorder()
    with correlation_scope():
        ran, ok, _ = _run_targets(
            session,
            group_id,
            automation,
            context,
            user_id=event_ctx.get("user_id"),
            authorizer_role=resolve_authorizer_role(session, group_id, getattr(automation, "created_by", None)),
            logger=logger,
            run_action=run_action,
            gate_conditions=False,
            recorder=recorder,
            dry_run=True,
            trigger_kind=trig.get("type", "event"),
        )
    return {
        "ok": ok,
        "ran": ran,
        "dry_run": True,
        "plan": recorder.plan,
        "trigger_matched": trigger_matched,
        "conditions": checks,
        "conditions_pass": conditions_pass,
        "would_fire": trigger_matched and (ran > 0 if has_target else conditions_pass),
    }
