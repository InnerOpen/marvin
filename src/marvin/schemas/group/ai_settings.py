"""Pydantic schemas for per-workspace AI workflow policy settings."""

from datetime import date, datetime

from pydantic import UUID4, ConfigDict

from marvin.schemas._marvin import _MarvinModel


class BubbleLines(_MarvinModel):
    """The Ask bubble's canned lines in the workspace's voice — see services/ai/bubble_lines.py. An empty
    list falls back to the built-in lines for that list."""

    greetings: list[str] = []
    taglines: list[str] = []
    thinking: list[str] = []
    errors: list[str] = []
    emotes: list[str] = []


class BubbleLinesState(_MarvinModel):
    """The bubble lines as AI settings → Persona shows them."""

    bubble_lines: BubbleLines | None = None
    bubble_lines_source: str | None = None  # "generated" | "edited"; None = the built-in lines
    bubble_lines_updated_at: datetime | None = None
    bubble_lines_warning: str | None = None  # why the last generation failed (the previous lines were kept)
    bubble_lines_generating: bool = False

    model_config = ConfigDict(from_attributes=True)


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
    # Per-workspace AI persona: display name, bubble icon (emoji or image URL) and its Character
    # (who the assistant is and how it speaks; the tone decides how far it reaches — services/ai/tones.py).
    assistant_name: str | None = None
    assistant_icon: str | None = None
    # The bubble's animated character ({"states": {state: url}, "files": [...]}, or a library pack's —
    # {"library": id, "name", "states"}), shown instead of the icon. Set through
    # POST /groups/ai-settings/character or PUT …/character/library; see services/ai/character.py.
    assistant_character: dict | None = None
    persona_prompt: str | None = None
    # Default tone for agent runs (axis B, separate from persona) — a tone slug, built-in ("auto" |
    # "professional" | "playful") or the workspace's own (GET /groups/ai-settings/tones). A per-call tone wins.
    default_register: str = "auto"

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


class WorkspaceAISettingsRead(BubbleLinesState, WorkspaceAISettingsCreate):
    # Bubble lines (from BubbleLinesState) are read-only here: they're set through /bubble-lines.
    id: UUID4 | None = None
    group_id: UUID4 | None = None
    # Read-only platform policy (from AppSettings), surfaced so the UI can gate the
    # "workspace" credential option. Not persisted on the workspace row.
    allow_workspace_credentials: bool = True
    # {agent slug: states} for agents with a bubble character of their own, so the bubble can swap on
    # `/use` and during hand-offs without another request. Not persisted on the workspace row.
    agent_characters: dict[str, dict[str, str]] = {}
    # {image URL: {top, right, bottom, left}}: the empty frame around each character image's drawing, as shares of
    # the frame, for the workspace's and its agents' characters — a tucked bubble lines up the drawing, not the
    # frame, with the screen edge. An image missing here was stored before it was measured.
    character_insets: dict[str, dict[str, float]] = {}

    model_config = ConfigDict(from_attributes=True)


class ToneItem(_MarvinModel):
    """A custom tone as the editor sends it. No slug → one is made from the name; a slug never changes."""

    slug: str | None = None
    name: str = ""
    instructions: str = ""
    persona: str = "frame"  # "frame" | "everywhere" | "drop" — see services/ai/tones.py
    description: str | None = None


class ToneRead(ToneItem):
    slug: str
    builtin: bool = False
    hidden: bool = False
    used_by: list[str] = []  # slugs of the workspace agents that default to this tone


class TonesState(_MarvinModel):
    """Every tone the workspace can use (built-ins first), which one is the default, and the editor's limits."""

    tones: list[ToneRead]
    default_tone: str
    max_custom_tones: int
    max_name_chars: int
    max_instructions_chars: int


class TonesUpdate(_MarvinModel):
    """Replace the custom tones and the hidden list (and optionally the default) in one save."""

    tones: list[ToneItem] = []
    hidden: list[str] = []
    default_tone: str | None = None  # omitted → unchanged


class TonePreviewRequest(_MarvinModel):
    """A saved tone by slug, or a draft one (name + instructions + persona) as the editor has it; neither →
    the workspace default tone (the Character box's preview).

    ``persona_prompt`` / ``assistant_name``, when sent, stand in for the stored ones (the AI settings form's
    unsaved values; blank means blank, so a cleared Character previews Marvin's default one).
    """

    slug: str | None = None
    name: str | None = None
    instructions: str | None = None
    persona: str | None = None
    persona_prompt: str | None = None
    assistant_name: str | None = None

    @property
    def is_draft(self) -> bool:
        return any(v is not None for v in (self.name, self.instructions, self.persona))


class TonePreview(_MarvinModel):
    """A tone's prompt section, whole and in labelled parts, so the editor never parses the text."""

    clause: str  # exactly what is appended to an agent's system prompt (with the workspace persona)
    tokens: int  # rough estimate; it rides on every agent step
    persona: str  # the tone's persona rule: frame / everywhere / drop
    persona_summary: str  # that rule in plain words
    has_persona: bool  # whether the workspace has a character to use (the persona, or Marvin's default voice)
    character: str = ""  # from the persona: the Character block ("" when the tone drops it, or there is none)
    from_tone: str = ""  # from the tone: its persona rule's scope line(s) and its instructions
    rule: str = ""  # the precedence rule, when a character and a tone's instructions both apply
    tone_slug: str = ""  # the tone previewed (for a draft, the slug it would get)
    tone_name: str = ""


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
