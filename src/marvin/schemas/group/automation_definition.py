"""The ONE structural declaration of a Flavor B automation ``definition``.

Until now the ``definition`` was a raw, unvalidated ``dict`` at every layer — the API schema, the DB
column, and the engine — with a parallel hand-authored TypeScript interface in the SDK as a second,
drift-prone source of truth, and *zero* structure validation on create/update (any dict persisted).

This module makes a Pydantic **discriminated union** that single declaration:

  * triggers discriminate on ``type`` (event / manual / schedule / chained / on_error /
    incoming_webhook / mcp),
  * actions discriminate on ``kind`` (operation / entry / emit_event / handler / webhook) — one model
    per registered executor, its previously-implicit ``action.get(...)`` reads now typed fields,
  * conditions are a recursive leaf-or-group,
  * plus the optional target selector.

From it fall out: structural validation at the write boundary (see ``services/automation/validation``)
and a JSON Schema advertised by ``/api/automations/options`` that the builder + SDK mirror.

Two deliberate departures from the rest of Marvin's API models:

  * **snake_case, not camelCase.** The engine reads the stored definition by exact snake_case key
    (``action.get("entity_slug")``, ``trig.get("event")``), so — unlike ``_MarvinModel`` with its
    ``camelize`` alias — these models keep field names verbatim. They validate the definition; they do
    NOT re-serialize it (storage keeps the raw dict), so the engine is untouched.
  * **``extra="allow"``.** Validation gates the *shape it knows* (discriminators, required fields,
    types) but never rejects an unknown extra key, so advanced or forward-compatible definitions still
    save. The semantic "this won't match anything" checks stay advisory (``validation.py``).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _DefnBase(BaseModel):
    # snake_case verbatim (no camelize), lenient on unknown keys, accept field name or alias.
    model_config = ConfigDict(extra="allow", populate_by_name=True)


# ── Triggers (discriminated on `type`) ────────────────────────────────────────
class EventTrigger(_DefnBase):
    type: Literal["event"] = "event"
    event: str


class ManualTrigger(_DefnBase):
    type: Literal["manual"]


class ScheduleTrigger(_DefnBase):
    type: Literal["schedule"]
    schedule_type: str | None = None
    schedule_config: dict[str, Any] | None = None


class ChainedTrigger(_DefnBase):
    type: Literal["chained"]
    automation: str | None = None  # target automation (slug/id); None/"any" = every automation


class OnErrorTrigger(_DefnBase):
    type: Literal["on_error"]
    automation: str | None = None


class IncomingWebhookTrigger(_DefnBase):
    type: Literal["incoming_webhook"]
    webhook: str | None = None  # target incoming-webhook slug; None/"any" = any webhook


class McpTrigger(_DefnBase):
    type: Literal["mcp"]


# kind literal → model, so the union and the drift test both read from one place.
TRIGGER_MODELS: dict[str, type[_DefnBase]] = {
    "event": EventTrigger,
    "manual": ManualTrigger,
    "schedule": ScheduleTrigger,
    "chained": ChainedTrigger,
    "on_error": OnErrorTrigger,
    "incoming_webhook": IncomingWebhookTrigger,
    "mcp": McpTrigger,
}

Trigger = Annotated[
    EventTrigger | ManualTrigger | ScheduleTrigger | ChainedTrigger | OnErrorTrigger | IncomingWebhookTrigger | McpTrigger,
    Field(discriminator="type"),
]


# ── Actions (discriminated on `kind`) — one model per registered executor ──────
class OperationAction(_DefnBase):
    kind: Literal["operation"]
    op: str  # AI operation slug
    input: dict[str, Any] = Field(default_factory=dict)
    entity_type: str = "entry"
    entity_id: str | None = None  # defaults to $event.entry_id at run time
    entity_slug: str | None = None  # preferred for webhook payloads; resolved at run time
    write_back: bool = False
    id: str | None = None  # addressable as $steps.<id>.output.*


class EntryAction(_DefnBase):
    kind: Literal["entry"]
    op: Literal["publish", "unpublish", "archive", "restore", "add_to_collection", "remove_from_collection", "set_metadata"]
    entity_id: str | None = None
    entity_slug: str | None = None
    collection_id: str | None = None  # for add_to_collection / remove_from_collection…
    collection_slug: str | None = None  # …preferred: a collection slug/name (may be a $event.* template)
    metadata: dict[str, Any] | None = None  # for set_metadata: keys merged into metadata_json (values may be templates)
    id: str | None = None


class EmitEventAction(_DefnBase):
    kind: Literal["emit_event"]
    event: str  # internal event name to re-emit
    entity_id: str | None = None
    id: str | None = None


class HandlerAction(_DefnBase):
    kind: Literal["handler"]
    task: str  # allowlisted scheduled-task handler
    config: dict[str, Any] = Field(default_factory=dict)
    id: str | None = None


class WebhookAction(_DefnBase):
    kind: Literal["webhook"]
    webhook_id: str | None = None  # a configured workspace webhook…
    url: str | None = None  # …or (advanced) a raw url
    body: dict[str, Any] = Field(default_factory=dict)
    secret_ref: str | None = None  # optional secret ref, sent as `Authorization: <auth_scheme> <secret>`
    auth_scheme: str | None = None  # Bearer (default) | Token | … — some APIs (Buttondown) reject Bearer
    id: str | None = None


ACTION_MODELS: dict[str, type[_DefnBase]] = {
    "operation": OperationAction,
    "entry": EntryAction,
    "emit_event": EmitEventAction,
    "handler": HandlerAction,
    "webhook": WebhookAction,
}

Action = Annotated[
    OperationAction | EntryAction | EmitEventAction | HandlerAction | WebhookAction,
    Field(discriminator="kind"),
]


# ── Conditions (recursive: a leaf {field, op, value} OR a group {all|any|not}) ─
class Condition(_DefnBase):
    # Leaf:
    field: str | None = None
    op: str | None = None
    value: Any = None
    # Group (nestable; `not` is a Python keyword → aliased):
    all: list[Condition] | None = None
    any: list[Condition] | None = None
    not_: Condition | None = Field(default=None, alias="not")


# ── Target selector (the "FROM" clause) ───────────────────────────────────────
class Target(_DefnBase):
    entity: str = "entry"
    query: dict[str, Any] = Field(default_factory=dict)


# ── The whole definition ──────────────────────────────────────────────────────
class AutomationDefinition(_DefnBase):
    trigger: Trigger | None = None
    target: Target | None = None
    # A top-level list is an implicit AND; a single group dict is also accepted (JSON-mode advanced).
    conditions: list[Condition] | Condition | None = None
    actions: list[Action] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _default_trigger_type(cls, data: Any) -> Any:
        """A trigger without an explicit ``type`` means "event" (the engine's default). The
        discriminated union needs the tag present, so fill it in before validation."""
        if isinstance(data, dict):
            trig = data.get("trigger")
            if isinstance(trig, dict) and "type" not in trig:
                data = {**data, "trigger": {**trig, "type": "event"}}
        return data


Condition.model_rebuild()


def definition_json_schema() -> dict:
    """The definition's JSON Schema — advertised by /api/automations/options so the builder + SDK
    mirror one declaration instead of hand-maintaining a parallel shape."""
    return AutomationDefinition.model_json_schema(by_alias=True)
