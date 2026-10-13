"""drop the built-in Apprise notifier tables

The built-in Apprise notifier is gone; Apprise notifications are the ``apprise`` integration
(marvin-integration-apprise), and e49ab4346b7b already mirrored any notifiers onto it. Drops:

  - ``notification_execution_logs``   (per-notifier delivery log)
  - ``group_events_notifier_options`` (a notifier's subscribed events)
  - ``group_events_notifiers``        (the notifiers: name + Apprise URL)
  - ``events_notifier_options``       (the global event catalog the notifiers subscribed against;
                                       webhooks, email and integrations key on event_type strings
                                       from the code catalog and never read it)

Downgrade recreates the tables empty, with the shape the initial schema gave them — the dropped
rows (unused in production at the time of removal) are not restored.

Revision ID: b3f7c2e9d1a4
Revises: a8d4b0f6c3e9
Create Date: 2026-10-04 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types as mt

# revision identifiers, used by Alembic.
revision: str = "b3f7c2e9d1a4"
down_revision: str | None = "a8d4b0f6c3e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Indexed columns per table, matching the initial schema's ix_<table>_<column> names.
INDEXES = {
    "notification_execution_logs": ("created_at", "event_type", "executed_at", "group_id", "notifier_id", "status"),
    "group_events_notifier_options": ("created_at", "group_event_notifiers_id"),
    "group_events_notifiers": ("created_at", "group_id"),
    "events_notifier_options": ("created_at",),
}
# Children before parents.
DROP_ORDER = ("notification_execution_logs", "group_events_notifier_options", "group_events_notifiers", "events_notifier_options")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", mt.NaiveDateTime(), nullable=True),
        sa.Column("update_at", mt.NaiveDateTime(), nullable=True),
    ]


def upgrade() -> None:
    for table in DROP_ORDER:
        with op.batch_alter_table(table, schema=None) as batch_op:
            for column in INDEXES[table]:
                batch_op.drop_index(batch_op.f(f"ix_{table}_{column}"))
        op.drop_table(table)


def _create_indexes(table: str) -> None:
    with op.batch_alter_table(table, schema=None) as batch_op:
        for column in INDEXES[table]:
            batch_op.create_index(batch_op.f(f"ix_{table}_{column}"), [column], unique=False)


def downgrade() -> None:
    op.create_table(
        "events_notifier_options",
        sa.Column("id", mt.GUID(), nullable=False),
        sa.Column("namespace", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    _create_indexes("events_notifier_options")

    op.create_table(
        "group_events_notifiers",
        sa.Column("id", mt.GUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("apprise_url", sa.String(), nullable=False),
        sa.Column("group_id", mt.GUID(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_indexes("group_events_notifiers")

    op.create_table(
        "group_events_notifier_options",
        sa.Column("id", mt.GUID(), nullable=False),
        sa.Column("namespace", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("group_event_notifiers_id", mt.GUID(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["group_event_notifiers_id"], ["group_events_notifiers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_indexes("group_events_notifier_options")

    op.create_table(
        "notification_execution_logs",
        sa.Column("id", mt.GUID(), nullable=False),
        sa.Column("notifier_id", mt.GUID(), nullable=False),
        sa.Column("group_id", mt.GUID(), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("request_payload", sa.JSON(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["notifier_id"], ["group_events_notifiers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_indexes("notification_execution_logs")
