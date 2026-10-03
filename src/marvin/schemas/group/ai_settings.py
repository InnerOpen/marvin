"""Pydantic schemas for per-workspace AI workflow policy settings."""

from datetime import date

from pydantic import UUID4, ConfigDict

from marvin.schemas._marvin import _MarvinModel


class WorkspaceAISettingsCreate(_MarvinModel):
    enabled: bool = True
    credential_mode: str = "platform"  # "platform" | "workspace" | "disabled"
    provider: str | None = None
    model: str | None = None
    secret_ref: str | None = None  # slug of a WorkspaceSecret — never a raw key
    approval_mode: str = "suggest-only"  # "suggest-only" | "allow-draft-update" | "allow-automatic-update"

    invocation_sources: dict | None = None
    operation_overrides: dict | None = None
    budget_config: dict | None = None
    logging_config: dict | None = None
    moderation_config: dict | None = None
    # Per-workspace grade preset overrides ({name: {warmth, contrast, saturation, brightness,
    # vignette}}), merged over the built-in presets. None → built-in defaults only.
    media_presets: dict | None = None
    # Master switch: may the agent draw tools from registered external MCP servers?
    external_mcp_enabled: bool = False
    # Per-workspace AI persona: display name, bubble icon (emoji or image URL) and a voice/tone instruction.
    assistant_name: str | None = None
    assistant_icon: str | None = None
    # The bubble's animated character ({"states": {state: url}, "files": [...]}, or a library pack's —
    # {"library": id, "name", "states"}), shown instead of the icon. Set through
    # POST /groups/ai-settings/character or PUT …/character/library; see services/ai/character.py.
    assistant_character: dict | None = None
    persona_prompt: str | None = None
    # Default tone register for agent runs (axis B, separate from persona). A per-call register wins.
    default_register: str = "auto"  # "auto" | "professional" | "playful"

    model_config = ConfigDict(from_attributes=True)


class WorkspaceAISettingsUpdate(_MarvinModel):
    enabled: bool | None = None
    credential_mode: str | None = None
    provider: str | None = None
    model: str | None = None
    secret_ref: str | None = None
    approval_mode: str | None = None

    invocation_sources: dict | None = None
    operation_overrides: dict | None = None
    budget_config: dict | None = None
    logging_config: dict | None = None
    moderation_config: dict | None = None
    media_presets: dict | None = None
    external_mcp_enabled: bool | None = None
    assistant_name: str | None = None
    assistant_icon: str | None = None
    # Only {"states": ...} or {"library": pack id or slug} is taken (or null, to remove the character);
    # uploads go through /character.
    assistant_character: dict | None = None
    persona_prompt: str | None = None
    default_register: str | None = None

    model_config = ConfigDict(from_attributes=True)


class WorkspaceAISettingsRead(WorkspaceAISettingsCreate):
    id: UUID4 | None = None
    group_id: UUID4 | None = None
    # Read-only platform policy (from AppSettings), surfaced so the UI can gate the
    # "workspace" credential option. Not persisted on the workspace row.
    allow_workspace_credentials: bool = True
    # {agent slug: states} for agents with a bubble character of their own, so the bubble can swap on
    # `/use` and during hand-offs without another request. Not persisted on the workspace row.
    agent_characters: dict[str, dict[str, str]] = {}

    model_config = ConfigDict(from_attributes=True)


class AIUsageOperation(_MarvinModel):
    operation: str
    label: str
    runs: int
    tokens: int
    cost_usd: float


class AIUsageLimits(_MarvinModel):
    max_cost_per_month_usd: float | None = None
    max_requests_per_day: int | None = None
    max_tokens_per_request: int | None = None


class WorkspaceAIUsage(_MarvinModel):
    """Where the workspace stands against its AI limits — see services/ai/budget.py."""

    limits: AIUsageLimits
    warning_percent: float
    level: str  # "ok" | "warn" | "over"
    month_cost_usd: float
    month_tokens: int
    month_runs: int
    month_percent: float | None = None
    today_runs: int
    day_percent: float | None = None
    resets_on: date | None = None
    by_operation: list[AIUsageOperation] = []


class AssistantCharacterFile(_MarvinModel):
    """One animation the character's upload stored, assigned to a state or not."""

    name: str
    asset_id: str | None = None  # a workspace's own character; library packs' files aren't assets
    url: str


class AssistantCharacter(_MarvinModel):
    """The bubble's animated character — see services/ai/character.py."""

    library: str | None = None  # the library pack's id, when it is one (its files aren't listed)
    name: str | None = None
    states: dict[str, str]
    files: list[AssistantCharacterFile] = []
    missing: list[str] = []  # canonical states without an animation; the bubble falls back for these


class AssistantCharacterUpload(AssistantCharacter):
    ignored: list[str] = []  # uploaded files that weren't a GIF, WebP or PNG image (or were duplicates)
    idle_guessed: bool = False  # no file was named for idle, so the first image stands in
    cleared: list[str] = []  # files whose solid background was made transparent (services/ai/character.py: clear_matte)


class AssistantCharacterAssign(_MarvinModel):
    state: str
    file: str | None = None  # a file name or asset id from the character's files; null clears the state


class AssistantCharacterLibraryChoice(_MarvinModel):
    pack: str  # a library pack's id or slug


class CharacterPackSummary(_MarvinModel):
    """A library pack as a workspace member sees it, to choose from."""

    id: str
    slug: str
    name: str
    states: dict[str, str]
    missing: list[str] = []


class AssistantCharacterState(_MarvinModel):
    key: str
    aliases: list[str]
    required: bool = False
