"""Blueprint schemas — declarative descriptions of workspace structure.

A *blueprint* says "here is a collection / entry type / scheduled task a workspace could have",
without creating anything. Core ships a catalog of them; integration providers contribute their own
(a provider may only ever *declare* — the SDK forbids it touching the database). One schema, three
consumers: the catalog a user browses, what an integration brings on install, and what the agent
offers to create.

Applying a blueprint is an upsert by slug that **creates what is missing and never overwrites what
exists** — a workspace may have customised its copy, and a blueprint is a starting point, not a
template the workspace is held to.
"""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator

from marvin.schemas._marvin import _MarvinModel

BlueprintKind = Literal["collection", "entry_type", "scheduled_task"]

#: `requires` entries look like "entry_type:bench-note" — a blueprint that references content the
#: workspace does not have is surfaced as unavailable rather than applied into a broken state.
REQUIREMENT_KINDS = ("entry_type", "collection")

CORE_SOURCE = "core"


class Blueprint(_MarvinModel):
    """One thing a workspace could create, described rather than created."""

    kind: BlueprintKind
    """What this blueprint builds."""

    slug: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    """Slug the created object gets, and the key the upsert dedupes on."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    """Human label, shown in the catalog."""

    description: str = ""
    """One line on what it is for — this is the discoverability, so it earns its place."""

    category: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = "General"
    """Groups the catalog. Core uses editorial/workflow-style categories; a provider's blueprints
    are filed under that provider so the catalog stays legible as providers multiply."""

    source: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = CORE_SOURCE
    """`core`, or the slug of the provider that contributed it."""

    requires: list[str] = Field(default_factory=list)
    """Prerequisites as `kind:slug`, e.g. `entry_type:bench-note`. Checked before offering."""

    payload: dict = Field(default_factory=dict)
    """The body handed to the creating repository — a CollectionCreate / EntryTypes /
    ScheduledTaskCreate shape, minus the workspace scoping the core adds."""

    @field_validator("requires")
    @classmethod
    def _validate_requires(cls, value: list[str]) -> list[str]:
        for req in value:
            kind, _, slug = req.partition(":")
            if kind not in REQUIREMENT_KINDS or not slug:
                raise ValueError(f"requirement must be '<{'|'.join(REQUIREMENT_KINDS)}>:<slug>', got {req!r}")
        return value

    @field_validator("payload")
    @classmethod
    def _payload_carries_no_scope(cls, value: dict) -> dict:
        # Scoping is the core's job. A blueprint that carried its own group_id could be applied into
        # the wrong workspace, so refuse the shape outright rather than silently dropping the key.
        for forbidden in ("group_id", "id"):
            if forbidden in value:
                raise ValueError(f"payload must not set {forbidden!r} — the workspace is supplied when the blueprint is applied")
        return value


class BlueprintRead(Blueprint):
    """A catalog entry as the API returns it, with what this workspace can do about it."""

    available: bool = True
    """False when `requires` is unmet — shown, but not applicable."""

    missing_requirements: list[str] = Field(default_factory=list)
    """The unmet entries from `requires`, so the UI can say what is needed."""

    applied: bool = False
    """True when this workspace already has something with that slug — applying again is a no-op."""


class BlueprintApplyResult(_MarvinModel):
    """What applying one blueprint did."""

    slug: str
    kind: BlueprintKind
    created: bool
    """False when it already existed; the existing object is left exactly as it was."""

    detail: str = ""
    """Why nothing was created, when nothing was."""
