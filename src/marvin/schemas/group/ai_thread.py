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
    status: str
    total_tokens: int = 0
    last_message_at: datetime | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class AIThreadDetail(AIThreadRead):
    messages: list[AIThreadMessageRead] = []
    # Calls waiting for the user's decision (ask-first): [{id, tool, arguments}]
    pending: list[dict] = []


class AIThreadUpdate(_MarvinModel):
    title: str | None = Field(default=None, max_length=200)

    model_config = ConfigDict(from_attributes=True)


class AIThreadResumeRequest(_MarvinModel):
    """Decide the calls a paused run is waiting on. Missing ids count as denied."""

    decisions: dict[str, Literal["approve", "deny"]] = {}
    client_run_id: str | None = None  # live steps for the resumed run, as on a run

    model_config = ConfigDict(from_attributes=True)
