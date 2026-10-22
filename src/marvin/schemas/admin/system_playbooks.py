"""Schemas for the platform's system Playbooks (admin: /api/admin/system-playbooks)."""

from pydantic import Field

from marvin.schemas._marvin import _MarvinModel


class AdminSystemPlaybook(_MarvinModel):
    name: str
    description: str = ""
    label: str
    """"System · Marvin", "System · Social", "System · <plugin>"."""
    source: str
    """"core" or "plugin"."""
    version: str = ""
    manual_only: bool = True
    allowed_tools: str = ""
    """Set when the Playbook narrows an agent's tools while loaded (rarely right; shown so an admin sees it)."""
    warnings: list[str] = Field(default_factory=list)
    files: int = 0
    server_off: bool = False
    """The platform switch: off in every workspace."""
    workspaces_off: int = 0
    """How many workspaces switched it off themselves."""


class AdminSystemPlaybookSkipped(_MarvinModel):
    name: str
    label: str
    reason: str


class AdminSystemPlaybooks(_MarvinModel):
    items: list[AdminSystemPlaybook] = Field(default_factory=list)
    skipped: list[AdminSystemPlaybookSkipped] = Field(default_factory=list)
    """What could not be loaded (a bad name, a script, over the caps, a name another source already holds), each with the reason."""


class AdminSystemPlaybookSwitch(_MarvinModel):
    enabled: bool
