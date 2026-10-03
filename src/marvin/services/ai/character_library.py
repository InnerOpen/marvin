"""The platform's character library: bubble-character packs a platform admin uploads once, for any
workspace or agent to pick instead of uploading its own (db/models/platform/character_packs.py).

Plugins and shared assets are installed site-wide by a platform admin, and workspaces only choose. So a
pack's files belong to no workspace: assets are workspace-scoped (every asset row has a group), and a
pack shared by all of them can't be one workspace's asset — deleting that workspace would take the pack
from everyone. They go through the same storage provider as assets, under a prefix of their own
(LIBRARY_STORAGE_PREFIX/<pack id>/…), and are loaded by the provider's public URL exactly as asset
files are (local storage: the /assets static mount; S3: the bucket URL).

A workspace's or agent's character that uses a pack is stored as {"library": "<pack id>"} and resolved
here to the pack's states whenever it's read, so renaming a pack or re-picking its animations reaches
everyone using it. A pack in use can't be deleted: pack_usage lists who would lose it.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from marvin.services.ai.character import LIBRARY_KEY, CharacterError, CharacterImage, library_ref

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from marvin.db.models.platform.character_packs import CharacterPackModel
    from marvin.services.storage.base_provider import BaseStorageProvider

# Never a workspace's slug: workspace keys are "<slug>/assets/…", and slugs don't start with "_".
LIBRARY_STORAGE_PREFIX = "_platform/character-packs"
MAX_PACK_SLUG = 64
DEFAULT_PACK_SLUG = "character"


@dataclass
class LibraryFileStore:
    """A library pack's files, under the pack's own storage prefix."""

    storage: BaseStorageProvider
    pack_id: str
    id_field = "key"

    @property
    def prefix(self) -> str:
        return f"{LIBRARY_STORAGE_PREFIX}/{self.pack_id}/"

    def put(self, image: CharacterImage, name: str, slug: str) -> dict:
        key = f"{self.prefix}{slug}-{name}"
        self.storage.put(storage_key=key, file_data=io.BytesIO(image.data), content_type=image.mime_type)
        return {"key": key, "url": self.storage.get_public_url(key)}

    def delete(self, file_id: str) -> None:
        # Keys come from the pack's stored JSON, never a request — but a pack only ever deletes its own.
        if file_id.startswith(self.prefix):
            self.storage.delete(file_id)


def library_store(pack_id: str, storage: BaseStorageProvider | None = None) -> LibraryFileStore:
    if storage is None:
        from marvin.services.storage.provider_factory import get_storage_provider

        storage = get_storage_provider()
    return LibraryFileStore(storage=storage, pack_id=str(pack_id))


# --- reading the library --------------------------------------------------------------------------


def list_packs(session: Session) -> list[CharacterPackModel]:
    from marvin.db.models.platform.character_packs import CharacterPackModel

    return session.query(CharacterPackModel).order_by(CharacterPackModel.name, CharacterPackModel.slug).all()


def get_pack(session: Session, ref: str | None) -> CharacterPackModel | None:
    """The pack `ref` names — its id, or its slug."""
    from marvin.db.models.platform.character_packs import CharacterPackModel

    ref = (ref or "").strip()
    if not ref:
        return None
    try:
        pack_id = uuid.UUID(ref)
    except ValueError:
        return session.query(CharacterPackModel).filter_by(slug=ref.lower()).first()
    return session.get(CharacterPackModel, pack_id)


def library_reference(session: Session, ref: str | None) -> dict:
    """A character pointing at the pack `ref` names (id or slug), by id; CharacterError if there's none."""
    pack = get_pack(session, ref)
    if pack is None:
        raise CharacterError(f"there's no character called {ref!r} in the library")
    return {LIBRARY_KEY: str(pack.id)}


def pack_character(pack: CharacterPackModel) -> dict:
    """A pack as a workspace or agent sees it: its states, under its id and name — not its files, which
    only the library edits."""
    return {LIBRARY_KEY: str(pack.id), "name": pack.name, "states": dict((pack.pack or {}).get("states") or {}), "files": []}


def resolve(session: Session, character: dict | None, packs: dict[str, CharacterPackModel | None] | None = None) -> dict | None:
    """The character as it plays: an own pack as stored; a library reference as that pack's states
    (None if the pack is gone). `packs` caches lookups across several calls (listing agents)."""
    ref = library_ref(character)
    if ref is None:
        return character or None
    if packs is None:
        packs = {}
    if ref not in packs:
        packs[ref] = get_pack(session, ref)
    pack = packs[ref]
    return pack_character(pack) if pack is not None else None


def agent_character_states(session: Session, group_id) -> dict[str, dict]:
    """{agent slug: states} for the workspace's agents that have a character of their own — what the
    bubble swaps to on `/use` or while a hand-off works (the rest play the workspace's)."""
    from marvin.db.models.groups.agents import WorkspaceAgentModel

    rows = session.query(WorkspaceAgentModel.slug, WorkspaceAgentModel.character).filter(
        WorkspaceAgentModel.group_id == group_id, WorkspaceAgentModel.character.isnot(None)
    )
    packs: dict[str, CharacterPackModel | None] = {}
    resolved = ((slug, resolve(session, character, packs)) for slug, character in rows)
    return {slug: character["states"] for slug, character in resolved if character and character.get("states")}


# --- managing it ----------------------------------------------------------------------------------


def unique_slug(session: Session, name: str) -> str:
    """A slug for a new pack from its name, numbered when taken."""
    from slugify import slugify

    from marvin.db.models.platform.character_packs import CharacterPackModel

    base = slugify(name, max_length=MAX_PACK_SLUG - 4) or DEFAULT_PACK_SLUG
    taken = {s for (s,) in session.query(CharacterPackModel.slug).filter(CharacterPackModel.slug.like(f"{base}%"))}
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug


def pack_usage(session: Session, pack_id: str) -> list[dict]:
    """Every workspace and agent whose character is this pack: [{workspace_id, workspace, agent}],
    agent None for a workspace's own bubble character."""
    import sqlalchemy as sa

    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.agents import WorkspaceAgentModel
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    pack_id = str(pack_id)

    def referencing(column):
        # The text match only narrows the scan; library_ref decides.
        return [column.isnot(None), sa.cast(column, sa.String).contains(pack_id)]

    users: list[tuple] = []
    for row in session.query(WorkspaceAISettingsModel).filter(*referencing(WorkspaceAISettingsModel.assistant_character)):
        if library_ref(row.assistant_character) == pack_id:
            users.append((row.group_id, None))
    for row in session.query(WorkspaceAgentModel).filter(*referencing(WorkspaceAgentModel.character)):
        if library_ref(row.character) == pack_id:
            users.append((row.group_id, row.slug))
    names = dict(session.query(Groups.id, Groups.name).filter(Groups.id.in_({g for g, _ in users}))) if users else {}
    return [{"workspace_id": str(g), "workspace": names.get(g) or str(g), "agent": agent} for g, agent in users]
