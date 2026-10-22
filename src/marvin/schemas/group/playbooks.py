"""The Playbooks page's API (routes/groups/playbooks_controller.py): the workspace's Playbooks with their status."""

from datetime import datetime
from typing import Any

from pydantic import UUID4, Field

from marvin.schemas._marvin import _MarvinModel


class PlaybookOrigin(_MarvinModel):
    """An integration's Playbook: which integration shipped it (``metadata_json["installedBy"]``)."""

    source: str
    """The provider's slug (``buttondown``)."""
    name: str
    """The provider's name for display; its slug when the plugin is not installed."""
    integration_id: UUID4 | None = None
    """The workspace's connection of that provider; None once it was removed."""
    removed: bool = False
    """True when that integration is gone from this workspace: the Playbook stays (a published one keeps working)."""


class PlaybookItem(_MarvinModel):
    id: UUID4
    name: str
    description: str = ""
    status: str
    manual_only: bool = False
    updated_at: datetime | None = None
    last_used_at: datetime | None = None
    """When an agent last loaded it (None: not lately, or never)."""
    from_integration: PlaybookOrigin | None = None
    """Set when an integration shipped this Playbook and the workspace added it from the integration's card."""


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


class PlaybookGithubImport(_MarvinModel):
    url: str
    """A public github.com link to a skill folder (``…/tree/<branch>/<folder>``), a ``SKILL.md`` (``…/blob/…``) or a repository root."""
    name: str | None = None
    """A new name when the skill's own is already taken."""


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
