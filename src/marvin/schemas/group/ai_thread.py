"""Schemas for Ask threads (see db/models/groups/ai_threads.py and services/ai/threads.py)."""

from datetime import datetime
from typing import Literal

from pydantic import UUID4, ConfigDict, Field

from marvin.schemas._marvin import _MarvinModel


class AIThreadMessageRead(_MarvinModel):
    id: UUID4
    seq: int
    role: str
    content: str
    steps_json: list | None = None
    meta_json: dict | None = None
    execution_id: UUID4 | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class AIThreadRead(_MarvinModel):
    id: UUID4
    agent_slug: str
    title: str | None = None
    entity_type: str | None = None
    entity_id: UUID4 | None = None
    created_by: UUID4
    parent_thread_id: UUID4 | None = None  # set on a hand-off child (see ?children=true)
    parent_title: str | None = None  # the parent's title, on a child listed with ?children=true
    status: str
    total_tokens: int = 0
    last_message_at: datetime | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class AIThreadDetail(AIThreadRead):
    messages: list[AIThreadMessageRead] = []
    # Calls waiting for the user's decision (ask-first): [{id, tool, arguments, preview?}] — `preview` lists a
    # big bulk write's targets × items (services/ai/tools/bulk_writes.py). A specialist's ask carried up
    # through a hand-off is flattened in: id `c1/c7`, plus `via`, `viaName`, `viaChain`, `childThreadId`.
    pending: list[dict] = []
    # On a parked specialist's thread: the conversation its decision is taken on (resuming here forwards
    # there, and the answer is that conversation's). None on a root or an open thread.
    root_thread_id: UUID4 | None = None


class AIThreadUpdate(_MarvinModel):
    title: str | None = Field(default=None, max_length=200)

    model_config = ConfigDict(from_attributes=True)


class AIThreadResumeRequest(_MarvinModel):
    """Decide the calls a paused run is waiting on. Missing ids count as denied."""

    decisions: dict[str, Literal["approve", "deny"]] = {}
    client_run_id: str | None = None  # live steps for the resumed run, as on a run
    # invocation surface resuming it (the Ask page sends "ask_page", the bubble "bubble"); gated by workspace policy
    source: str = "agent"

    model_config = ConfigDict(from_attributes=True)
