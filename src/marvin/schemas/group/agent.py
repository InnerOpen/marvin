"""Schemas for workspace agents (see db/models/groups/agents.py and services/ai/agents.py)."""

import re
from typing import Literal

from pydantic import UUID4, ConfigDict, Field, field_validator

from marvin.schemas._marvin import _MarvinModel
from marvin.schemas.group.ai_settings import PERSONA_PROMPT_MAX_CHARS, AssistantCharacter, BubbleLines, MoodSettings, TonePreview
from marvin.services.ai.operations.base import INVOCATION_SOURCES
from marvin.services.ai.tones import SLUG_RE as TONE_SLUG_RE

AgentKind = Literal["persona", "model"]
PolicyValue = Literal["allow", "block", "ask"]  # ask = bound, but every call waits for the user (Ask threads)
# Built-in agents are code, not rows; a user-defined agent may not shadow them.
SYSTEM_AGENT_SLUGS = ("marvin", "ask", "builder", "chat")
# The permission matrix for outside assistants (MCP clients): a policy holder, not an agent anyone can run.
EXTERNAL_SLUG = "external"
RESERVED_AGENT_SLUGS = (*SYSTEM_AGENT_SLUGS, EXTERNAL_SLUG)
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")


def _check_register(v: str | None) -> str | None:
    """A tone slug's shape. Whether the workspace has that tone is checked on save (it needs the DB)."""
    if v is None:
        return None
    v = v.strip().lower()
    if not v:
        return None
    if not TONE_SLUG_RE.match(v):
        raise ValueError("default_register must be a tone slug (a-z, 0-9 and '-', at most 40 chars)")
    return v


def _check_sources(v: list[str] | None) -> list[str] | None:
    if v is None:
        return None
    bad = [s for s in v if s not in INVOCATION_SOURCES]
    if bad:
        raise ValueError(f"unknown sources {bad}; allowed: {list(INVOCATION_SOURCES)}")
    return list(dict.fromkeys(v))


def _clean_allowlist(v: list[str] | None) -> list[str] | None:
    if v is None:
        return None
    return list(dict.fromkeys(x.strip() for x in v if x and x.strip()))


class AgentPlaybooks(_MarvinModel):
    """Which Playbooks an agent may use. `names` null = every published one, a list = only those; `always` = up to three
    put in full in its system frame (they must be in `names`, published and not manual-only: checked on save)."""

    names: list[str] | None = Field(default=None, max_length=200)
    always: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("names", "always")
    @classmethod
    def _v_names(cls, v):
        if v is None:
            return None
        return list(dict.fromkeys(x.strip().lower() for x in v if x and x.strip()))

    def stored(self) -> dict | None:
        """As the column keeps it; None when it says nothing (all Playbooks, none always)."""
        return None if self.names is None and not self.always else {"names": self.names, "always": self.always}


class AgentBase(_MarvinModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    kind: AgentKind = "persona"
    system_prompt: str | None = Field(default=None, max_length=8000)
    model_override: str | None = Field(default=None, max_length=120)
    tool_allowlist: list[str] | None = Field(default=None, max_length=64)
    default_register: str | None = None
    min_role: int = Field(default=1, ge=1, le=5)
    sources: list[str] | None = None
    enabled: bool = True
    # Bind non-read-only tools (authoring, links, AI ops, external MCP)? Off by default; the caller
    # still needs AUTHOR+ for them to actually bind.
    allow_writes: bool = False
    # Check its work before it finishes: gaps Marvin sees and the Playbooks' "Done when" checklist go back to it
    # (services/ai/work_check.py). Off by default; optional on the wire (absent or null = off), so clients that don't know it
    # are unaffected.
    check_work: bool | None = None
    # Permission matrix overrides keyed by category id or tool name.
    tool_policy: dict[str, PolicyValue] | None = None
    icon: str | None = Field(default=None, max_length=16)
    suggestions: list[str] | None = Field(default=None, max_length=8)
    # When the router (marvin) should hand a question to this agent; shown on its roster line.
    handoff_hint: str | None = Field(default=None, max_length=300)
    # Its own Character (who it is and how it speaks) in place of the workspace's, its bubble lines and its
    # mood settings (not active yet); unset → the workspace's. A library character fills these in when picked.
    persona_prompt: str | None = Field(default=None, max_length=PERSONA_PROMPT_MAX_CHARS)
    bubble_lines: BubbleLines | None = None
    mood: MoodSettings | None = None
    playbooks: AgentPlaybooks | None = None

    @field_validator("default_register")
    @classmethod
    def _v_register(cls, v):
        return _check_register(v)

    @field_validator("sources")
    @classmethod
    def _v_sources(cls, v):
        return _check_sources(v)

    @field_validator("tool_allowlist")
    @classmethod
    def _v_allowlist(cls, v):
        return _clean_allowlist(v)


class AgentCreate(AgentBase):
    slug: str

    @field_validator("slug")
    @classmethod
    def _slug_valid(cls, v: str) -> str:
        v = v.strip().lower()
        if not SLUG_RE.match(v):
            raise ValueError("slug must be 2-64 chars of a-z, 0-9 and '-', starting with a letter or digit")
        if v in RESERVED_AGENT_SLUGS:
            raise ValueError(f"'{v}' is a built-in agent; pick another slug")
        return v


class AgentUpdate(_MarvinModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    kind: AgentKind | None = None
    system_prompt: str | None = Field(default=None, max_length=8000)
    model_override: str | None = Field(default=None, max_length=120)
    tool_allowlist: list[str] | None = None
    default_register: str | None = None
    min_role: int | None = Field(default=None, ge=1, le=5)
    sources: list[str] | None = None
    enabled: bool | None = None
    allow_writes: bool | None = None
    check_work: bool | None = None
    tool_policy: dict[str, PolicyValue] | None = None
    icon: str | None = Field(default=None, max_length=16)
    suggestions: list[str] | None = Field(default=None, max_length=8)
    handoff_hint: str | None = Field(default=None, max_length=300)
    persona_prompt: str | None = Field(default=None, max_length=PERSONA_PROMPT_MAX_CHARS)
    bubble_lines: BubbleLines | None = None
    mood: MoodSettings | None = None
    playbooks: AgentPlaybooks | None = None

    @field_validator("default_register")
    @classmethod
    def _v_register(cls, v):
        return _check_register(v)

    @field_validator("sources")
    @classmethod
    def _v_sources(cls, v):
        return _check_sources(v)

    @field_validator("tool_allowlist")
    @classmethod
    def _v_allowlist(cls, v):
        return _clean_allowlist(v)


class AgentRead(AgentBase):
    id: UUID4 | None = None  # system agents have no row
    slug: str
    is_system: bool = False
    # A built-in agent whose permission matrix this workspace changed: `tool_policy` is the effective (merged)
    # matrix. Reset with DELETE /ai/agents/{slug}/tool-policy (or PATCH `tool_policy: null`).
    tool_policy_overridden: bool = False
    # The bubble's character while this agent talks (a library pack resolved to its states); None → the
    # workspace's. Set through /ai/agents/{slug}/character; see services/ai/character.py.
    character: AssistantCharacter | None = None
    # Where the bubble lines came from: "character" (a library pack's), "generated" or "edited"; None = none.
    bubble_lines_source: str | None = None

    model_config = ConfigDict(from_attributes=True)


class AgentPromptPreviewRequest(AgentUpdate):
    """The Edit form's unsaved values for a prompt preview; anything left out is the stored agent's."""


class AgentDefinitionPreviewRequest(AgentBase):
    """A whole agent not saved yet (the New form's create payload) for a prompt preview. The slug is
    optional and unchecked: nothing is stored, and it only keeps the agent off its own roster."""

    slug: str | None = None


class AgentLinesRequest(_MarvinModel):
    """The Edit form's unsaved Character and name to write bubble lines from; one left out is the stored one."""

    name: str | None = Field(default=None, max_length=120)
    persona_prompt: str | None = Field(default=None, max_length=PERSONA_PROMPT_MAX_CHARS)


class AgentToolCategory(_MarvinModel):
    id: str
    label: str
    count: int


class AgentPromptPreview(_MarvinModel):
    """The system prompt a run of this agent sends, in labelled parts, assembled by the run's own code.

    Leaves out what only a run knows: the "what the user is looking at" block, the conversation, and the
    tool definitions themselves (summarised as counts per permission-matrix category).
    """

    system: str  # the whole system prompt, in order
    tokens: int  # rough estimate of `system`
    kind: AgentKind
    workspace: str = ""  # from Marvin: the workspace preamble (persona agents only; it names the bound tools)
    instructions: str  # from the agent: its own instructions, or its kind's default
    default_instructions: bool  # `instructions` is the default (the agent has none of its own)
    tone: TonePreview  # the Character / tone section, as the tone preview shows it
    tone_source: Literal["agent", "workspace"]  # the agent's default tone, or the workspace default
    roster: str = ""  # the agents it may hand off or refer to, when it can
    playbooks_warning: str | None = None  # the "always load" Playbooks are long (they ride along with every run)
    tool_count: int = 0
    ask_first_count: int = 0  # of those, the ones that pause the run for approval
    tool_categories: list[AgentToolCategory] = Field(default_factory=list)
