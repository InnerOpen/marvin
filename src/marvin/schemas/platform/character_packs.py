"""Schemas for the platform's character library (admin: /api/admin/character-packs)."""

from datetime import datetime

from pydantic import UUID4, Field

from marvin.schemas._marvin import _MarvinModel
from marvin.schemas.group.ai_settings import AssistantCharacter, AssistantCharacterUpload, CharacterPackPersona

__all__ = [
    "CharacterPackLinesRequest",
    "CharacterPackPersona",
    "CharacterPackRead",
    "CharacterPackUpdate",
    "CharacterPackUploadRead",
    "CharacterPackUser",
]


class CharacterPackUser(_MarvinModel):
    """A workspace — or one of its agents — whose character is the pack."""

    workspace_id: str
    workspace: str
    agent: str | None = None  # None: the workspace's own bubble character


class CharacterPackRead(AssistantCharacter):
    id: str
    slug: str
    name: str
    created_at: datetime | None = None
    used_by: list[CharacterPackUser] = []
    persona: CharacterPackPersona | None = None  # its character sheet; None: animations only


class CharacterPackUploadRead(CharacterPackRead, AssistantCharacterUpload):
    """A pack just created or re-uploaded, with what the upload skipped."""


class CharacterPackUpdate(_MarvinModel):
    """Either or both: a new name (its slug stays), and its character sheet (null clears it)."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    persona: CharacterPackPersona | None = None


class CharacterPackLinesRequest(_MarvinModel):
    """The character sheet's unsaved fields to write lines from; one left out is the stored one."""

    assistant_name: str | None = Field(default=None, max_length=120)
    persona_prompt: str | None = Field(default=None, max_length=8000)
    workspace_id: UUID4 | None = None
    """The workspace to bill the AI call to. Left out: the caller's current workspace; none of those: 409 no_workspace."""
