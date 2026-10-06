"""events storage: webhook subscriptions table, workflow trigger columns

Two "who listens to what" facts move out of JSON so they can be joined (Events hub, slice 1):

* ``webhook_urls.subscribed_events`` (a JSON list) → one ``webhook_event_subscriptions`` row per
  (webhook, event type), the same shape as ``email_event_subscriptions`` and
  ``integration_event_subscriptions``. NULL, ``[]`` and duplicates all collapse to "these distinct
  event types"; entries that aren't non-empty strings are dropped (nothing could ever match them).
  The column is then dropped. The API still reads and writes ``subscribedEvents``.
* ``workspace_automations.definition.trigger`` → ``trigger_type`` / ``trigger_event`` /
  ``trigger_ref`` / ``trigger_config``, and ``definition`` keeps the rest (conditions, actions, …).
  ``trigger_event`` is the event the trigger listens to — its own ``event`` for an event trigger,
  ``incoming_webhook`` / ``automation_ran`` / ``automation_failed`` for the incoming-webhook / chained /
  on-error types, NULL for manual / schedule / mcp. ``trigger_ref`` is the incoming webhook slug or
  the chained / on-error target workflow. Keys the columns don't model (a schedule's
  ``schedule_type``/``schedule_config``, anything extra) are kept verbatim in ``trigger_config``.
  A trigger without ``type`` (the old ``{"event": X}`` shape) is stored as an event trigger, so it
  comes back with ``"type": "event"``; a workflow with no trigger keeps ``trigger_type`` NULL.
  The API still accepts and returns ``definition.trigger``.

The split/assemble logic is copied here on purpose (see ``WorkspaceAutomationModel``): a migration
must not change meaning when the model code moves on.

Downgrade restores both JSON shapes from the new storage: ``subscribed_events`` as the sorted list
(``[]`` when a webhook has none) and ``definition.trigger`` as the API returns it.

Revision ID: cba7c23b692e
Revises: e6c2a9f4b1d3
Create Date: 2026-10-06 11:03:15.996163

"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types as mt

# revision identifiers, used by Alembic.
revision: str = "cba7c23b692e"
down_revision: str | None = "e6c2a9f4b1d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TYPE_EVENTS = {"incoming_webhook": "incoming_webhook", "chained": "automation_ran", "on_error": "automation_failed"}
_REF_KEYS = {"incoming_webhook": "webhook", "chained": "automation", "on_error": "automation"}


def _split_trigger(trigger) -> dict:
    if not isinstance(trigger, dict):
        return {"trigger_type": None, "trigger_event": None, "trigger_ref": None, "trigger_config": None}
    rest = dict(trigger)
    ttype = rest.pop("type", None) or "event"
    event = ref = None
    if ttype == "event":
        if isinstance(rest.get("event"), str) or rest.get("event") is None:
            event = rest.pop("event", None)
    elif ttype in _TYPE_EVENTS:
        event = _TYPE_EVENTS[ttype]
        key = _REF_KEYS[ttype]
        if isinstance(rest.get(key), str) or rest.get(key) is None:
            ref = rest.pop(key, None)
    return {"trigger_type": ttype, "trigger_event": event, "trigger_ref": ref, "trigger_config": rest or None}


def _assemble_trigger(ttype, event, ref, config) -> dict | None:
    if ttype is None:
        return None
    trigger: dict = {"type": ttype}
    if ttype == "event" and event is not None:
        trigger["event"] = event
    if ttype in _REF_KEYS and ref is not None:
        trigger[_REF_KEYS[ttype]] = ref
    trigger.update(config or {})
    return trigger


def _webhooks(with_events: bool):
    cols = [sa.column("id", mt.GUID())]
    if with_events:
        cols.append(sa.column("subscribed_events", sa.JSON()))
    return sa.table("webhook_urls", *cols)


def _subscriptions():
    return sa.table(
        "webhook_event_subscriptions",
        sa.column("id", mt.GUID()),
        sa.column("webhook_id", mt.GUID()),
        sa.column("event_type", sa.String()),
        sa.column("created_at", mt.NaiveDateTime()),
        sa.column("update_at", mt.NaiveDateTime()),
    )


def _automations(with_trigger_columns: bool):
    cols = [sa.column("id", mt.GUID()), sa.column("definition", sa.JSON())]
    if with_trigger_columns:
        cols += [
            sa.column("trigger_type", sa.String()),
            sa.column("trigger_event", sa.String()),
            sa.column("trigger_ref", sa.String()),
            sa.column("trigger_config", sa.JSON(none_as_null=True)),
        ]
    return sa.table("workspace_automations", *cols)


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(UTC).replace(tzinfo=None)

    # ── webhooks: JSON list → rows ──────────────────────────────────────────
    # Read first, drop the column, then insert: the batch rebuild of webhook_urls happens before the
    # new child table holds anything.
    webhooks = _webhooks(with_events=True)
    subscribed = {row.id: row.subscribed_events for row in bind.execute(sa.select(webhooks.c.id, webhooks.c.subscribed_events))}
    with op.batch_alter_table("webhook_urls", schema=None) as batch_op:
        batch_op.drop_column("subscribed_events")

    op.create_table(
        "webhook_event_subscriptions",
        sa.Column("id", mt.GUID(), nullable=False),
        sa.Column("webhook_id", mt.GUID(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("created_at", mt.NaiveDateTime(), nullable=True),
        sa.Column("update_at", mt.NaiveDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["webhook_id"], ["webhook_urls.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("webhook_id", "event_type", name="uq_webhook_event_subscriptions_webhook_event"),
    )
    with op.batch_alter_table("webhook_event_subscriptions", schema=None) as batch_op:
        batch_op.create_index("ix_webhook_event_subscriptions_created_at", ["created_at"], unique=False)
        batch_op.create_index("ix_webhook_event_subscriptions_event_type", ["event_type"], unique=False)

    rows = []
    for webhook_id, events in subscribed.items():
        if not isinstance(events, list):
            continue
        for event_type in dict.fromkeys(e for e in events if isinstance(e, str) and e):
            rows.append({"id": uuid.uuid4(), "webhook_id": webhook_id, "event_type": event_type, "created_at": now, "update_at": now})
    if rows:
        op.bulk_insert(_subscriptions(), rows)

    # ── workflows: definition.trigger → columns ─────────────────────────────
    with op.batch_alter_table("workspace_automations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("trigger_type", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("trigger_event", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("trigger_ref", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("trigger_config", sa.JSON(none_as_null=True), nullable=True))
        batch_op.create_index("ix_workspace_automations_trigger_event", ["trigger_event"], unique=False)

    automations = _automations(with_trigger_columns=True)
    for row in bind.execute(sa.select(automations.c.id, automations.c.definition)).fetchall():
        definition = row.definition
        if not isinstance(definition, dict):
            continue  # no definition (or not an object): no trigger to move
        columns = _split_trigger(definition.get("trigger"))
        body = {k: v for k, v in definition.items() if k != "trigger"}
        bind.execute(automations.update().where(automations.c.id == row.id).values(definition=body, **columns))


def downgrade() -> None:
    bind = op.get_bind()

    # ── workflows: columns → definition.trigger ─────────────────────────────
    automations = _automations(with_trigger_columns=True)
    for row in bind.execute(
        sa.select(
            automations.c.id,
            automations.c.definition,
            automations.c.trigger_type,
            automations.c.trigger_event,
            automations.c.trigger_ref,
            automations.c.trigger_config,
        )
    ).fetchall():
        trigger = _assemble_trigger(row.trigger_type, row.trigger_event, row.trigger_ref, row.trigger_config)
        if trigger is None:
            continue
        definition = {"trigger": trigger, **(row.definition if isinstance(row.definition, dict) else {})}
        bind.execute(automations.update().where(automations.c.id == row.id).values(definition=definition))

    with op.batch_alter_table("workspace_automations", schema=None) as batch_op:
        batch_op.drop_index("ix_workspace_automations_trigger_event")
        batch_op.drop_column("trigger_config")
        batch_op.drop_column("trigger_ref")
        batch_op.drop_column("trigger_event")
        batch_op.drop_column("trigger_type")

    # ── webhooks: rows → JSON list ──────────────────────────────────────────
    subs = _subscriptions()
    events: dict = {}
    for row in bind.execute(sa.select(subs.c.webhook_id, subs.c.event_type).order_by(subs.c.event_type)):
        events.setdefault(row.webhook_id, []).append(row.event_type)

    with op.batch_alter_table("webhook_urls", schema=None) as batch_op:
        batch_op.add_column(sa.Column("subscribed_events", sa.JSON(), nullable=True))
    webhooks = _webhooks(with_events=True)
    for (webhook_id,) in bind.execute(sa.select(webhooks.c.id)).fetchall():
        bind.execute(webhooks.update().where(webhooks.c.id == webhook_id).values(subscribed_events=events.get(webhook_id, [])))

    with op.batch_alter_table("webhook_event_subscriptions", schema=None) as batch_op:
        batch_op.drop_index("ix_webhook_event_subscriptions_event_type")
        batch_op.drop_index("ix_webhook_event_subscriptions_created_at")
    op.drop_table("webhook_event_subscriptions")
