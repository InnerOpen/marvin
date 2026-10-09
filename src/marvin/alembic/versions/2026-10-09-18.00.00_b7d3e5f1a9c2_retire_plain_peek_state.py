"""bubble characters: retire the plain `peek` state

A tucked bubble peeks with the animation for its edge (`peek_left`, `peek_right`, `peek_top`, `peek_bottom`);
the single `peek` slot is gone from the picker and from services/ai/character.py's states, which now refuse
it as unknown. This removes `peek` from every stored character's states — library packs, workspaces' and
agents' own — so a character saved back isn't refused for it. Its file stays in the file list, unassigned.
Data only; safe on Postgres and SQLite. Not reversed: a retired state has nothing to play it.

Revision ID: b7d3e5f1a9c2
Revises: a6c2f19d4e70
Create Date: 2026-10-09 18:00:00.000000

"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d3e5f1a9c2"
down_revision: str | None = "a6c2f19d4e70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RETIRED = "peek"
COLUMNS = (("character_packs", "pack"), ("workspace_ai_settings", "assistant_character"), ("workspace_agents", "character"))


def _without_retired(value):
    """The character with RETIRED out of its states, or None when there's nothing to change."""
    character = json.loads(value) if isinstance(value, str) else value
    if not isinstance(character, dict) or not isinstance(character.get("states"), dict) or RETIRED not in character["states"]:
        return None
    return {**character, "states": {k: v for k, v in character["states"].items() if k != RETIRED}}


def upgrade() -> None:
    bind = op.get_bind()
    for table, column in COLUMNS:
        rows = bind.execute(sa.text(f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL")).fetchall()  # noqa: S608 - fixed names
        for row_id, value in rows:
            changed = _without_retired(value)
            if changed is not None:
                statement = sa.text(f"UPDATE {table} SET {column} = :value WHERE id = :id").bindparams(sa.bindparam("value", type_=sa.JSON))  # noqa: S608
                bind.execute(statement, {"value": changed, "id": row_id})


def downgrade() -> None:
    pass
