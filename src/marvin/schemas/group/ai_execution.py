"""Pydantic schemas for AI executions."""

from datetime import datetime

from pydantic import UUID4, ConfigDict, Field

from marvin.schemas._marvin import _MarvinModel


class AIExecutionRead(_MarvinModel):
    id: UUID4
    group_id: UUID4
    operation_slug: str
    provider_type: str
    model_id: str
    status: str
    triggered_by: UUID4 | None = None
    trigger_type: str
    entity_type: str | None = None
    entity_id: UUID4 | None = None
    output_json: dict | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost_usd: float | None = None
    duration_ms: int | None = None
    error_message: str | None = None
    # Execution metadata — carries `writeback: "applied" | "staged"` so a client can report
    # honestly whether the entity was changed or a suggestion is waiting for review.
    metadata_json: dict | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class AIOperationExecuteRequest(_MarvinModel):
    entity_type: str | None = None
    entity_id: str | None = None  # UUID or slug — resolved server-side (MCP/CLI work in slugs)
    input: dict = {}
    model_override: str | None = None  # override the workspace default model
    # Invocation surface (editor/forms/actions/mcp/scheduled/agent/api). Set by the calling
    # infrastructure (e.g. MarvinMCP sends "mcp"); gated against the workspace policy ∩ the
    # operation's declared sources. Defaults to the admin editor.
    source: str = "editor"

    model_config = ConfigDict(from_attributes=True)


class AIReindexRequest(_MarvinModel):
    """Reindex embeddings for a single entity, or the whole workspace when scope='workspace'."""

    entity_type: str | None = None  # entry | resource
    entity_id: UUID4 | None = None
    scope: str | None = None  # "workspace" → reindex all entries + resources

    model_config = ConfigDict(from_attributes=True)


class AIComposeEntryRequest(_MarvinModel):
    """Compose a draft entry of `entry_type` from a short brief (+ optional image assets)."""

    entry_type: str  # entry type slug or id
    brief: str  # what the entry should be about
    # image assets to see (vision) + attach. Order matters: first → hero, and only the first 4 are
    # sent to the model as vision input, so callers should list the most important images first.
    asset_ids: list[UUID4] | None = None
    model_override: str | None = None
    # Optional tone register for this compose, falling back to the workspace default. Named
    # `tone_register` in Python but aliased to `register` on the wire — a field literally named
    # `register` shadows ABCMeta.register and trips a Pydantic warning (see AIAgentRequest). The
    # compose route reads `body.tone_register`; without this field that raised AttributeError → 502.
    tone_register: str | None = Field(default=None, alias="register")
    source: str = "editor"  # invocation surface; gated by workspace policy

    model_config = ConfigDict(from_attributes=True)


class AIReviseEntryRequest(_MarvinModel):
    """Revise an EXISTING entry in place per an instruction — never recreate it.

    The counterpart to compose: same shared AuthoringService, but it enriches an entry that
    already exists (e.g. "determine the tags and attach any relevant resources", "tighten the
    summary") rather than authoring a new draft.
    """

    entry: str  # the entry to revise, by slug or id
    instruction: str  # what to determine / change
    model_override: str | None = None
    source: str = "editor"  # invocation surface; gated by workspace policy

    model_config = ConfigDict(from_attributes=True)


class AIAgentTurn(_MarvinModel):
    """One prior turn of the conversation, replayed to give the agent short-term memory."""

    role: str  # "user" | "assistant" (anything else is dropped)
    content: str

    model_config = ConfigDict(from_attributes=True)


class AIAgentRequest(_MarvinModel):
    """Run the Marvin agent — an iterative tool-calling loop over Marvin's own capabilities."""

    message: str  # the user's request / question
    entity_type: str | None = None  # optional grounding: what the caller is looking at
    entity_id: str | None = None  # UUID or slug — resolved server-side
    # Prior turns, oldest first, EXCLUDING the current message. The client is stateless as far as
    # the model is concerned — it replays what it has. Bounded server-side (turn count + chars) so
    # a long transcript can't blow the context window or the token budget.
    history: list[AIAgentTurn] = []
    # Tone register for this call, independent of the workspace persona. The persona governs how
    # the assistant ADDRESSES the user; it must not govern work product (a review written in
    # character isn't actionable). "professional" suppresses the persona outright.
    # None (default) → fall back to the workspace's `default_register`, then "auto". An explicit
    # value here wins — e.g. the entry editor's "Review & suggest" sends "professional".
    # "auto" | "professional" | "playful"
    #
    # Named `tone_register` in Python, aliased back to `register` on the wire. A field
    # literally named `register` shadows `ABCMeta.register` (Pydantic's metaclass derives
    # from ABCMeta), which Pydantic warns about on every startup. The alias keeps the
    # request/response payload byte-identical — clients still send/receive `register`.
    tone_register: str | None = Field(default=None, alias="register")
    model_override: str | None = None
    max_steps: int | None = None  # tool-dispatch budget (server clamps)
    source: str = "agent"  # invocation surface; gated by workspace policy

    model_config = ConfigDict(from_attributes=True)


class AIToolInvokeRequest(_MarvinModel):
    """Invoke a core AI tool by name with raw args (the generic execution endpoint).

    This is the one endpoint MarvinMCP routes every projected registry tool through: the tool's
    handler receives `args` verbatim and returns its JSON result.
    """

    args: dict = {}  # tool args matching the tool's input schema
    source: str = "mcp"  # invocation surface; gated by workspace policy

    model_config = ConfigDict(from_attributes=True)
