"""backup runs: one row per run of a backup target, for Admin → Backup health and its alerts

``backup_runs`` is written by the backup CronJob at the end of each run (plain DB-API, see
services/backup_engine/recorder.py) and by the backend's health check (``missed`` rows). Never a
credential: location, non-secret settings, sizes, counts and a scrubbed error summary.

Additive — safe on Postgres and SQLite.

Revision ID: 59d0896537fa
Revises: 4e1b9c7a2d55
Create Date: 2026-10-07 12:59:18.841623
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types as mt

# revision identifiers, used by Alembic.
revision: str = "59d0896537fa"
down_revision: str | None = "4e1b9c7a2d55"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backup_runs",
        sa.Column("id", mt.GUID(), nullable=False),
        sa.Column("target_name", sa.String(length=63), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", mt.NaiveDateTime(), nullable=False),
        sa.Column("finished_at", mt.NaiveDateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("schedule", sa.String(length=64), nullable=True),
        sa.Column("time_zone", sa.String(length=64), nullable=True),
        sa.Column("keep_hourly", sa.Integer(), nullable=True),
        sa.Column("keep_daily", sa.Integer(), nullable=True),
        sa.Column("keep_weekly", sa.Integer(), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("settings_json", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("db_engine", sa.String(length=16), nullable=True),
        sa.Column("db_key", sa.String(length=255), nullable=True),
        sa.Column("db_bytes", sa.BigInteger(), nullable=True),
        sa.Column("db_gz_bytes", sa.BigInteger(), nullable=True),
        sa.Column("config_items", sa.Integer(), nullable=True),
        sa.Column("assets_uploaded", sa.Integer(), nullable=True),
        sa.Column("assets_uploaded_bytes", sa.BigInteger(), nullable=True),
        sa.Column("assets_unchanged", sa.Integer(), nullable=True),
        sa.Column("pruned", sa.Integer(), nullable=True),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("host", sa.String(length=63), nullable=True),
        sa.Column("notified_at", mt.NaiveDateTime(), nullable=True),
        sa.Column("created_at", mt.NaiveDateTime(), nullable=True),
        sa.Column("update_at", mt.NaiveDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("backup_runs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_backup_runs_created_at"), ["created_at"], unique=False)
        batch_op.create_index("ix_backup_runs_target_started", ["target_name", "started_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("backup_runs", schema=None) as batch_op:
        batch_op.drop_index("ix_backup_runs_target_started")
        batch_op.drop_index(batch_op.f("ix_backup_runs_created_at"))

    op.drop_table("backup_runs")
