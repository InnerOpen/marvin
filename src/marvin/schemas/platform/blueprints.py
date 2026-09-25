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

BlueprintKind = Literal["collection", "entry_type", "scheduled_task", "event_subscription"]

#: Kinds that wire up one *connection* rather than workspace content: they reference an integration
#: instance, so applying one needs to know which. The integration's own card supplies it.
PER_INTEGRATION_KINDS = ("event_subscription",)

#: Kinds that *do* something once switched on — send, fire, open an endpoint. They are always created
#: disabled: applying a blueprint gives you the wiring, turning it on stays a deliberate second act.
ACTS_WHEN_ENABLED_KINDS = ("scheduled_task", "event_subscription")

#: What a parameter asks for. `entry_type`/`collection` render as a picker fed by the workspace's
#: own content and are validated against it — that is how a blueprint stays general without ever
#: naming someone's content model.
ParameterKind = Literal["entry_type", "collection", "text", "number"]

#: `requires` entries look like "entry_type:<slug>" — a blueprint that references content the
#: workspace does not have is surfaced as unavailable rather than applied into a broken state.
REQUIREMENT_KINDS = ("entry_type", "collection")

CORE_SOURCE = "core"


class BlueprintParameter(_MarvinModel):
    """Something the workspace supplies when the blueprint is applied.

    A blueprint that hardcoded an entry-type slug would only be useful to whoever happened to name
    a type that way. A parameter asks instead: the catalog can demonstrate `entry_types` rules
    without presuming what anyone calls their content.
    """

    key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    """Referenced as `{{key}}` in the blueprint's slug, name, description and payload."""

    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    """What the UI asks."""

    kind: ParameterKind = "text"
    """`entry_type`/`collection` are pickers validated against the workspace; the rest are free input."""

    required: bool = True
    default: str | None = None
    help: str = ""


class Blueprint(_MarvinModel):
    """One thing a workspace could create, described rather than created."""

    kind: BlueprintKind
    """What this blueprint builds."""

    slug: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    """Slug the created object gets, and the key the upsert dedupes on.

    An `event_subscription` has no slug of its own in the database, so there this is only the
    catalog identity — that upsert dedupes on (integration, event type, action) instead.
    """

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    """Human label, shown in the catalog."""

    description: str = ""
    """One line on what it is for — this is the discoverability, so it earns its place."""

    required: bool = False
    """True only when the source genuinely cannot work without it — an entry type an action reads or
    writes. Everything else is a suggestion the workspace may take or leave, and the two are listed
    separately: calling a preference a requirement tells someone their integration is broken when it
    is not. Core catalog blueprints are always suggestions."""

    category: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = "General"
    """Groups the catalog. Core uses editorial/workflow-style categories; a provider's blueprints
    are filed under that provider so the catalog stays legible as providers multiply."""

    source: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = CORE_SOURCE
    """`core`, or the slug of the provider that contributed it."""

    requires: list[str] = Field(default_factory=list)
    """Prerequisites as `kind:slug`. Mostly for provider bundles, where one blueprint genuinely
    depends on another the same provider brings; core blueprints ask via `parameters` instead."""

    parameters: list[BlueprintParameter] = Field(default_factory=list)
    """What the workspace fills in at apply time. `{{key}}` placeholders are substituted through
    the slug, name, description and payload."""

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
    """True when this workspace already has something with that slug — applying again is a no-op.
    Always False for a parameterised blueprint: its slug is not known until the parameters are."""


class BlueprintApplyResult(_MarvinModel):
    """What applying one blueprint did."""

    slug: str
    kind: BlueprintKind
    created: bool
    """False when it already existed; the existing object is left exactly as it was."""

    detail: str = ""
    """Why nothing was created, when nothing was."""

    name: str = ""
    """The created object's name, after parameter substitution."""
