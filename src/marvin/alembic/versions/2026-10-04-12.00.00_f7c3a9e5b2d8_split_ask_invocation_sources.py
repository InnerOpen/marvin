"""ai settings: split the Ask invocation source into bubble + ask_page

The single "Ask {assistant}" toggle (`agent`) becomes two: `bubble` (the floating bubble) and
`ask_page` (the Ask page and named agents). A stored `agent: false` becomes `bubble: false,
ask_page: false` and the `agent` key is dropped: the settings page no longer shows it, so a kept
`agent: false` would hold both surfaces off behind toggles that read "on". `agent: true` is the
default and is just dropped. Data only — no schema change.

Downgrade folds them back: `agent: false` when either surface is off (never re-enables one).

Revision ID: f7c3a9e5b2d8
Revises: e6b2d8f4a1c7
Create Date: 2026-10-04 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types as mt

# revision identifiers, used by Alembic.
revision: str = "f7c3a9e5b2d8"
down_revision: str | None = "e6b2d8f4a1c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_KEY = "agent"
SURFACE_KEYS = ("bubble", "ask_page")


def split_agent(policy: dict) -> dict | None:
    """The policy with `agent` replaced by the two surfaces, or None when there is nothing to change."""
    if LEGACY_KEY not in policy:
        return None
    out = {k: v for k, v in policy.items() if k != LEGACY_KEY}
    if policy[LEGACY_KEY] is False:
        out.update(dict.fromkeys(SURFACE_KEYS, False))
    return out


def join_surfaces(policy: dict) -> dict | None:
    """The policy with the two surfaces folded back into `agent`, or None when there is nothing to change."""
    if not any(k in policy for k in SURFACE_KEYS):
        return None
    out = {k: v for k, v in policy.items() if k not in SURFACE_KEYS}
    if any(policy.get(k) is False for k in SURFACE_KEYS):
        out[LEGACY_KEY] = False
    return out


def _settings():
    return sa.table(
        "workspace_ai_settings",
        sa.column("id", mt.GUID()),
        sa.column("invocation_sources", sa.JSON()),
    )


def _rewrite(transform) -> None:
    table = _settings()
    conn = op.get_bind()
    rows = conn.execute(sa.select(table.c.id, table.c.invocation_sources).where(table.c.invocation_sources.isnot(None))).all()
    for row_id, policy in rows:
        if not isinstance(policy, dict):
            continue
        new = transform(policy)
        if new is not None:
            conn.execute(table.update().where(table.c.id == row_id).values(invocation_sources=new))


def upgrade() -> None:
    _rewrite(split_agent)


def downgrade() -> None:
    _rewrite(join_surfaces)
