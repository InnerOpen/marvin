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

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator


class _DefnBase(BaseModel):
    # snake_case verbatim (no camelize), lenient on unknown keys, accept field name or alias.
    model_config = ConfigDict(extra="allow", populate_by_name=True)


# ── Triggers (discriminated on `type`) ────────────────────────────────────────
class EventTrigger(_DefnBase):
    """Runs when a Marvin event fires: `event` is a triggerable event name. An entry event's entry is `entry.*`."""

    type: Literal["event"] = "event"
    event: str


class ManualTrigger(_DefnBase):
    """Runs only when someone presses Run (or the run_workflow tool or the API runs it)."""

    type: Literal["manual"]


class ScheduleTrigger(_DefnBase):
    """Runs on a schedule: `schedule_type` interval (`schedule_config.interval_seconds`), cron
    (`cron_expression`, `timezone`) or once (`run_at`, ISO 8601)."""

    type: Literal["schedule"]
    schedule_type: str | None = None
    schedule_config: dict[str, Any] | None = None


class ChainedTrigger(_DefnBase):
    """Runs after another workflow ran: `automation` is its slug or id (omitted or "any": every workflow)."""

    type: Literal["chained"]
    automation: str | None = None  # target automation (slug/id); None/"any" = every automation


class OnErrorTrigger(_DefnBase):
    """Runs after another workflow failed: `automation` is its slug or id (omitted or "any": every workflow)."""

    type: Literal["on_error"]
    automation: str | None = None


class IncomingWebhookTrigger(_DefnBase):
    """Runs when an incoming webhook is called: `webhook` is its slug (omitted or "any": any). The body is `event.payload.*`."""

    type: Literal["incoming_webhook"]
    webhook: str | None = None  # target incoming-webhook slug; None/"any" = any webhook


class McpTrigger(_DefnBase):
    """Runs when an MCP host calls the workflow's own tool, `marvin_wf_<slug>`."""

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
    """Runs an AI operation (`op`: its slug) on the entry — or, with `entity_type` asset | resource, on that item (the
    operation must support it); `write_back` saves the result onto it."""

    kind: Literal["operation"]
    op: str  # AI operation slug
    input: dict[str, Any] = Field(default_factory=dict)
    entity_type: str = "entry"  # unset: the target's or the triggering item's kind, else entry
    entity_id: str | None = None  # defaults to the run's $event.<entity_type>_id
    entity_slug: str | None = None  # preferred for webhook payloads; resolved at run time
    write_back: bool = False
    id: str | None = None  # addressable as $steps.<id>.output.*


class EntryAction(_DefnBase):
    """Changes an entry without AI: a status op, collection membership, a metadata/data write or a review
    request. `trash` / `restore` also act on an asset or a resource (`entity_type`; unset, the kind of the
    target's or the triggering item): `entity_slug` / `entity_id`, else the current one — never `entity_query`."""

    kind: Literal["entry"]
    op: Literal[
        "publish",
        "unpublish",
        "archive",
        "trash",
        "restore",
        "add_to_collection",
        "remove_from_collection",
        "set_metadata",
        "set_data",
        "request_review",
    ]
    entity_type: Literal["entry", "asset", "resource"] = "entry"  # trash / restore also act on an asset or resource
    entity_id: str | None = None
    entity_slug: str | None = None
    entity_query: dict[str, Any] | None = None  # find exactly one entry (target-selector vocabulary; values may be templates)
    if_none: Literal["fail", "skip"] | None = None  # entity_query matched nothing: fail the step (unset/"fail") or skip it quietly
    collection_id: str | None = None  # for add_to_collection / remove_from_collection…
    collection_slug: str | None = None  # …preferred: a collection slug/name (may be a $event.* template)
    metadata: dict[str, Any] | None = None  # for set_metadata: keys merged into metadata_json (values may be templates)
    data: dict[str, Any] | None = None  # for set_data: schema fields merged into data_json (validated; values may be templates)
    reason: str | None = None  # for request_review: why it needs review, added to metadata_json.review_reasons (may be a template)
    id: str | None = None

    # Shapes that can only fail at run time are refused here, so the REST write gate (422) and an agent's draft
    # name them with their path (actions[0].entity_type) — see services/automation/actions/entry.py.
    @field_validator("entity_type")
    @classmethod
    def _item_ops_only(cls, value: str, info: ValidationInfo) -> str:
        op = info.data.get("op")  # absent when `op` itself failed — that error stands alone
        if op is not None and value != "entry" and op not in ("trash", "restore"):
            raise ValueError(f"only trash and restore act on an {value}; “{op}” acts on entries (drop entity_type)")
        return value

    @field_validator("entity_query")
    @classmethod
    def _entity_query_finds_entries(cls, value: dict[str, Any] | None, info: ValidationInfo) -> dict[str, Any] | None:
        kind = info.data.get("entity_type", "entry")
        if value is not None and kind != "entry":
            raise ValueError(
                f"entity_query finds entries only — a {kind} step acts on the current {kind} (an asset/resource target's "
                f"row, or the triggering one), or one named by entity_slug / entity_id"
            )
        return value


class EmitEventAction(_DefnBase):
    """Sends a Marvin event (`event`: an emittable event name) for other workflows and subscribers."""

    kind: Literal["emit_event"]
    event: str  # internal event name to re-emit
    entity_id: str | None = None
    id: str | None = None


class HandlerAction(_DefnBase):
    """Runs an allowlisted internal job (`task`), e.g. request_site_rebuild."""

    kind: Literal["handler"]
    task: str  # allowlisted scheduled-task handler
    config: dict[str, Any] = Field(default_factory=dict)
    id: str | None = None


class WebhookAction(_DefnBase):
    """Calls one of the workspace's outgoing webhooks (`webhook_id`), or a raw `url`, with a JSON `body`."""

    kind: Literal["webhook"]
    webhook_id: str | None = None  # a configured workspace webhook…
    url: str | None = None  # …or (advanced) a raw url
    method: str | None = None  # raw-url form only: GET | POST (default) | PUT | PATCH | DELETE
    body: dict[str, Any] = Field(default_factory=dict)
    secret_ref: str | None = None  # optional secret ref, sent as `Authorization: <auth_scheme> <secret>`
    auth_scheme: str | None = None  # Bearer (default) | Token | … — some APIs (Buttondown) reject Bearer
    id: str | None = None


class IntegrationAction(_DefnBase):
    """Runs a connected integration's action (`integration`: its slug, `action`: the action key) with `args`."""

    kind: Literal["integration"]
    integration: str  # the workspace integration's slug
    action: str  # the provider action key
    args: dict[str, Any] = Field(default_factory=dict)  # values may be templates; result → $steps.<id>.output
    id: str | None = None


ACTION_MODELS: dict[str, type[_DefnBase]] = {
    "operation": OperationAction,
    "entry": EntryAction,
    "emit_event": EmitEventAction,
    "handler": HandlerAction,
    "webhook": WebhookAction,
    "integration": IntegrationAction,
}

Action = Annotated[
    OperationAction | EntryAction | EmitEventAction | HandlerAction | WebhookAction | IntegrationAction,
    Field(discriminator="kind"),
]


# ── Conditions (recursive: a leaf {field, op, value} OR a group {all|any|not}) ─
class Condition(_DefnBase):
    """A leaf `{field, op, value}`, or a group `{all: [...]}` / `{any: [...]}` / `{not: {...}}`."""

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
    """Run on a query of entries, assets or resources instead of the trigger's one item: each match runs the steps
    as `entry`, `asset` or `resource` (`query`: that entity's keys, see the authoring guide's target section)."""

    entity: Literal["entry", "asset", "resource"] = "entry"
    query: dict[str, Any] = Field(default_factory=dict)


# ── The whole definition ──────────────────────────────────────────────────────
class AutomationDefinition(_DefnBase):
    trigger: Trigger | None = None
    target: Target | None = None
    # A top-level list is an implicit AND; a single group dict is also accepted (JSON-mode advanced).
    conditions: list[Condition] | Condition | None = None
    actions: list[Action] = Field(default_factory=list)
    # Steps run when a step of `actions` fails, in the same run and on the same entry, with the failure
    # as `${error.*}` (message, code, step, kind, at). The run still counts as failed.
    on_failure: list[Action] | None = None
    # How a failing integration step is handled. "policy" (the default) applies the integration's own
    # error policy — send the entry to review, retry later, alert admins, or carry on. "fail" opts this
    # workflow out: its integration steps fail as plain failures (the connection's admin alert still
    # fires). A workflow with on_failure steps runs those instead of the policy either way.
    integration_errors: Literal["policy", "fail"] | None = None

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
