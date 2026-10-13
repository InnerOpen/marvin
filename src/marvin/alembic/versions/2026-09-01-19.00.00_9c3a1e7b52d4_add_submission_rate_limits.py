"""add submission_rate_limits table

Subject-keyed rate limiting for public submissions to submittable entry types (generalizes
form_rate_limits off the forms.id FK). Additive CREATE TABLE — safe on Postgres and SQLite.

Revision ID: 9c3a1e7b52d4
Revises: e4ede8d3bfc3
Create Date: 2026-09-01 19:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = '9c3a1e7b52d4'
down_revision: str | None = 'e4ede8d3bfc3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'submission_rate_limits',
        sa.Column('id', marvin.db.migration_types.GUID(), nullable=False),
        sa.Column('subject_id', marvin.db.migration_types.GUID(), nullable=False),
        sa.Column('identifier', sa.String(), nullable=False),
        sa.Column('window_start', marvin.db.migration_types.NaiveDateTime(), nullable=False),
        sa.Column('submission_count', sa.Integer(), server_default='1', nullable=False),
        sa.Column('created_at', marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.Column('update_at', marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('subject_id', 'identifier', 'window_start', name='uq_submission_rate_limit_window'),
    )
    op.create_index('ix_submission_rate_limits_subject_id', 'submission_rate_limits', ['subject_id'])
    op.create_index('ix_submission_rate_limits_window_start', 'submission_rate_limits', ['window_start'])
    op.create_index(
        'ix_submission_rate_limits_subject_identifier', 'submission_rate_limits', ['subject_id', 'identifier']
    )


def downgrade() -> None:
    op.drop_index('ix_submission_rate_limits_subject_identifier', table_name='submission_rate_limits')
    op.drop_index('ix_submission_rate_limits_window_start', table_name='submission_rate_limits')
    op.drop_index('ix_submission_rate_limits_subject_id', table_name='submission_rate_limits')
    op.drop_table('submission_rate_limits')
