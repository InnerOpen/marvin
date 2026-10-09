"""Pydantic schemas for workspace automations (Flavor B: event → conditions → actions).

The `definition` is intentionally a loose dict at the API boundary — the automation engine
validates/executes it. `AutomationOptions` advertises the builder's vocabulary (trigger events,
condition operators, action kinds) so the UI is backend-driven rather than hardcoding it.
"""

from datetime import datetime
from typing import Any

from pydantic import UUID4, ConfigDict

from marvin.schemas._marvin import _MarvinModel


class AutomationCreate(_MarvinModel):
    name: str
    slug: str | None = None  # generated from name when omitted
    enabled: bool = False
    definition: dict = {}  # {trigger, conditions, actions} — validated by the engine

    model_config = ConfigDict(from_attributes=True)


class AutomationUpdate(_MarvinModel):
    name: str | None = None
    enabled: bool | None = None
    definition: dict | None = None

    model_config = ConfigDict(from_attributes=True)


class AutomationRead(_MarvinModel):
    id: UUID4
    group_id: UUID4
    name: str
    slug: str
    enabled: bool
    definition: dict = {}
    created_by: UUID4 | None = None
    source_integration_id: UUID4 | None = None
    """Read-only "installed by": the integration whose blueprint created this (null: made by a person)."""
    source_blueprint: str | None = None
    """Read-only: the slug of the blueprint that created this, if one did."""

    model_config = ConfigDict(from_attributes=True)


class AutomationActionOption(_MarvinModel):
    """One operation the builder can offer as an `operation` action."""

    op: str
    name: str
    description: str
    entity_types: list[str] = []
    writes_back: bool = False  # whether this op has a write-back map (offer the toggle)

    model_config = ConfigDict(from_attributes=True)


class AutomationWebhookOption(_MarvinModel):
    """One of the workspace's configured webhooks, offered to the `webhook` action."""

    id: UUID4
    name: str
    url: str
    method: str = "POST"

    model_config = ConfigDict(from_attributes=True)


class AutomationTargetOption(_MarvinModel):
    """Another automation in the workspace — a chained/on-error trigger may target it."""

    id: UUID4
    slug: str
    name: str

    model_config = ConfigDict(from_attributes=True)


class AutomationIncomingWebhookOption(_MarvinModel):
    """One of the workspace's incoming webhooks — an `incoming_webhook` trigger targets it by slug."""

    id: UUID4
    slug: str
    name: str
    enabled: bool = False
    has_token: bool = False  # whether a token has been minted (the endpoint is live)

    model_config = ConfigDict(from_attributes=True)


class AutomationConditionField(_MarvinModel):
    """A field a condition can reference, suggested per trigger context (guided builder)."""

    field: str  # dotted path, e.g. "entry.entry_type" or "event.payload."
    label: str
    description: str = ""

    model_config = ConfigDict(from_attributes=True)


class AutomationOptions(_MarvinModel):
    """The builder's vocabulary — so the UI doesn't hardcode triggers/ops/operators."""

    trigger_types: list[str] = []  # event | manual (schedule/webhook/chat/mcp/… as they land)
    triggers: list[str] = []  # event names, for trigger_type="event" (flat, all groups)
    trigger_groups: dict[str, list[str]] = {}  # same event names grouped (Entries/Assets/…) for the picker
    emittable: list[str] = []  # event names the emit_event step offers (the event catalog's `emittable`)
    condition_ops: list[str] = []  # eq | neq | contains | exists
    # Suggested condition fields per trigger type — so the builder offers the right fields and can't
    # silently pair an entry.* condition with a trigger that has no entry.
    condition_fields: dict[str, list[AutomationConditionField]] = {}
    action_kinds: list[str] = []  # operation / emit_event / handler / webhook
    operations: list[AutomationActionOption] = []
    webhooks: list[AutomationWebhookOption] = []  # the workspace's configured (outgoing) webhooks
    automations: list[AutomationTargetOption] = []  # other automations (chained/on-error targets)
    incoming_webhooks: list[AutomationIncomingWebhookOption] = []  # ingress webhooks (incoming_webhook trigger)
    # JSON Schema of the definition (trigger/action/condition/target discriminated unions) — the one
    # structural declaration the builder + SDK mirror. dict-typed to pass the schema through verbatim.
    definition_schema: dict = {}

    model_config = ConfigDict(from_attributes=True)


class AutomationValidationIssue(_MarvinModel):
    """One advisory coherence issue in a definition (not a hard error)."""

    level: str  # "warning" | "error"
    message: str
    where: str  # "trigger" | "condition" | "action"
    index: int | None = None  # position within conditions/actions, when applicable
    path: str | None = None  # the key the issue is about, as an author reads it (actions[0].op), when known

    model_config = ConfigDict(from_attributes=True)


class AutomationValidateRequest(_MarvinModel):
    definition: dict = {}

    model_config = ConfigDict(from_attributes=True)


class AutomationValidateResult(_MarvinModel):
    issues: list[AutomationValidationIssue] = []

    model_config = ConfigDict(from_attributes=True)


class AutomationPreviewMatch(_MarvinModel):
    """One entity a `target` selector resolved to (dry-run preview): an entry (entry_type, status, title) or an
    asset / resource (name, asset_type / resource_type, trashed)."""

    id: str
    entity: str = "entry"
    entry_type: str | None = None
    status: str | None = None
    title: str | None = None
    slug: str | None = None
    name: str | None = None
    asset_type: str | None = None
    resource_type: str | None = None
    trashed: bool | None = None

    model_config = ConfigDict(from_attributes=True)


class AutomationPreviewRequest(_MarvinModel):
    definition: dict = {}
    payload: dict = {}  # simulates $event.payload for the query/conditions

    model_config = ConfigDict(from_attributes=True)


class AutomationPreviewResult(_MarvinModel):
    """Dry-run of a `target` selector — which entities it resolves to, before running anything."""

    has_target: bool = False  # false when the definition has no target selector
    entity: str = "entry"
    total: int = 0  # entities matching the query (the FROM count, pre-cap)
    capped: bool = False  # total exceeded the run cap (only the first N would run)
    matches: list[AutomationPreviewMatch] = []  # capped set that also passes conditions (the WHERE)
    error: str | None = None

    model_config = ConfigDict(from_attributes=True)


class AutomationActionExecutionRead(_MarvinModel):
    """One recorded step within a run — which target, which action, and how it went."""

    id: UUID4
    target_index: int = 0
    target_entity_type: str | None = None
    target_entity_id: str | None = None
    action_index: int = 0
    kind: str
    label: str | None = None
    status: str
    error: str | None = None
    duration_ms: int | None = None
    output_snapshot: dict | None = None
    handling: dict | None = None
    """How the integration's error policy handled this failed step: {code, applied, summary, retry?}."""

    model_config = ConfigDict(from_attributes=True)


class AutomationExecutionRead(_MarvinModel):
    """One recorded run of an automation (compact — for the history list)."""

    id: UUID4
    automation_id: UUID4 | None = None
    automation_slug: str
    trigger_type: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    targets_matched: int = 1
    targets_run: int = 0
    capped: bool = False
    steps_total: int = 0
    steps_ok: int = 0
    steps_failed: int = 0
    error: str | None = None
    correlation_id: str | None = None
    triggered_by: UUID4 | None = None
    handled: bool = False
    """A failed run whose every failure an integration's error policy took in hand (review, retry, …)."""
    retry_of_id: UUID4 | None = None
    """On a retry run: the run whose failed step it resumed."""

    model_config = ConfigDict(from_attributes=True)


class IntegrationRetryRead(_MarvinModel):
    """A failed integration step's retry chain — pending, parked (waiting for the connection), or done."""

    id: UUID4
    status: str
    integration_slug: str
    action: str
    code: str
    step_index: int
    entry_id: UUID4 | None = None
    attempt: int = 0
    max_attempts: int = 0
    next_attempt_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str | None = None
    origin_execution_id: UUID4 | None = None

    model_config = ConfigDict(from_attributes=True)


class AutomationExecutionDetail(AutomationExecutionRead):
    """A run plus its per-step records and the definition it ran against."""

    definition_snapshot: dict | None = None
    actions: list[AutomationActionExecutionRead] = []
    retry_chain: list[AutomationExecutionRead] = []
    """The original run and each retry of it, oldest first — just this run when it has none."""
    retries: list[IntegrationRetryRead] = []
    """The retry chains its failures started (what happens next, or how it ended)."""

    model_config = ConfigDict(from_attributes=True)


# ── Workflow Library (services/automation/recipes) ─────────────────────────────
class WorkflowRecipeVariable(_MarvinModel):
    """A setup placeholder the person fills: its `type` says which picker (entry_type_slug, field_key, webhook_id…)."""

    name: str
    type: str
    description: str = ""
    example: Any = None


class WorkflowRecipeTrigger(_MarvinModel):
    type: str  # event | manual | schedule | subscription | incoming_webhook | on_error
    event: str | None = None
    note: str | None = None


class WorkflowRecipeSideEffect(_MarvinModel):
    kind: str  # content_mutation | external_post | paid_call | notification | email
    description: str = ""


class WorkflowRecipeSupportingObject(_MarvinModel):
    """Something set up alongside the recipe — for a configuration recipe, the whole of it."""

    kind: str  # email_event_subscription | notification_settings | outgoing_webhook | integration_connection | …
    name: str = ""
    purpose: str = ""
    required: bool = False


class WorkflowRecipeDependency(_MarvinModel):
    """An idea's gap: the capability it waits on (a key of `WorkflowLibraryRead.capabilities`) and why."""

    capability: str
    why: str = ""


class WorkflowRecipe(_MarvinModel):
    """One catalogue entry, and whether this workspace can use it: `missing` empty → ready here."""

    id: str
    title: str
    outcome: str
    category: str
    category_slug: str
    tags: list[str] = []
    trigger: WorkflowRecipeTrigger
    status: str  # verified-current | supported-after-configuration | needs-engine-capability | needs-adapter
    shape: str  # workflow | configuration | idea
    providers: list[str] = []  # integration providers it needs connected
    side_effects: list[WorkflowRecipeSideEffect] = []
    setup_variables: list[WorkflowRecipeVariable] = []
    supporting_objects: list[WorkflowRecipeSupportingObject] = []
    dependencies: list[WorkflowRecipeDependency] = []
    missing: list[str] = []


class WorkflowCapability(_MarvinModel):
    name: str
    priority: str = ""
    acceptance: str = ""


class WorkflowLibraryEntryType(_MarvinModel):
    slug: str
    name: str
    fields: list[str] = []


class WorkflowLibraryIntegration(_MarvinModel):
    slug: str
    name: str
    provider: str
    enabled: bool = False


class WorkflowLibraryRef(_MarvinModel):
    """A collection, an outgoing webhook (`id`) or an incoming one (`slug`) — what a picker offers."""

    id: str | None = None
    slug: str | None = None
    name: str
    enabled: bool | None = None


class WorkflowLibraryRefs(_MarvinModel):
    """The workspace's names every setup picker draws from, in one fetch."""

    entry_types: list[WorkflowLibraryEntryType] = []
    integrations: list[WorkflowLibraryIntegration] = []
    collections: list[WorkflowLibraryRef] = []
    outgoing_webhooks: list[WorkflowLibraryRef] = []
    incoming_webhooks: list[WorkflowLibraryRef] = []
    statuses: list[str] = []


class WorkflowLibraryRead(_MarvinModel):
    recipes: list[WorkflowRecipe] = []
    capabilities: dict[str, WorkflowCapability] = {}
    refs: WorkflowLibraryRefs = WorkflowLibraryRefs()


class RecipeConfigureRequest(_MarvinModel):
    vars: dict[str, Any] = {}


class RecipeConfigureResult(_MarvinModel):
    """A recipe filled in for this workspace — not saved. `issues` are what the builder would flag (shown, not blocking)."""

    name: str
    definition: dict
    issues: list[AutomationValidationIssue] = []
