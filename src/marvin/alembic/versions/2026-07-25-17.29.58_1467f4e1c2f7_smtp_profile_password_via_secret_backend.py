"""smtp profile password via secret backend

Moves the SMTP password off the bespoke `password_encrypted` column and behind the secret backend,
referenced by `secret_ref` (same pattern as integrations). The database secret backend uses the same
Fernet key, so an existing ciphertext moves into a `workspace_secrets` row verbatim — no decrypt.

Revision ID: 1467f4e1c2f7
Revises: a79fa1345639
Create Date: 2026-07-25 17:29:58.957446

"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types as mt
from marvin.db.models.groups.smtp_profiles import smtp_secret_ref

# revision identifiers, used by Alembic.
revision: str = "1467f4e1c2f7"
down_revision: str | None = "a79fa1345639"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _profiles_table():
    return sa.table(
        "workspace_smtp_profiles",
        sa.column("id", mt.GUID()),
        sa.column("group_id", mt.GUID()),
        sa.column("name", sa.String()),
        sa.column("password_encrypted", sa.Text()),
        sa.column("secret_ref", sa.String()),
    )


def _secrets_table():
    return sa.table(
        "workspace_secrets",
        sa.column("id", mt.GUID()),
        sa.column("group_id", mt.GUID()),
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
        sa.column("description", sa.String()),
        sa.column("encrypted_value", sa.Text()),
    )


def upgrade() -> None:
    with op.batch_alter_table("workspace_smtp_profiles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("secret_ref", sa.String(), nullable=True))

    bind = op.get_bind()
    profiles, secrets = _profiles_table(), _secrets_table()
    rows = bind.execute(
        sa.select(profiles.c.id, profiles.c.group_id, profiles.c.name, profiles.c.password_encrypted).where(
            profiles.c.password_encrypted.isnot(None)
        )
    ).fetchall()
    for row in rows:
        ref = smtp_secret_ref(row.id)
        bind.execute(
            secrets.insert().values(
                id=uuid.uuid4(),
                group_id=row.group_id,
                name=f"SMTP password · {row.name}",
                slug=ref,
                description="Migrated from the SMTP profile password.",
                encrypted_value=row.password_encrypted,
            )
        )
        bind.execute(profiles.update().where(profiles.c.id == row.id).values(secret_ref=ref))

    with op.batch_alter_table("workspace_smtp_profiles", schema=None) as batch_op:
        batch_op.drop_column("password_encrypted")


def downgrade() -> None:
    with op.batch_alter_table("workspace_smtp_profiles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("password_encrypted", sa.Text(), nullable=True))

    bind = op.get_bind()
    profiles, secrets = _profiles_table(), _secrets_table()
    rows = bind.execute(sa.select(profiles.c.id, profiles.c.group_id, profiles.c.secret_ref).where(profiles.c.secret_ref.isnot(None))).fetchall()
    for row in rows:
        ref = smtp_secret_ref(row.id)
        # Only pull back the profile's own managed secret; a user-referenced secret stays put.
        if row.secret_ref != ref:
            continue
        sec = bind.execute(
            sa.select(secrets.c.id, secrets.c.encrypted_value).where(secrets.c.group_id == row.group_id, secrets.c.slug == ref)
        ).first()
        if sec is not None:
            bind.execute(profiles.update().where(profiles.c.id == row.id).values(password_encrypted=sec.encrypted_value))
            bind.execute(secrets.delete().where(secrets.c.id == sec.id))

    with op.batch_alter_table("workspace_smtp_profiles", schema=None) as batch_op:
        batch_op.drop_column("secret_ref")
