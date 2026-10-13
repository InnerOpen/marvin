"""Schemas for the platform's character library (admin: /api/admin/character-packs)."""

from datetime import datetime

from pydantic import Field

from marvin.schemas._marvin import _MarvinModel
from marvin.schemas.group.ai_settings import AssistantCharacter, AssistantCharacterUpload


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


class CharacterPackUploadRead(CharacterPackRead, AssistantCharacterUpload):
    """A pack just created or re-uploaded, with what the upload skipped."""


class CharacterPackUpdate(_MarvinModel):
    name: str = Field(min_length=1, max_length=120)
