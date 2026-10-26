"""The Social Battery's meter: how a character feels about one person, per workspace and agent (services/ai/mood.py).

One row per (workspace, person, agent). ``level`` is 0–100 and starts at 50; ``state`` keeps what the scoring rules
need to look back on (the recent message times, a few message fingerprints for repeats, the last signals) and nothing
about the person beyond that. A person can reset it ("Reset our relationship"); ``reset_at`` says when they last did.
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import NaiveDateTime
from .._model_utils.guid import GUID

__all__ = ["AIMoodMeterModel"]

MOOD_START = 50


class AIMoodMeterModel(SqlAlchemyBase, BaseMixins):
    __tablename__ = "ai_mood_meters"
    __table_args__ = (sa.UniqueConstraint("group_id", "user_id", "agent_slug", name="uq_ai_mood_meters_person_agent"),)

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_slug: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    level: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=MOOD_START, server_default=str(MOOD_START))
    """0–100: how the character feels about this person right now."""
    band_since: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    """``{"band", "at"}``: the band the level is in and when it got there — a first message in a new band gets a milestone aside."""
    state: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    """``{"messages": [iso…], "texts": [fingerprint…], "signals": [{"kind", "delta", "at"}…]}`` — the recent past the rules read."""
    last_seen_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)
    """When the person last wrote to this agent (UTC): drift and absences are measured from it."""
    reset_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
