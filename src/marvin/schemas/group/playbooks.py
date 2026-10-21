"""The Playbooks page's API (routes/groups/playbooks_controller.py): the workspace's Playbooks with their status."""

from datetime import datetime
from typing import Any

from pydantic import UUID4, Field

from marvin.schemas._marvin import _MarvinModel


class PlaybookItem(_MarvinModel):
    id: UUID4
    name: str
    description: str = ""
    status: str
    manual_only: bool = False
    updated_at: datetime | None = None
    last_used_at: datetime | None = None
    """When an agent last loaded it (None: not lately, or never)."""


class PlaybookUse(_MarvinModel):
    execution_id: UUID4
    agent_slug: str | None = None
    agent_name: str | None = None
    used_at: datetime | None = None
    thread_id: UUID4 | None = None
    """The Ask conversation the run belongs to, when it has one: what a person can open."""


class PlaybookUses(_MarvinModel):
    items: list[PlaybookUse] = Field(default_factory=list)


class PlaybookList(_MarvinModel):
    entry_type_id: UUID4 | None = None
    """The ``playbook`` entry type, None until the first Playbook is written (reading never creates it)."""
    items: list[PlaybookItem] = Field(default_factory=list)


class PlaybookType(_MarvinModel):
    entry_type_id: UUID4


class PlaybookImported(_MarvinModel):
    """What an import made: the draft's id and name, how many reference files it kept, and the review of what it asks for."""

    id: UUID4
    name: str
    status: str
    file_count: int = 0
    skipped: list[dict[str, Any]] = Field(default_factory=list)
    """Files left out, each ``{path, reason}``."""
    review: dict[str, Any]
    """The findings (services/playbooks/importer.py ``review_package``); camelCase keys, also stored on the entry's metadata."""
