"""The migrated `webhookmode` enum covers every WebhookMode.

On Postgres the enum type is created by the migrations, not the model, so a value added to WebhookMode
needs its own `ALTER TYPE … ADD VALUE` migration. `workflow` was missing: saving a workflow-type webhook
failed on Postgres. SQLite stores the column as text, so there it's only the round trip that's checked.
"""

import uuid

import pytest
import sqlalchemy as sa

from marvin.db.db_setup import engine
from marvin.db.models.groups import Groups
from marvin.db.models.groups.webhooks import GroupWebhooksModel
from marvin.services.event_bus_service.event_types import WebhookMode


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="the enum type exists only on Postgres")
def test_postgres_enum_has_every_webhook_mode(db_session):
    rows = db_session.execute(
        sa.text("SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid WHERE t.typname = 'webhookmode'")
    ).all()
    assert {r[0] for r in rows} >= {m.value for m in WebhookMode}


def test_every_webhook_mode_saves(db_session):
    gid = uuid.uuid4()
    group = Groups(session=db_session, name=f"wm-{gid.hex[:8]}", slug=f"wm-{gid.hex[:8]}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    try:
        for mode in WebhookMode:
            hook = GroupWebhooksModel(
                session=db_session, group_id=gid, name=f"hook {mode.value}", url="https://example.invalid/hook", webhook_type=mode
            )
            db_session.add(hook)
        db_session.commit()
        saved = {h.webhook_type for h in db_session.query(GroupWebhooksModel).filter_by(group_id=gid)}
        assert saved == set(WebhookMode)
    finally:
        db_session.rollback()
        db_session.query(GroupWebhooksModel).filter_by(group_id=gid).delete()
        db_session.query(Groups).filter(Groups.id == gid).delete()
        db_session.commit()
