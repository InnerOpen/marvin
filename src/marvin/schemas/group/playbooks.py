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


class PlaybookCopiedFrom(_MarvinModel):
    """A Playbook made by copying a system Playbook (``metadata_json["copiedFrom"]``)."""

    name: str
    """The system Playbook it was copied from."""
    label: str = ""
    version: str = ""
    """The version it was copied at."""
    current_version: str | None = None
    """The installed version of that system Playbook now; None when it is gone."""
    upstream_changed: bool = False
    """The system Playbook changed since the copy was made (or last marked as seen). A hint only: nothing is merged."""


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
    copied_from: PlaybookCopiedFrom | None = None
    """Set on a copy of a system Playbook."""


class PlaybookUse(_MarvinModel):
    execution_id: UUID4
    agent_slug: str | None = None
    agent_name: str | None = None
    used_at: datetime | None = None
    thread_id: UUID4 | None = None
    """The Ask conversation the run belongs to, when it has one: what a person can open."""


class PlaybookFileText(_MarvinModel):
    path: str
    size: int = 0
    text: str | None = None
    """The file's text (cut at 20,000 characters, see ``truncated``); None when it is not a text file."""
    truncated: bool = False
    error: str | None = None
    """Why the text isn't here (not a text file, too large, unreadable)."""


class PlaybookFiles(_MarvinModel):
    items: list[PlaybookFileText] = Field(default_factory=list)


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


class SystemPlaybookItem(_MarvinModel):
    """A system Playbook as this workspace sees it (the Playbooks page's System section)."""

    name: str
    description: str = ""
    label: str
    """Where it comes from: "System · Marvin", "System · Social", "System · <plugin>"."""
    version: str = ""
    manual_only: bool = True
    allowed_tools: str = ""
    state: str
    """"on" | "off" (this workspace switched it off) | "off_server" (the platform did) | "hidden" (a Playbook of yours has its name)
    | "replaced" (your published copy stands in for it)."""
    detail: str = ""
    """The sentence for a state other than "on"."""
    enabled: bool = True
    """Whether this workspace's own switch is on (it can be on while the platform's is off)."""
    suggested_copy_name: str = ""
    """What Copy proposes as the name (the name without its prefix), when that is free."""
    file_count: int = 0


class SystemPlaybookList(_MarvinModel):
    items: list[SystemPlaybookItem] = Field(default_factory=list)


class SystemPlaybookFile(_MarvinModel):
    path: str
    text: str


class SystemPlaybookRead(SystemPlaybookItem):
    """One system Playbook in full, read-only."""

    source: str = "core"
    """"core" (Marvin's own folder) or "plugin"."""
    fingerprint: str = ""
    """A fingerprint of the text and files: it changes when the Playbook does (what a copy compares against)."""
    body: str = ""
    files: list[SystemPlaybookFile] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SystemPlaybookSwitch(_MarvinModel):
    enabled: bool


class SystemPlaybookCopy(_MarvinModel):
    name: str | None = None
    """The copy's name; the suggestion (the name without its prefix) when omitted. 409 when taken."""
