"""event secrets: redact password-reset and invitation links from the Event Log and webhook execution logs

`user_password_reset_requested` carried the live reset URL, and the `invitation_*` events the live invitation token
and URL. Each event was stored in `event_log.event_data` (any workspace member reads an event's payload) and posted
to subscribed webhooks, whose bodies `webhook_execution_logs.request_payload` keeps. The events no longer carry them
(the emails are sent directly); this scrubs what was stored: those keys' values become "[redacted]", and so does the
token in any reset or registration link left in a string. Data only — no schema change.

Not reversible: the downgrade leaves the rows as they are (a redacted secret can't be put back, and shouldn't be).

Revision ID: cc5204b9dfc1
Revises: 8d2f6a1c4e93
Create Date: 2026-10-07 19:00:00.000000

"""

import re
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types as mt

# revision identifiers, used by Alembic.
revision: str = "cc5204b9dfc1"
down_revision: str | None = "8d2f6a1c4e93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REDACTED = "[redacted]"
# The payload keys that held a live link or token, as stored (camelCase, by alias) and as an older writer may have.
SECRET_KEYS = frozenset({"resetUrl", "reset_url", "invitationToken", "invitation_token", "invitationUrl", "invitation_url"})
# A reset or registration link's token, wherever a link ended up in a string (a webhook's custom payload, a message).
LINK_TOKEN = re.compile(r"(/(?:reset-password|register)/?\?(?:[^\s\"'#]*&)?token=)[^&\s\"'#]+")
# The only event types whose payload carried one.
EVENT_TYPES = (
    "user_password_reset_requested",
    "invitation_created",
    "invitation_sent",
    "invitation_accepted",
    "invitation_revoked",
)


def redact(value: Any) -> Any:
    """`value` with every secret key's value and every link token replaced by "[redacted]"."""
    if isinstance(value, dict):
        return {k: (REDACTED if k in SECRET_KEYS and value[k] not in (None, "") else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return LINK_TOKEN.sub(rf"\g<1>{REDACTED}", value)
    return value


def _scrub(table: sa.Table, column: str, where) -> int:
    conn = op.get_bind()
    col = table.c[column]
    changed = 0
    for row_id, data in conn.execute(sa.select(table.c.id, col).where(col.isnot(None), where)).all():
        clean = redact(data)
        if clean != data:
            conn.execute(table.update().where(table.c.id == row_id).values({column: clean}))
            changed += 1
    return changed


def upgrade() -> None:
    event_log = sa.table("event_log", sa.column("id", mt.GUID()), sa.column("event_type", sa.String()), sa.column("event_data", sa.JSON()))
    _scrub(event_log, "event_data", event_log.c.event_type.in_(EVENT_TYPES))

    # A webhook body has no event type of its own: look only at those that mention a token at all.
    logs = sa.table("webhook_execution_logs", sa.column("id", mt.GUID()), sa.column("request_payload", sa.JSON()))
    _scrub(logs, "request_payload", sa.func.lower(sa.cast(logs.c.request_payload, sa.Text)).like("%token%"))


def downgrade() -> None:
    pass  # a redacted secret stays redacted
