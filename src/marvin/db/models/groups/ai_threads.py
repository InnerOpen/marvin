"""
AI threads — server-side conversations with an agent.

A thread is the memory behind Ask: the messages the client used to replay from a JS array now live
here, so a conversation survives a reload, can be reopened, and — because a paused run has a row to
park on — an agent can stop mid-loop and ask the user before doing something (v2 "ask first").
Threads are owned by the user who started them (admins see every thread in the workspace).
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import NaiveDateTime
from .._model_utils.guid import GUID

__all__ = ["AIThreadMessageModel", "AIThreadModel"]

THREAD_STATUS_OPEN = "open"
THREAD_STATUS_AWAITING = "awaiting_approval"
THREAD_STATUS_ARCHIVED = "archived"


class AIThreadModel(SqlAlchemyBase, BaseMixins):
    __tablename__ = "ai_threads"
    # Listed as "this workspace, most recent first".
    __table_args__ = (sa.Index("ix_ai_threads_group_last_message", "group_id", "last_message_at"),)

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, ForeignKey("groups.id", ondelete="CASCADE"), index=True, nullable=False)
    agent_slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Optional grounding the thread was opened with (what the user was looking at).
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[GUID | None] = mapped_column(GUID, nullable=True)
    created_by: Mapped[GUID] = mapped_column(GUID, nullable=False, index=True)
    # A hand-off child: the specialist's thread opened from a router (marvin) thread. Hidden from the
    # default thread list; orphaned (SET NULL), not deleted, when the parent goes. No relationship —
    # the service looks children up by (parent, agent, user).
    parent_thread_id: Mapped[GUID | None] = mapped_column(
        GUID, ForeignKey("ai_threads.id", ondelete="SET NULL", name="fk_ai_threads_parent_thread_id"), nullable=True, index=True
    )
    # open | awaiting_approval | archived (32 wide: "awaiting_approval" alone is 17, see b2d5e8f1a3c4)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=THREAD_STATUS_OPEN)
    # A paused run waiting for the user's approval: everything needed to resume it (Slice C).
    # none_as_null so `pending_json IS NULL` is a real emptiness check (see sa-json-none-as-null).
    pending_json: Mapped[dict | None] = mapped_column(sa.JSON(none_as_null=True), nullable=True)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)
    # Not a column: the parent's title, filled in when the thread list includes hand-off children
    # (services/ai/threads.list_threads) so a child listed without its parent can still name it.
    parent_title = None

    messages: Mapped[list[AIThreadMessageModel]] = orm.relationship(
        "AIThreadMessageModel",
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="AIThreadMessageModel.seq",
    )

    @auto_init()
    def __init__(self, session: Session, **_) -> None:
        pass


class AIThreadMessageModel(SqlAlchemyBase, BaseMixins):
    __tablename__ = "ai_thread_messages"
    __table_args__ = (sa.Index("ix_ai_thread_messages_thread_seq", "thread_id", "seq"),)

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    thread_id: Mapped[GUID] = mapped_column(GUID, ForeignKey("ai_threads.id", ondelete="CASCADE"), nullable=False)
    group_id: Mapped[GUID] = mapped_column(GUID, nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    # Tool trace of the assistant turn: [{tool, arguments, result}] (results truncated; names only
    # when the workspace does not log outputs).
    steps_json: Mapped[list | None] = mapped_column(sa.JSON, nullable=True)
    # {sources: [{entityType, entityId, title}], totalTokens, handoffs?: [{agent, threadId, executionId}],
    #  referrals?: [{agent, name, question, reason}]}
    meta_json: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    execution_id: Mapped[GUID | None] = mapped_column(GUID, nullable=True)

    thread: Mapped[AIThreadModel] = orm.relationship("AIThreadModel", back_populates="messages")

    @auto_init()
    def __init__(self, session: Session, **_) -> None:
        pass
