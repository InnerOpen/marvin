"""Pydantic schemas for per-workspace AI workflow policy settings."""

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
    persona_prompt: str | None = None
    default_register: str | None = None

    model_config = ConfigDict(from_attributes=True)


class WorkspaceAISettingsRead(WorkspaceAISettingsCreate):
    id: UUID4 | None = None
    group_id: UUID4 | None = None
    # Read-only platform policy (from AppSettings), surfaced so the UI can gate the
    # "workspace" credential option. Not persisted on the workspace row.
    allow_workspace_credentials: bool = True

    model_config = ConfigDict(from_attributes=True)
