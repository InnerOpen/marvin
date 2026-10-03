"""Base class and registry for named AI operations."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..base import Message

# WorkspaceRole numeric values for min_role checks
ROLE_VIEWER = 1
ROLE_AUTHOR = 2
ROLE_EDITOR = 3
ROLE_ADMIN = 4
ROLE_OWNER = 5

# Invocation surfaces an AI operation can be reached from. The effective allow-list for a
# call is the INTERSECTION of the operation's declared sources and the per-workspace
# invocation_sources policy (ai_settings). This gates *which surfaces* may run AI; min_role
# is the separate per-user authorization wall.
INVOCATION_SOURCES = ("editor", "forms", "actions", "mcp", "scheduled", "agent", "automation", "api")

# User-facing catalog for the invocation_sources policy editor: which surface each source is, in
# terms people recognize (not how it's wired). A source is allowed unless the workspace policy
# explicitly sets it false, so the editor shows every source as on by default.
#
# Only surfaces that actually identify themselves are listed. `forms`, `actions` and `scheduled` stay
# valid keys (an operation may declare them; old policies may store them) but nothing sends them — AI
# on form submissions and scheduled runs goes through workflows (`automation`) — so a toggle for them
# would switch nothing off.
#
# `source` is reported by the caller, so this is feature gating (turn a surface off), not a security
# boundary: per-user authorization is the role check.
UNSENT_SOURCES = ("forms", "actions", "scheduled")

INVOCATION_SOURCE_CATALOG: tuple[dict[str, str], ...] = (
    {"key": "editor", "label": "Entry editor", "description": "Inline AI actions inside the entry editor (summarize, tags, rewrite…)."},
    # `{assistant}` is the workspace's assistant name (AI settings → Persona), filled in when served.
    {
        "key": "agent",
        "label": "Ask {assistant}",
        "description": "The Ask {assistant} bubble, the Ask page and named agents (incl. resuming a paused chat).",
    },
    {"key": "automation", "label": "Workflows", "description": "Workflows running an AI-operation step (incl. form- or schedule-triggered ones)."},
    {"key": "mcp", "label": "External MCP hosts", "description": "External assistants (Claude Desktop, etc.) calling in over MCP."},
    {"key": "api", "label": "API", "description": "Direct calls to the AI operation endpoints."},
)

OPERATION_REGISTRY: dict[str, "AIOperation"] = {}


def register_operation(cls):
    """Class decorator that adds the operation to the global registry."""
    OPERATION_REGISTRY[cls.slug] = cls()
    return cls


def get_operation(slug: str) -> "AIOperation":
    if slug not in OPERATION_REGISTRY:
        raise KeyError(f"AI operation '{slug}' not found. Available: {list(OPERATION_REGISTRY)}")
    return OPERATION_REGISTRY[slug]


def list_operations() -> list["AIOperation"]:
    return list(OPERATION_REGISTRY.values())


@dataclass
class OperationContext:
    """Resolved context assembled by ContextBuilder before prompt construction."""

    workspace_name: str = ""
    site_title: str = ""
    site_locale: str = "en-US"
    current_date: str = ""
    variables: dict = field(default_factory=dict)
    entry: dict | None = None
    assets: list[dict] = field(default_factory=list)
    resources: list[dict] = field(default_factory=list)
    form_submission: dict | None = None
    retrieved: list[dict] = field(default_factory=list)  # semantic-search chunks (RAG)


class AIOperation(ABC):
    """
    Named, typed AI capability.

    Each subclass defines input/output schemas, minimum role,
    supported entity types, and prompt construction logic.
    """

    slug: str
    name: str
    description: str
    # NOTE: plain class-level defaults, NOT dataclasses.field() — AIOperation is a plain ABC, so
    # field(default_factory=...) would never resolve to {} here; it would leave a truthy Field
    # object on every subclass that doesn't override it (breaking `getattr(op, "writeback") or {}`).
    # Matches the existing `entity_types: list[str] = []` convention. Treat these as read-only.
    input_schema: dict = {}
    output_schema: dict = {}
    min_role: int = ROLE_AUTHOR
    entity_types: list[str] = []  # which entity types this operation supports
    requires_vision: bool = False
    # Look at an image asset target when the model can see (unlike requires_vision, works without:
    # the prompt falls back to the asset's name/alt text/description).
    sees_asset_image: bool = False
    requires_retrieval: bool = False  # RAG: retrieve workspace chunks before prompting
    # Surfaces this operation may be invoked from (default: all). Intersected with the
    # workspace's invocation_sources policy at execute time.
    invocation_sources: tuple[str, ...] = INVOCATION_SOURCES
    # Write-back field map for entries: {output_field: entry_target}. entry_target is a
    # top-level column ("summary"/"title"/"description") or a "data_json.<key>" /
    # "metadata_json.<key>" path. Empty → this op only proposes (never applies).
    writeback: dict = {}

    @abstractmethod
    def build_prompt(self, input: dict, ctx: OperationContext) -> list[Message]:
        """Construct the message list to send to the provider."""
        ...

    def info(self) -> dict:
        return {
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "min_role": self.min_role,
            "entity_types": self.entity_types,
            "requires_vision": self.requires_vision,
            "invocation_sources": list(self.invocation_sources),
        }
