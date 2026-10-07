"""The cc5204b9dfc1 data migration: live reset and invitation links scrubbed from what the Event Log and the webhook
execution logs stored before the events stopped carrying them.

The redaction is checked as a pure function, then the upgrade is run against a scratch SQLite database with just the
columns it touches, so the row rewrite itself is exercised.
"""

import importlib.util
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

import marvin.db.migration_types as mt

_PATH = next((Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions").glob("*_cc5204b9dfc1_*.py"))
_spec = importlib.util.spec_from_file_location("redact_event_secrets", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)

RESET = "https://marvin.test/reset-password/?token=RESET-SECRET"
INVITE = "https://marvin.test/register?token=INVITE-SECRET"


def _event(document: dict) -> dict:
    return {"message": {"title": "t", "body": "b"}, "eventType": "x", "documentData": {"documentType": "user", **document}}


def test_secret_keys_and_link_tokens_are_redacted_everything_else_kept():
    stored = _event({"email": "a@b.test", "resetUrl": RESET, "username": "a"})
    assert mig.redact(stored) == _event({"email": "a@b.test", "resetUrl": "[redacted]", "username": "a"})

    stored = _event({"invitationToken": "INVITE-SECRET", "invitationUrl": INVITE, "workspaceName": "W", "usesLeft": 3})
    assert mig.redact(stored) == _event({"invitationToken": "[redacted]", "invitationUrl": "[redacted]", "workspaceName": "W", "usesLeft": 3})

    # A link inside free text (a webhook's custom payload) loses its token, wherever it sits.
    body = {"meta": {"text": f"Reset here: {RESET} or join {INVITE}&ref=x"}, "list": [INVITE]}
    clean = mig.redact(body)
    assert "SECRET" not in str(clean)
    assert clean["meta"]["text"].endswith("register?token=[redacted]&ref=x") and clean["list"] == ["https://marvin.test/register?token=[redacted]"]

    untouched = _event({"entryId": "e", "url": "https://marvin.test/entries?token_count=3", "invitationToken": None})
    assert mig.redact(untouched) == untouched


@pytest.fixture
def scratch():
    """An in-memory DB with just the columns the migration touches, and an alembic op bound to it."""
    engine = sa.create_engine("sqlite://")
    meta = sa.MetaData()
    events = sa.Table(
        "event_log",
        meta,
        sa.Column("id", mt.GUID(), primary_key=True),
        sa.Column("event_type", sa.String()),
        sa.Column("event_data", sa.JSON(), nullable=False),
    )
    logs = sa.Table(
        "webhook_execution_logs", meta, sa.Column("id", mt.GUID(), primary_key=True), sa.Column("request_payload", sa.JSON(), nullable=True)
    )
    meta.create_all(engine)
    with engine.begin() as conn:
        ops = Operations(MigrationContext.configure(conn))
        original = mig.op
        mig.op = ops
        try:
            yield conn, events, logs
        finally:
            mig.op = original


def test_upgrade_scrubs_stored_events_and_webhook_bodies(scratch):
    conn, events, logs = scratch
    rows = {
        "reset": ("user_password_reset_requested", _event({"email": "a@b.test", "resetUrl": RESET})),
        "invite": ("invitation_sent", _event({"invitationToken": "INVITE-SECRET", "invitationUrl": INVITE})),
        "other": ("entry_published", _event({"entryId": "e"})),
    }
    ids = {k: uuid.uuid4() for k in rows}
    conn.execute(events.insert(), [{"id": ids[k], "event_type": t, "event_data": d} for k, (t, d) in rows.items()])
    hook_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    bodies = [rows["reset"][1], {"meta": {"note": INVITE}}, None]
    conn.execute(logs.insert(), [{"id": i, "request_payload": b} for i, b in zip(hook_ids, bodies, strict=True)])

    mig.upgrade()

    stored = dict(conn.execute(sa.select(events.c.id, events.c.event_data)).all())
    assert "SECRET" not in str(stored)
    assert stored[ids["reset"]]["documentData"] == {"documentType": "user", "email": "a@b.test", "resetUrl": "[redacted]"}
    assert stored[ids["other"]] == rows["other"][1]
    sent = dict(conn.execute(sa.select(logs.c.id, logs.c.request_payload)).all())
    assert "SECRET" not in str(sent) and sent[hook_ids[2]] is None

    mig.downgrade()  # a no-op: nothing comes back
    assert "SECRET" not in str(dict(conn.execute(sa.select(events.c.id, events.c.event_data)).all()))
