"""Pydantic schemas for workspace external MCP servers (agent tool sources)."""

from pydantic import UUID4, ConfigDict

from marvin.schemas._marvin import _MarvinModel


class McpServerCreate(_MarvinModel):
    name: str
    slug: str | None = None  # generated from name when omitted
    transport: str = "http"  # "http" | "sse" (stdio not supported)
    url: str
    secret_ref: str | None = None  # slug of a WorkspaceSecret (Bearer token)
    enabled: bool = False
    allowed_tools: list[str] | None = None  # DENY by default — only listed tools are callable

    model_config = ConfigDict(from_attributes=True)


class McpServerUpdate(_MarvinModel):
    name: str | None = None
    transport: str | None = None
    url: str | None = None
    secret_ref: str | None = None
    enabled: bool | None = None
    allowed_tools: list[str] | None = None

    model_config = ConfigDict(from_attributes=True)


class McpServerRead(_MarvinModel):
    id: UUID4
    group_id: UUID4
    name: str
    slug: str
    transport: str
    url: str
    secret_ref: str | None = None
    enabled: bool
    allowed_tools: list[str] | None = None
    created_by: UUID4 | None = None

    model_config = ConfigDict(from_attributes=True)


class McpServerToolInfo(_MarvinModel):
    """A tool advertised by a server's tools/list (shown in the UI to build the allowlist)."""

    name: str
    description: str
    input_schema: dict = {}
    read_only: bool | None = None  # readOnlyHint, when the server sends annotations
    destructive: bool | None = None  # destructiveHint

    model_config = ConfigDict(from_attributes=True)


class McpServerTestResult(_MarvinModel):
    success: bool
    message: str
    tools: list[McpServerToolInfo] = []

    model_config = ConfigDict(from_attributes=True)
