"""Package schemas: a named, versioned bundle of blueprints, as one JSON file.

A *package* groups what belongs together (a "Brand kit" package: its entry types, its workflows) so it can be installed, shown as one
collapsed section on the Workflows page, downloaded and uploaded. It is a list of ordinary `Blueprint`s (`schemas/platform/blueprints.py`),
applied with the same rules: create what is missing, never overwrite what exists, and everything that acts when on starts disabled.

A package file comes from outside, so it is checked harder than a blueprint the code ships: only the kinds that are plain workspace
content, a size cap, no ids that belong to another workspace, and no secret values (a secret is named by a `{{NAME}}` reference).
"""

import re
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from marvin.schemas._marvin import _MarvinModel
from marvin.schemas.platform.blueprints import CORE_SOURCE, Blueprint, BlueprintApplyResult

#: Kinds a package may carry: workspace content. Not `playbook` (it commits as it applies and brings files) and not `event_subscription`
#: (it wires one existing connection, so it cannot travel).
PACKAGEABLE_KINDS = ("entry_type", "entry_fields", "collection", "workflow", "scheduled_task", "incoming_webhook")

MAX_BLUEPRINTS = 200
MAX_MANIFEST_BYTES = 2_000_000

PACKAGE_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
#: A key that holds a credential. Its value may only be a reference (`{{NAME}}` or `${...}`), never the secret itself.
_SECRET_KEY = re.compile(r"^(password|passwd|token|secret|api[_-]?key|private[_-]?key|client[_-]?secret|authorization)$", re.IGNORECASE)
_REFERENCE = re.compile(r"^\s*(\{\{[^}]+\}\}|\$\{[^}]+\})\s*$")


def content_problems(value: Any, path: str = "") -> list[str]:
    """What in this content must not travel in a package: another workspace's ids, and secret values. `path` says where, for the message."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            where = f"{path}.{key}" if path else str(key)
            if _SECRET_KEY.match(str(key)) and isinstance(item, str) and item.strip() and not _REFERENCE.match(item):
                found.append(f"{where} holds a secret value: name a workspace secret with {{{{NAME}}}} instead")
            else:
                found.extend(content_problems(item, where))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            found.extend(content_problems(item, f"{path}[{i}]"))
    elif isinstance(value, str) and _UUID.search(value):
        found.append(f"{path} contains an id ({_UUID.search(value).group(0)[:8]}…) that belongs to one workspace: refer to things by slug")
    return found


class PackageManifest(_MarvinModel):
    """The file: what a package is and the blueprints it brings."""

    format: Literal[1] = 1
    """Version of this file layout, so a later change can be told apart."""

    slug: Annotated[str, StringConstraints(strip_whitespace=True)]
    """Identifies the package in a workspace; lower-case letters, digits and hyphens. Installing the same slug again adds what is missing."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    """The group label: the heading of its section on the Workflows page."""

    description: str = ""
    version: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)] = "1"

    blueprints: list[Blueprint] = Field(min_length=1, max_length=MAX_BLUEPRINTS)

    @field_validator("slug")
    @classmethod
    def _slug_shape(cls, value: str) -> str:
        if not PACKAGE_SLUG.match(value):
            raise ValueError("slug is lower-case letters, digits and hyphens, starting with a letter or digit (up to 64)")
        return value

    @model_validator(mode="after")
    def _only_content_that_travels(self):
        seen: set[tuple[str, str]] = set()
        problems: list[str] = []
        for blueprint in self.blueprints:
            if blueprint.kind not in PACKAGEABLE_KINDS:
                problems.append(f"{blueprint.kind} '{blueprint.slug}': a package carries {', '.join(PACKAGEABLE_KINDS)}, not {blueprint.kind}")
            key = (blueprint.kind, blueprint.slug)
            if key in seen:
                problems.append(f"{blueprint.kind} '{blueprint.slug}' is listed twice")
            seen.add(key)
            problems.extend(f"{blueprint.kind} '{blueprint.slug}': {p}" for p in content_problems(blueprint.payload, "payload"))
        if problems:
            raise ValueError("; ".join(problems[:8]) + (f" (and {len(problems) - 8} more)" if len(problems) > 8 else ""))
        # A file cannot name an integration as its source: that would link what it creates to a connection it has no right to claim.
        self.blueprints = [b if b.source == CORE_SOURCE else b.model_copy(update={"source": CORE_SOURCE}) for b in self.blueprints]
        return self


class PackageItem(_MarvinModel):
    """One blueprint's outcome in a preview or an install."""

    slug: str
    kind: str
    name: str = ""
    status: Literal["create", "created", "exists", "blocked"]
    """`create`: a preview, it would be made. `created`: it was. `exists`: already here, left exactly as it is.
    `blocked`: it could not be made (see `detail`)."""
    detail: str = ""
    summary: str = ""
    """For a workflow: when it runs and what it does, in a line, so the person installing can read what they are switching on."""


class PackageResult(_MarvinModel):
    package: str
    name: str
    items: list[PackageItem]
    created: int = 0
    existing: int = 0
    blocked: int = 0


class PackageRead(_MarvinModel):
    """An installed package, with what it holds in this workspace."""

    slug: str
    name: str
    description: str = ""
    version: str = "1"
    entry_types: list[str] = Field(default_factory=list)
    """Slugs of the entry types it brings (these carry no marker; the manifest is the record)."""
    workflows: int = 0
    workflows_on: int = 0
    collections: int = 0
    scheduled_tasks: int = 0
    incoming_webhooks: int = 0


class PackageExportRequest(_MarvinModel):
    """What to bundle from this workspace's own content."""

    slug: str
    name: str
    description: str = ""
    version: str = "1"
    workflows: list[str] = Field(default_factory=list)
    """Workflow slugs."""
    entry_types: list[str] = Field(default_factory=list)
    collections: list[str] = Field(default_factory=list)
    adopt: bool = False
    """Also group the chosen workflows and collections into the package here (nothing is recreated), and keep the manifest
    so it can be downloaded again."""


class PackageEnableResult(_MarvinModel):
    switched_on: int
    already_on: int


__all__ = [
    "PACKAGEABLE_KINDS",
    "MAX_MANIFEST_BYTES",
    "BlueprintApplyResult",
    "PackageEnableResult",
    "PackageExportRequest",
    "PackageItem",
    "PackageManifest",
    "PackageRead",
    "PackageResult",
    "content_problems",
]
