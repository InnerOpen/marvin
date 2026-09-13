"""Schemas for workspace agents (see db/models/groups/agents.py and services/ai/agents.py)."""

import re
from typing import Literal

from pydantic import UUID4, ConfigDict, Field, field_validator

from marvin.schemas._marvin import _MarvinModel
from marvin.services.ai.operations.base import INVOCATION_SOURCES

AgentKind = Literal["persona", "model"]
REGISTERS = ("auto", "professional", "playful")
# Built-in agents are code, not rows; a user-defined agent may not shadow them.
SYSTEM_AGENT_SLUGS = ("marvin", "ask", "chat")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")


def _check_register(v: str | None) -> str | None:
    if v is not None and v not in REGISTERS:
        raise ValueError(f"default_register must be one of {REGISTERS}")
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
        if v in SYSTEM_AGENT_SLUGS:
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

    model_config = ConfigDict(from_attributes=True)
