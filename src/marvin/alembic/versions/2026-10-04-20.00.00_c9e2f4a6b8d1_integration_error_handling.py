"""integration error handling

Integration-owned error handling: a provider declares how each of its error codes is handled
(review, retry, notify, succeed) and the core applies it.

  - ``integration_retries``  — a failed workflow step waiting to be retried (or holding partial progress)
  - ``integration_alerts``   — a connection that needs attention, one open row per integration + code
  - ``automation_action_executions.handling`` — how the policy handled a failed step
  - ``automation_executions.handled`` / ``retry_of_id`` — the run was taken care of / the run it retried
  - ``group_preferences.integration_alert_reminder_hours`` — when an open alert is announced again (24)
  - ``integrations.error_overrides`` — an admin's per-connection review/notify adjustments to the policy

Additive — safe on Postgres and SQLite.

Revision ID: c9e2f4a6b8d1
Revises: b3f7c2e9d1a4
Create Date: 2026-10-04 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types as mt

# revision identifiers, used by Alembic.
revision: str = "c9e2f4a6b8d1"
down_revision: str | None = "b3f7c2e9d1a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("automation_executions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("handled", sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column("retry_of_id", mt.GUID(), nullable=True))
        batch_op.create_index("ix_automation_executions_retry_of_id", ["retry_of_id"])
        batch_op.create_foreign_key("fk_automation_executions_retry_of_id", "automation_executions", ["retry_of_id"], ["id"], ondelete="SET NULL")
    with op.batch_alter_table("automation_action_executions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("handling", sa.JSON(none_as_null=True), nullable=True))
    with op.batch_alter_table("group_preferences", schema=None) as batch_op:
        batch_op.add_column(sa.Column("integration_alert_reminder_hours", sa.Integer(), server_default="24", nullable=False))
    with op.batch_alter_table("integrations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("error_overrides", sa.JSON(none_as_null=True), nullable=True))

    op.create_table(
        "integration_retries",
        sa.Column("id", mt.GUID(), nullable=False),
        sa.Column("group_id", mt.GUID(), nullable=False),
        sa.Column("automation_id", mt.GUID(), nullable=False),
        sa.Column("integration_id", mt.GUID(), nullable=True),
        sa.Column("entry_id", mt.GUID(), nullable=True),
        sa.Column("integration_slug", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("codes", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("live_key", sa.String(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("handle", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("snapshot", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("partial", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("idempotency_seed", sa.String(), nullable=False),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("origin_execution_id", mt.GUID(), nullable=True),
        sa.Column("last_execution_id", mt.GUID(), nullable=True),
        sa.Column("created_at", mt.NaiveDateTime(), nullable=True),
        sa.Column("update_at", mt.NaiveDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["automation_id"], ["workspace_automations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["integration_id"], ["integrations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["origin_execution_id"], ["automation_executions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["last_execution_id"], ["automation_executions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "live_key", name="uq_integration_retries_live"),
    )
    # entry_id has no foreign key on purpose: a retry must outlive its entry (its facts are in `snapshot`).
    for column in ("group_id", "automation_id", "integration_id", "entry_id", "status", "next_attempt_at", "origin_execution_id", "created_at"):
        op.create_index(f"ix_integration_retries_{column}", "integration_retries", [column])

    op.create_table(
        "integration_alerts",
        sa.Column("id", mt.GUID(), nullable=False),
        sa.Column("group_id", mt.GUID(), nullable=False),
        sa.Column("integration_id", mt.GUID(), nullable=False),
        sa.Column("integration_slug", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("open_key", sa.String(), nullable=True),
        sa.Column("message", sa.String(), nullable=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("first_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("samples", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("channels", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", mt.GUID(), nullable=True),
        sa.Column("resolution", sa.String(), nullable=True),
        sa.Column("created_at", mt.NaiveDateTime(), nullable=True),
        sa.Column("update_at", mt.NaiveDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["integration_id"], ["integrations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "open_key", name="uq_integration_alerts_open"),
    )
    for column in ("group_id", "integration_id", "status", "created_at"):
        op.create_index(f"ix_integration_alerts_{column}", "integration_alerts", [column])


def downgrade() -> None:
    for column in ("created_at", "status", "integration_id", "group_id"):
        op.drop_index(f"ix_integration_alerts_{column}", table_name="integration_alerts")
    op.drop_table("integration_alerts")
    for column in ("created_at", "origin_execution_id", "next_attempt_at", "status", "entry_id", "integration_id", "automation_id", "group_id"):
        op.drop_index(f"ix_integration_retries_{column}", table_name="integration_retries")
    op.drop_table("integration_retries")

    with op.batch_alter_table("integrations", schema=None) as batch_op:
        batch_op.drop_column("error_overrides")
    with op.batch_alter_table("group_preferences", schema=None) as batch_op:
        batch_op.drop_column("integration_alert_reminder_hours")
    with op.batch_alter_table("automation_action_executions", schema=None) as batch_op:
        batch_op.drop_column("handling")
    with op.batch_alter_table("automation_executions", schema=None) as batch_op:
        batch_op.drop_constraint("fk_automation_executions_retry_of_id", type_="foreignkey")
        batch_op.drop_index("ix_automation_executions_retry_of_id")
        batch_op.drop_column("retry_of_id")
        batch_op.drop_column("handled")
