"""The platform's character library: bubble-character packs a platform admin uploads once, for any
workspace or agent to pick instead of uploading its own (db/models/platform/character_packs.py).

Plugins and shared assets are installed site-wide by a platform admin, and workspaces only choose. So a
pack's files belong to no workspace: assets are workspace-scoped (every asset row has a group), and a
pack shared by all of them can't be one workspace's asset — deleting that workspace would take the pack
from everyone. They go to the provider new uploads go to (Admin → Storage), under a prefix of their own
(LIBRARY_STORAGE_PREFIX/<pack id>/…), and are loaded by the provider's public URL exactly as asset
files are (local storage: the /assets static mount; S3: the bucket's public URL). Like an asset row,
each file records the provider it lives in ("provider"; a file without one predates that and is
local), so switching providers or moving files never breaks a pack.

A workspace's or agent's character that uses a pack is stored as {"library": "<pack id>"} and resolved
here to the pack's states whenever it's read, so renaming a pack or re-picking its animations reaches
everyone using it. A pack in use can't be deleted: pack_usage lists who would lose it.
"""

from __future__ import annotations

import io
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit

from marvin.services.ai.character import LIBRARY_KEY, CharacterError, CharacterImage, library_ref

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from marvin.db.models.platform.character_packs import CharacterPackModel
    from marvin.services.storage.base_provider import BaseStorageProvider

logger = logging.getLogger(__name__)

# Never a workspace's slug: workspace keys are "<slug>/assets/…", and slugs don't start with "_".
LIBRARY_STORAGE_PREFIX = "_platform/character-packs"
MAX_PACK_SLUG = 64
DEFAULT_PACK_SLUG = "character"
LOCAL_PROVIDER = "local"


def library_file_provider(file: dict) -> str:
    """The provider a pack file lives in. Files stored before files recorded one are local: every
    environment stored on local disk until then."""
    return file.get("provider") or LOCAL_PROVIDER


@dataclass
class LibraryFileStore:
    """A library pack's files, under the pack's own storage prefix. New files go to ``storage`` (the
    provider uploads go to); each file is read and deleted from the provider it records."""

    storage: BaseStorageProvider
    pack_id: str
    id_field = "key"

    @property
    def prefix(self) -> str:
        return f"{LIBRARY_STORAGE_PREFIX}/{self.pack_id}/"

    def put(self, image: CharacterImage, name: str, slug: str) -> dict:
        from marvin.services.storage.provider_factory import provider_slug

        key = f"{self.prefix}{slug}-{name}"
        self.storage.put(storage_key=key, file_data=io.BytesIO(image.data), content_type=image.mime_type)
        return {"key": key, "url": self.storage.get_public_url(key), "provider": provider_slug(self.storage)}

    def storage_for(self, file: dict) -> BaseStorageProvider:
        from marvin.services.storage.provider_factory import provider_for, provider_slug

        slug = library_file_provider(file)
        return self.storage if slug == provider_slug(self.storage) else provider_for(slug)

    def delete(self, file: dict) -> None:
        # Keys come from the pack's stored JSON, never a request — but a pack only ever deletes its own.
        key = file.get("key") or ""
        if key.startswith(self.prefix):
            self.storage_for(file).delete(key)


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


def _current(session: Session | None, file: dict) -> tuple[str, str] | None:
    """(storage key, URL it is served at now) of a character file: an asset file by its row's provider,
    a library file by the provider it records. None when that can't be worked out (the stored URL stays)."""
    from marvin.services.storage.provider_factory import provider_for

    try:
        if file.get("assetId"):
            if session is None:
                return None
            from marvin.db.models.platform import Assets

            asset = session.get(Assets, uuid.UUID(str(file["assetId"])))
            return (asset.storage_key, provider_for(asset).get_public_url(asset.storage_key)) if asset is not None else None
        if file.get("key"):
            return file["key"], provider_for(library_file_provider(file)).get_public_url(file["key"])
    except Exception as e:  # a provider that's gone or misconfigured: keep serving the stored URL
        logger.debug(f"character file {file.get('name')!r}: no current URL ({e})")
    return None


def _names_key(url: str, key: str) -> bool:
    """Whether `url` is some provider's URL for `key`: its path (query string aside) ends in the key."""
    path = unquote(urlsplit(url).path)
    return path == key or path.endswith(f"/{key}")


def with_current_urls(character: dict | None, session: Session | None = None) -> dict | None:
    """`character` with each file's URL — and every state playing it — as the file is served now.

    A character stores its files' URLs as they were at upload; the file's provider decides where it is
    served today (an asset moved to another provider, a provider's public URL changed). A state plays a
    file when its URL is the file's stored URL or any URL for the file's key (one saved back from an
    earlier read). The stored JSON is never rewritten here: this returns a copy when anything differs."""
    if not character:
        return character
    files = character.get("files") or []
    current: list[tuple[str | None, str, str]] = []  # (stored URL, key, URL now)
    current_files = []
    for f in files:
        now = _current(session, f) if isinstance(f, dict) else None
        if now:
            current.append((f.get("url"), *now))
            if now[1] != f.get("url"):
                f = {**f, "url": now[1]}
        current_files.append(f)

    def playing(url: str) -> str:
        for stored, key, now in current:
            if url == stored or (isinstance(url, str) and _names_key(url, key)):
                return now
        return url

    states = {state: playing(url) for state, url in (character.get("states") or {}).items()}
    if current_files == files and states == (character.get("states") or {}):
        return character
    return {**character, "states": states, "files": current_files}


def pack_character(pack: CharacterPackModel) -> dict:
    """A pack as a workspace or agent sees it: its states, under its id and name — not its files, which
    only the library edits."""
    current = with_current_urls(pack.pack or {}) or {}
    return {LIBRARY_KEY: str(pack.id), "name": pack.name, "states": dict(current.get("states") or {}), "files": []}


def resolve(session: Session, character: dict | None, packs: dict[str, CharacterPackModel | None] | None = None) -> dict | None:
    """The character as it plays: an own pack as stored; a library reference as that pack's states
    (None if the pack is gone). `packs` caches lookups across several calls (listing agents)."""
    ref = library_ref(character)
    if ref is None:
        return with_current_urls(character, session) or None
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


def unlink_pack(session: Session, pack_id: str) -> int:
    """Take the pack away from every workspace and agent that uses it (they fall back: a workspace to its
    icon, an agent to the workspace's character). Library references hold no files, so nothing is
    deleted here. Returns how many were unlinked; the caller commits."""
    from marvin.db.models.groups.agents import WorkspaceAgentModel
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    pack_id = str(pack_id)
    unlinked = 0
    for model, attr in ((WorkspaceAISettingsModel, "assistant_character"), (WorkspaceAgentModel, "character")):
        column = getattr(model, attr)
        for row in session.query(model).filter(column.isnot(None)):
            if library_ref(getattr(row, attr)) == pack_id:
                setattr(row, attr, None)
                unlinked += 1
    return unlinked
