"""Events hub — one lookup: what sends an event type and what reacts to it.

Nothing is stored here; every connection is read from where it lives, when asked:

* **Reactions** — one UNION ALL over the four subscription stores (integration actions, emails, outgoing webhooks,
  workflow triggers), plus the system email template an event sends when no workspace template is connected, then
  the built-in reactions declared in code (`builtin_reactions`). Switched-off ones are listed too: `enabled` says
  whether the event bus would run it now, decided exactly as each listener decides (`_runs`).
* **Senders** — the catalog's `sent_by` lines (Marvin itself), then the workspace's own rows that send it: workflows
  whose steps send it (Emit event, a task step such as Request Site Rebuild, an entry step), the incoming webhooks
  that start such a workflow (one hop), and scheduled tasks whose task type sends it (`ScheduledTaskHandler.sends`).
  Workflows are scanned in Python (a few dozen rows; the steps live in JSON, with no stored copy).
* **Recent** — the newest Event Log rows of the type, with whether the workspace records the type at all.
* **Chain** — the catalog's `leads_to`, and its reverse.

Not listed, because they depend on the event's payload rather than on anything stored: an
`integration_attention_resolved` notice also reaches the routes that delivered its alert
(services/integrations/errors.py `resolved_channel_rows`), and `webhook_task` (scheduler plumbing) posts the
scheduled webhooks due in its time window. A workflow's conditions are also left to run time.

Platform-scope event types (sign-ups, backups, …) aren't a workspace's: the workspace API leaves them out and
`platform_detail` gives the super-admin view.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import NamedTuple

import sqlalchemy as sa
from sqlalchemy.orm import Session, aliased

from marvin.db.models._model_utils.guid import GUID
from marvin.schemas.platform.event_connections import (
    EventConnectionCounts,
    EventConnections,
    EventReaction,
    EventSender,
    EventTypeRef,
    InstalledBy,
    WorkspaceEventReactions,
)
from marvin.schemas.platform.event_log import EventLogSummary
from marvin.services.events.event_catalog import CATALOG, TRIGGERABLE_EVENT_TYPES, CatalogEntry, get_catalog_entry

# The order reactions are listed in (built-in ones come last).
_REACTION_ORDER = {"workflow": 0, "integration_action": 1, "email": 2, "webhook": 3}
# Workflow trigger types that listen to an event of their own (the rest name it in trigger_event as "event").
_LIFECYCLE_TRIGGERS = {"incoming_webhook": "incoming_webhook", "automation_ran": "chained", "automation_failed": "on_error"}
# scheduler plumbing: the webhook, integration and email listeners ignore its subscriptions
_WEBHOOK_TASK = "webhook_task"
_RECIPIENTS = {"admins": "To the workspace admins", "specific": "To specific addresses", "event_field": "To an address in the event"}


def workspace_entry(event_type: str) -> CatalogEntry | None:
    """The catalog entry for a shown workspace-scope event type, or None (unknown, hidden, or a platform event)."""
    entry = get_catalog_entry(event_type)
    return entry if entry is not None and entry.scope == "workspace" and not entry.hidden else None


# ── reactions ────────────────────────────────────────────────────────────────


class _Facts(NamedTuple):
    """What decides whether a reaction runs — one subscription row, or (in `summary`) a group of alike rows."""

    kind: str  # integration_action | email | system_email | webhook | workflow
    event_type: str
    own_enabled: bool | None  # the subscription / webhook / workflow switch
    parent_enabled: bool | None  # the integration's / email template's switch (True where there's none)
    template_type: str | None
    template_group: object | None  # the email template's workspace (None: a system template)
    trigger_type: str | None
    group_id: object | None


def _str(value) -> str | None:
    return None if value is None else str(value).replace("-", "").lower()


def _same(a, b) -> bool:
    return a is not None and b is not None and _str(a) == _str(b)


def _workflow_runs(f: _Facts) -> bool:
    """AutomationReactionListener takes the triggerable events plus the three lifecycle ones; the engine then
    runs the enabled workflows whose trigger_event is the event and whose trigger type matches it."""
    if not f.own_enabled:
        return False
    lifecycle = _LIFECYCLE_TRIGGERS.get(f.event_type)
    if lifecycle is not None:
        return f.trigger_type in (lifecycle, "event")
    return f.event_type in TRIGGERABLE_EVENT_TYPES and f.trigger_type == "event"


def _runs(facts: list[_Facts], group_id) -> list[bool]:
    """For one event type in one workspace: whether the event bus runs each reaction, decided the way each
    listener decides (event_bus_listener.py) — Marvin's own email that carries a live link (the invitation) is sent
    by the code that mints it, by the same rule. `facts` must hold every reaction row of that type and workspace,
    so the email rule below can see the others."""
    from marvin.services.email.system_email_events import get_template_type_for_event
    from marvin.services.events.event_catalog import is_platform_event

    if not facts:
        return []
    event_type = facts[0].event_type
    system_type = get_template_type_for_event(event_type)
    # A platform event reaches none of the workspace's subscriptions (event_bus_listener._platform_event); only
    # Marvin's own email for it (or the workspace template that replaces it) sends.
    workspace_hears = not is_platform_event(event_type)

    def deliverable(f: _Facts) -> bool:  # EmailEventListener.publish_to_subscribers: a usable, enabled template
        return bool(f.own_enabled and f.parent_enabled) and (f.template_group is None or _same(f.template_group, group_id))

    # EmailEventListener.get_subscribers: for an event with a system template (invitation, welcome),
    # enabled subscriptions to this workspace's own enabled template of that type replace it — and
    # only those send; with none, the enabled system template sends instead of every subscription.
    connected = (
        [
            f
            for f in facts
            if f.kind == "email" and f.own_enabled and f.parent_enabled and f.template_type == system_type and _same(f.template_group, group_id)
        ]
        if system_type
        else []
    )
    system = next((f for f in facts if f.kind == "system_email"), None)
    system_sends = bool(system_type and not connected and system is not None and system.parent_enabled)

    out = []
    for f in facts:
        if f.event_type == _WEBHOOK_TASK and f.kind != "workflow":
            out.append(False)
        elif f.kind == "workflow":
            out.append(workspace_hears and _workflow_runs(f))
        elif f.kind == "integration_action":  # IntegrationEventListener: enabled subscription, enabled integration
            out.append(workspace_hears and bool(f.own_enabled and f.parent_enabled))
        elif f.kind == "webhook":  # WebhookEventListener: enabled event-driven webhook (the query keeps only those)
            out.append(workspace_hears and bool(f.own_enabled))
        elif f.kind == "system_email":
            out.append(f is system and system_sends)
        elif connected:
            out.append(f in connected)
        else:
            out.append(workspace_hears and not system_sends and deliverable(f))
    return out


_COLUMNS = (
    "kind",
    "event_type",
    "id",
    "name",
    "own_enabled",
    "parent_enabled",
    "detail",
    "template_id",
    "template_type",
    "template_group",
    "trigger_type",
    "source_id",
    "source_blueprint",
    "group_id",
)


def _reaction_union(group_id, event_type: str | None):
    """Every stored reaction as one UNION ALL subquery with `_COLUMNS`. `group_id` None: every workspace;
    `event_type` None: every type."""
    from marvin.db.models.groups.automations import WorkspaceAutomationModel as Workflow
    from marvin.db.models.groups.email_event_subscriptions import EmailEventSubscriptionModel as EmailSub
    from marvin.db.models.groups.email_templates import EmailTemplateModel as Template
    from marvin.db.models.groups.integration_event_subscriptions import IntegrationEventSubscriptionModel as IntegrationSub
    from marvin.db.models.groups.integrations import IntegrationModel as Integration
    from marvin.db.models.groups.webhook_event_subscriptions import WebhookEventSubscriptionModel as WebhookSub
    from marvin.db.models.groups.webhooks import GroupWebhooksModel as Webhook
    from marvin.services.email.system_email_events import SYSTEM_TEMPLATE_EVENT_MAP
    from marvin.services.event_bus_service.event_types import WebhookMode

    no_text, no_id, yes = sa.cast(sa.null(), sa.String), sa.cast(sa.null(), GUID), sa.true()

    def row(kind: str, *values):
        return sa.select(*(v.label(n) for v, n in zip((sa.cast(sa.literal(kind), sa.String), *values), _COLUMNS, strict=True)))

    def scoped(stmt, owner_group, event_column):
        if group_id is not None:
            stmt = stmt.where(owner_group == group_id)
        return stmt.where(event_column == event_type) if event_type is not None else stmt

    integrations = scoped(
        row(
            "integration_action",
            IntegrationSub.event_type,
            IntegrationSub.id,
            Integration.name,
            IntegrationSub.enabled,
            Integration.enabled,
            IntegrationSub.action,
            no_id,
            no_text,
            no_id,
            no_text,
            IntegrationSub.source_integration_id,
            IntegrationSub.source_blueprint,
            IntegrationSub.group_id,
        ).join(Integration, Integration.id == IntegrationSub.integration_id),
        IntegrationSub.group_id,
        IntegrationSub.event_type,
    )
    emails = scoped(
        row(
            "email",
            EmailSub.event_type,
            EmailSub.id,
            Template.name,
            EmailSub.enabled,
            Template.enabled,
            EmailSub.recipient_type,
            Template.id,
            Template.template_type,
            Template.group_id,
            no_text,
            no_id,
            no_text,
            EmailSub.group_id,
        ).join(Template, Template.id == EmailSub.template_id),
        EmailSub.group_id,
        EmailSub.event_type,
    )
    # The system templates (no workspace) an event sends when no workspace template replaces them.
    system_event = sa.case({t: m["event_type"] for t, m in SYSTEM_TEMPLATE_EVENT_MAP.items()}, value=Template.template_type)
    system_emails = row(
        "system_email",
        system_event,
        Template.id,
        Template.name,
        yes,
        Template.enabled,
        no_text,
        Template.id,
        Template.template_type,
        no_id,
        no_text,
        no_id,
        no_text,
        no_id,
    ).where(Template.group_id.is_(None), Template.template_type.in_(list(SYSTEM_TEMPLATE_EVENT_MAP)))
    if event_type is not None:
        system_emails = system_emails.where(system_event == event_type)
    webhooks = scoped(
        row(
            "webhook",
            WebhookSub.event_type,
            Webhook.id,
            sa.func.coalesce(Webhook.name, "Webhook"),
            Webhook.enabled,
            yes,
            no_text,
            no_id,
            no_text,
            no_id,
            no_text,
            no_id,
            no_text,
            Webhook.group_id,
        )
        .join(Webhook, Webhook.id == WebhookSub.webhook_id)
        .where(Webhook.webhook_type == WebhookMode.event_driven),  # the only webhooks the listener delivers events to
        Webhook.group_id,
        WebhookSub.event_type,
    )
    workflows = scoped(
        row(
            "workflow",
            Workflow.trigger_event,
            Workflow.id,
            Workflow.name,
            Workflow.enabled,
            yes,
            Workflow.trigger_ref,
            no_id,
            no_text,
            no_id,
            Workflow.trigger_type,
            Workflow.source_integration_id,
            Workflow.source_blueprint,
            Workflow.group_id,
        ).where(Workflow.trigger_event.is_not(None)),
        Workflow.group_id,
        Workflow.trigger_event,
    )
    return sa.union_all(integrations, emails, system_emails, webhooks, workflows).subquery("reactions")


def _facts(row) -> _Facts:
    return _Facts(*(getattr(row, f) for f in _Facts._fields))


def _reaction(row, runs: bool) -> EventReaction:
    detail, managed_at, kind = row.detail, None, row.kind
    if kind == "workflow":
        managed_at = f"/automation/workflows?workflow={row.id}"
    elif kind == "integration_action":
        managed_at = "/workspace/settings/integrations"
    elif kind == "webhook":
        managed_at = f"/automation/webhooks/{row.id}"
    else:  # an email: who it goes to, never the addresses
        system = kind == "system_email"
        kind, detail = "email", "System template" if system else _RECIPIENTS.get(row.detail or "")
        own = row.template_group is not None
        managed_at = f"/workspace/settings/email/{row.template_id}" if own else f"/workspace/settings/email?customize={row.template_id}"
    installed_by = (
        InstalledBy(integration_id=row.source_id, name=row.source_name, provider=row.source_provider, blueprint=row.source_blueprint)
        if row.source_id is not None and row.source_name is not None
        else None
    )
    return EventReaction(
        kind=kind,
        id=row.id,
        name=row.name or "",
        enabled=runs,
        detail=detail,
        trigger_type=row.trigger_type if kind == "workflow" else None,
        managed_at=managed_at,
        installed_by=installed_by,
    )


def _reaction_rows(session: Session, group_id, event_type: str):
    """The stored reactions to `event_type` (in `group_id`, or every workspace when None), with the integration
    that installed each — one query."""
    from marvin.db.models.groups.integrations import IntegrationModel

    union = _reaction_union(group_id, event_type)
    source = aliased(IntegrationModel, name="source")
    stmt = (
        sa.select(union, source.name.label("source_name"), source.provider.label("source_provider"))
        .select_from(union)
        .outerjoin(source, source.id == union.c.source_id)
    )
    return session.execute(stmt).all()


def _sorted(reactions: list[EventReaction]) -> list[EventReaction]:
    return sorted(reactions, key=lambda r: (_REACTION_ORDER.get(r.kind, 9), r.name.lower(), str(r.id)))


def builtin(event_type: str) -> list[EventReaction]:
    """The built-in reactions (code, not data): always on."""
    from marvin.services.event_bus_service.event_bus_listener import builtin_reactions

    return [EventReaction(kind="builtin", name=label, enabled=True) for label, _ in builtin_reactions(event_type)]


def system_email(session: Session, group_id, event_type: str) -> tuple[bool, list]:
    """For an event with a system email (invitation, welcome): whether Marvin's own email sends in
    the workspace, and the workspace templates of its type that replace it — `_runs`, so the email template page
    and the event page always agree."""
    from marvin.services.email.system_email_events import get_template_type_for_event

    template_type = get_template_type_for_event(event_type)
    rows = _reaction_rows(session, group_id, event_type)
    runs = _runs([_facts(r) for r in rows], group_id)
    sends = any(ok for r, ok in zip(rows, runs, strict=True) if r.kind == "system_email")
    replacing = [r.template_id for r, ok in zip(rows, runs, strict=True) if ok and r.kind == "email" and r.template_type == template_type]
    return sends, list(dict.fromkeys(replacing))


def reactions(session: Session, group_id, event_type: str) -> list[EventReaction]:
    """Everything that reacts to `event_type` in the workspace: its workflows, integration actions, emails and
    webhooks (switched-off ones as enabled=False), then the built-in reactions."""
    rows = _reaction_rows(session, group_id, event_type)
    runs = _runs([_facts(r) for r in rows], group_id)
    return [*_sorted([_reaction(r, ok) for r, ok in zip(rows, runs, strict=True)]), *builtin(event_type)]


# ── senders ──────────────────────────────────────────────────────────────────


def _step_sends(step, subject: str = "entry") -> list[tuple[str, str]]:
    """(event type, what sends it) for one workflow step, when the step's kind and settings decide it. `subject`:
    what the workflow's steps act on without an entity_type (validation.subject_of) — an asset/resource target's
    rows or event's item, else an entry."""
    from marvin.services.automation.actions.entry import ITEM_OP_SENDS, ITEM_OPS, OP_SENDS
    from marvin.services.automation.actions.handler import AUTOMATION_ALLOWED_HANDLERS
    from marvin.services.events.event_catalog import EMITTABLE_EVENT_TYPES, canonical_event_type
    from marvin.services.scheduled_tasks.handlers import TaskHandlerRegistry

    if not isinstance(step, dict):
        return []
    kind = step.get("kind")
    emits = canonical_event_type(step["event"]) if kind == "emit_event" and isinstance(step.get("event"), str) else None
    if emits in EMITTABLE_EVENT_TYPES:  # anything else fails at run time
        return [(emits, "Emit event step")]
    if kind == "handler" and step.get("task") in AUTOMATION_ALLOWED_HANDLERS and TaskHandlerRegistry.is_registered(step["task"]):
        handler = TaskHandlerRegistry.get_handler(step["task"])
        return [(e, f"{handler.name} step") for e in handler.sends]
    item_op = (step.get("entity_type") or (subject if step.get("op") in ITEM_OPS else "entry"), step.get("op"))
    if kind == "entry" and item_op in ITEM_OP_SENDS:
        return [(e, f"Entry step: {step['op']} ({item_op[0]})") for e in ITEM_OP_SENDS[item_op]]
    if kind == "entry" and step.get("entity_type") in (None, "entry") and step.get("op") in OP_SENDS:
        return [(e, f"Entry step: {step['op'].replace('_', ' ')}") for e in OP_SENDS[step["op"]]]
    return []


def workflow_sends(definition: dict | None) -> dict[str, list[str]]:
    """{event type: [what sends it]} for a workflow's steps (and on-failure steps), as many as the engine runs."""
    from marvin.services.automation.engine import MAX_ACTIONS
    from marvin.services.automation.validation import subject_of

    body = definition or {}
    subject = subject_of(body)
    out: dict[str, list[str]] = defaultdict(list)
    for step in [*(body.get("actions") or [])[:MAX_ACTIONS], *(body.get("on_failure") or [])[:MAX_ACTIONS]]:
        for event_type, what in _step_sends(step, subject):
            if what not in out[event_type]:
                out[event_type].append(what)
    return dict(out)


def _installed_by(row, integrations: dict) -> InstalledBy | None:
    integration = integrations.get(row.source_integration_id) if row.source_integration_id else None
    if integration is None:
        return None
    return InstalledBy(integration_id=integration.id, name=integration.name, provider=integration.provider, blueprint=row.source_blueprint)


def _data_senders(session: Session, group_id) -> dict[str, list[EventSender]]:
    """{event type: senders} for the workspace's own rows — four queries whatever the number of types."""
    from marvin.db.models.groups.automations import WorkspaceAutomationModel as Workflow
    from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel as IncomingWebhook
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
    from marvin.services.scheduled_tasks.handlers import TaskHandlerRegistry

    out: dict[str, list[EventSender]] = defaultdict(list)
    integrations = {i.id: i for i in session.query(IntegrationModel).filter(IntegrationModel.group_id == group_id)}
    workflows = session.query(Workflow).filter(Workflow.group_id == group_id).order_by(Workflow.name).all()
    hooks = session.query(IncomingWebhook).filter(IncomingWebhook.group_id == group_id).order_by(IncomingWebhook.name).all()

    for hook in hooks:  # every incoming webhook sends incoming_webhook when its URL is called
        out["incoming_webhook"].append(
            EventSender(
                kind="incoming_webhook",
                id=hook.id,
                name=hook.name,
                enabled=bool(hook.enabled),
                detail="A call to its URL",
                managed_at="/automation/incoming-webhooks",
                installed_by=_installed_by(hook, integrations),
            )
        )

    for workflow in workflows:
        sends = workflow_sends(workflow.body)
        if not sends:
            continue
        # The incoming webhooks that start it (one hop): its slug, or any of them when it names none.
        starters = []
        if workflow.trigger_type == "incoming_webhook":
            ref = workflow.trigger_ref
            starters = [h for h in hooks if not ref or ref == "any" or h.slug == ref]
        for event_type, what in sends.items():
            out[event_type].append(
                EventSender(
                    kind="workflow",
                    id=workflow.id,
                    name=workflow.name,
                    enabled=bool(workflow.enabled),
                    detail="; ".join(what),
                    managed_at=f"/automation/workflows?workflow={workflow.id}",
                    installed_by=_installed_by(workflow, integrations),
                )
            )
            for hook in starters:
                out[event_type].append(
                    EventSender(
                        kind="incoming_webhook",
                        id=hook.id,
                        name=hook.name,
                        enabled=bool(hook.enabled and workflow.enabled),
                        detail=f"Starts the workflow {workflow.name}",
                        via_workflow_id=workflow.id,
                        via_workflow_name=workflow.name,
                        managed_at="/automation/incoming-webhooks",
                        installed_by=_installed_by(hook, integrations),
                    )
                )

    sending_types = {t for t in TaskHandlerRegistry.list_registered_types() if TaskHandlerRegistry.get_handler(t).sends}
    tasks = (
        session.query(ScheduledTaskModel)
        .filter(
            sa.or_(ScheduledTaskModel.group_id == group_id, ScheduledTaskModel.group_id.is_(None)),
            ScheduledTaskModel.task_type.in_(sorted(sending_types)),
        )
        .order_by(ScheduledTaskModel.name)
        .all()
        if sending_types
        else []
    )
    for task in tasks:
        handler = TaskHandlerRegistry.get_handler(task.task_type)
        system = task.group_id is None  # a system task covers every workspace
        for event_type in handler.sends:
            out[event_type].append(
                EventSender(
                    kind="scheduled_task",
                    id=task.id,
                    name=task.name,
                    enabled=bool(task.enabled),
                    detail="System task (every workspace)" if system else f"{handler.name} task",
                    managed_at=None if system else f"/workspace/scheduled-tasks/{task.id}",
                    installed_by=None if system else _installed_by(task, integrations),
                )
            )
    return out


def marvin_senders(entry: CatalogEntry) -> list[EventSender]:
    """The catalog's `sent_by` lines: what in Marvin's own code sends it."""
    return [EventSender(kind="marvin", name=line, enabled=True) for line in entry.sent_by]


def senders(session: Session, group_id, event_type: str) -> list[EventSender]:
    """What sends `event_type` in the workspace: Marvin itself, then its workflows, incoming webhooks and
    scheduled tasks."""
    entry = get_catalog_entry(event_type)
    own = marvin_senders(entry) if entry else []
    return [*own, *_data_senders(session, group_id).get(event_type, [])]


# ── recent, chain ────────────────────────────────────────────────────────────


class Recent(NamedTuple):
    events: list[EventLogSummary]
    audited: bool
    """Whether the workspace records the type: if not, no events is "not recorded", not "never happened"."""


def recent(session: Session, group_id, event_type: str, limit: int = 10, *, visible=None) -> Recent:
    """The newest Event Log rows of `event_type` in the workspace (platform events left out, as every workspace
    read of the log does). `visible`: the caller's visibility clause (services.ai.executions)."""
    from marvin.repos.platform.event_log import EventLogRepository
    from marvin.services.events.audit_settings import is_audited

    rows = EventLogRepository(session, group_id).get_by_workspace(workspace_id=group_id, event_type=event_type, limit=limit, visible=visible)
    return Recent([EventLogSummary.model_validate(r) for r in rows], is_audited(group_id, event_type))


def _ref(event_type: str) -> EventTypeRef:
    entry = get_catalog_entry(event_type)
    return EventTypeRef(event_type=event_type, name=entry.name if entry else event_type)


def leads_to(event_type: str) -> list[EventTypeRef]:
    entry = get_catalog_entry(event_type)
    return [_ref(t) for t in (entry.leads_to if entry else [])]


def caused_by(event_type: str) -> list[EventTypeRef]:
    return [_ref(e.event_type) for e in CATALOG if event_type in e.leads_to]


# ── the two reads the API serves ─────────────────────────────────────────────


def detail(session: Session, group_id, entry: CatalogEntry, *, limit: int = 10, visible=None) -> EventConnections:
    """One event type's whole story in the workspace."""
    event_type = entry.event_type
    latest = recent(session, group_id, event_type, limit, visible=visible)
    return EventConnections(
        event_type=event_type,
        name=entry.name,
        description=entry.description,
        category=entry.category,
        senders=senders(session, group_id, event_type),
        reactions=reactions(session, group_id, event_type),
        audited=latest.audited,
        recent=latest.events,
        leads_to=leads_to(event_type),
        caused_by=caused_by(event_type),
    )


@dataclass
class _Count:
    reactions: int = 0
    active: int = 0


def summary(session: Session, group_id, *, visible=None) -> list[EventConnectionCounts]:
    """Per workspace-scope event type (catalog order): how many senders and reactions it has, and when it last
    happened. A fixed number of queries, whatever the number of types: one grouped query for every stored
    reaction, one per sender source, one for the last occurrences."""
    from marvin.db.models.platform.event_log import EventLogModel
    from marvin.repos.platform.event_log import workspace_events_clause

    union = _reaction_union(group_id, None)
    facts_cols = [union.c[f] for f in _Facts._fields]
    grouped = session.execute(sa.select(*facts_cols, sa.func.count().label("n")).group_by(*facts_cols)).all()
    by_type: dict[str, list] = defaultdict(list)
    for row in grouped:
        by_type[row.event_type].append(row)
    counts: dict[str, _Count] = defaultdict(_Count)
    for event_type, rows in by_type.items():
        for row, ok in zip(rows, _runs([_facts(r) for r in rows], group_id), strict=True):
            counts[event_type].reactions += row.n
            counts[event_type].active += row.n if ok else 0

    data_senders = _data_senders(session, group_id)
    last_stmt = (
        sa.select(EventLogModel.event_type, sa.func.max(EventLogModel.occurred_at))
        .where(EventLogModel.workspace_id == group_id, workspace_events_clause())
        .group_by(EventLogModel.event_type)
    )
    if visible is not None:
        last_stmt = last_stmt.where(visible)
    last = dict(session.execute(last_stmt).all())

    return [
        EventConnectionCounts(
            event_type=e.event_type,
            name=e.name,
            category=e.category,
            senders=len(e.sent_by) + len(data_senders.get(e.event_type, [])),
            reactions=counts[e.event_type].reactions,
            active_reactions=counts[e.event_type].active,
            builtin_reactions=len(builtin(e.event_type)),
            last_occurred_at=last.get(e.event_type),
        )
        for e in CATALOG
        if e.scope == "workspace" and not e.hidden
    ]


def platform_detail(session: Session, entry: CatalogEntry) -> tuple[list[EventSender], list[EventReaction], list[WorkspaceEventReactions]]:
    """A platform event type's senders (Marvin's own: workflows can't send one, and no task type does), its
    platform-wide reactions (built in, plus the system email template it sends) and each workspace's own
    reactions to it — one query for all workspaces."""
    from marvin.db.models.groups.groups import Groups

    event_type = entry.event_type
    rows = _reaction_rows(session, None, event_type)
    system_rows = [r for r in rows if r.kind == "system_email"]
    by_group: dict[object, list] = defaultdict(list)
    for row in rows:
        if row.kind != "system_email":
            by_group[row.group_id].append(row)

    groups = {g.id: g for g in session.query(Groups).filter(Groups.id.in_(list(by_group)))} if by_group else {}
    workspaces = []
    for group_id, group_rows in by_group.items():
        runs = _runs([_facts(r) for r in [*group_rows, *system_rows]], group_id)[: len(group_rows)]
        group = groups.get(group_id)
        workspaces.append(
            WorkspaceEventReactions(
                workspace_id=group_id,
                workspace_name=group.name if group else None,
                workspace_slug=group.slug if group else None,
                reactions=_sorted([_reaction(r, ok) for r, ok in zip(group_rows, runs, strict=True)]),
            )
        )
    workspaces.sort(key=lambda w: ((w.workspace_name or "").lower(), str(w.workspace_id)))
    # The system template sends wherever a workspace hasn't connected its own: shown with its own switch.
    platform = [_reaction(r, bool(r.parent_enabled)) for r in system_rows]
    return marvin_senders(entry), [*platform, *builtin(event_type)], workspaces
