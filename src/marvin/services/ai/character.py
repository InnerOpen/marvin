"""The Ask Marvin bubble's animated character (AI settings → Persona → Bubble character).

A character is a set of animations, one per bubble state, shown instead of the round icon button. An
admin uploads a pack — a .zip or loose image files — and each file's name picks its state through the
alias table below, so a pack drawn for another tool ("waving.gif", "running-left.gif") works as is.
Files whose names match nothing are kept too, unassigned, so the settings page can assign any of them
to any state by hand (assign_state).

Every accepted file is stored as a workspace asset, and the bubble loads it by the asset's public URL
— the same URL the admin's asset pages display, served without auth (local storage: the /assets
static mount, proxied by the frontend; S3: the bucket URL). The stored JSON remembers which assets the
character created, so replacing or removing it deletes exactly those.

Stored on WorkspaceAISettingsModel.assistant_character as
    {"states": {state: url}, "files": [{"name": "waving.gif", "assetId": "…", "url": "…"}]}
The state machine that plays these lives in the frontend (frontend/src/lib/marvin/character.ts); the
canonical keys must match.

Only GIF, WebP and PNG/APNG are accepted, recognised by their magic bytes — never by name, and never
SVG, which is a script vector when served from the app's own origin. Zips are read in memory with
entry-count and size caps checked from the archive's directory before anything is decompressed, and
enforced again while reading; entry names are only ever used to pick a state, never as paths.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from fastapi import UploadFile
from pydantic import UUID4

from marvin.services.ai.persona import url_problem

if TYPE_CHECKING:
    from marvin.services.assets.asset_storage_service import AssetStorageService

IDLE_STATE = "idle"
CHARACTER_STATES = (
    IDLE_STATE,
    "idle_variant",  # played now and then while idle
    "greeting",  # the panel opens
    "thinking",  # a message was sent; no agent step yet
    "working",  # agent steps are running
    "waiting",  # the run is parked on the user's approval
    "success",  # the answer arrived
    "error",  # the run failed
    "move_left",  # being dragged leftwards
    "move_right",  # being dragged rightwards
)

# Filename stems (see normalize_stem) each state answers to, best first: when two files claim the same
# state, the one matching the earlier alias wins and the other stays unassigned.
STATE_ALIASES: dict[str, tuple[str, ...]] = {
    IDLE_STATE: ("idle",),
    "idle_variant": ("look-loop", "look", "look-around"),
    "greeting": ("waving", "wave", "greeting"),
    "thinking": ("review", "thinking", "think"),
    "working": ("running", "working", "run"),
    "waiting": ("waiting", "wait"),
    # idle-jump-idle is a jump framed by idle frames: a fair success, but a plain jump reads better.
    "success": ("jumping", "jump", "success", "idle-jump-idle"),
    "error": ("failed", "error", "fail"),
    "move_left": ("running-left", "move-left", "walk-left"),
    "move_right": ("running-right", "move-right", "walk-right"),
}
_ALIAS_INDEX = {alias: (state, rank) for state, aliases in STATE_ALIASES.items() for rank, alias in enumerate(aliases)}

MEGABYTE = 1024 * 1024
MAX_CHARACTER_FILES = 20
MAX_CHARACTER_FILE_BYTES = 5 * MEGABYTE
MAX_CHARACTER_TOTAL_BYTES = 20 * MEGABYTE
# A zip of MAX_CHARACTER_TOTAL_BYTES of already-compressed images is about that size again.
MAX_CHARACTER_UPLOAD_BYTES = MAX_CHARACTER_TOTAL_BYTES

ASSET_PURPOSE = "assistant-character"

_GIF_MAGIC = (b"GIF87a", b"GIF89a")
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_RIFF_MAGIC, _WEBP_MAGIC = b"RIFF", b"WEBP"
_WEBP_TAG_OFFSET = 8  # "RIFF" + a 4-byte length, then "WEBP"
_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06")  # a local file header, or an empty archive's end record
_JUNK_DIRS = {"__MACOSX"}
_DOT_DIRS = {".", ".."}


class CharacterError(ValueError):
    """An upload or assignment that can't become the bubble's character; the message says why."""


@dataclass
class CharacterImage:
    """One accepted animation: its display name (the file's base name) and verified image bytes."""

    name: str
    data: bytes
    mime_type: str
    extension: str


@dataclass
class CharacterPlan:
    """What an upload amounts to before anything is stored."""

    images: list[CharacterImage]
    states: dict[str, CharacterImage]
    ignored: list[str] = field(default_factory=list)
    # No file was named for idle, so the first image stands in until the admin picks one.
    idle_guessed: bool = False
    # The pack's display name: a zip's own name; None for loose files.
    name: str | None = None


# --- naming -------------------------------------------------------------------------------------


def _path(name: str) -> PurePosixPath:
    """A file or zip entry name as a path, whichever slash it was written with — for reading, never opening."""
    return PurePosixPath(name.replace("\\", "/"))


def normalize_stem(filename: str) -> str:
    """The part of a file name aliases match: base name without extension, lowercased, `_`/space → `-`."""
    return _path(filename).stem.strip().lower().replace("_", "-").replace(" ", "-")


def state_for(filename: str) -> tuple[str, int] | None:
    """(state, alias rank — lower is better) that `filename` answers to, or None."""
    return _ALIAS_INDEX.get(normalize_stem(filename))


def sniff_image(data: bytes) -> tuple[str, str] | None:
    """(mime type, extension) when `data` starts like a GIF, PNG/APNG or WebP; None otherwise."""
    if data.startswith(_GIF_MAGIC):
        return "image/gif", "gif"
    if data.startswith(_PNG_MAGIC):
        return "image/png", "png"
    if data.startswith(_RIFF_MAGIC) and data[_WEBP_TAG_OFFSET : _WEBP_TAG_OFFSET + len(_WEBP_MAGIC)] == _WEBP_MAGIC:
        return "image/webp", "webp"
    return None


def is_zip(data: bytes) -> bool:
    return data.startswith(_ZIP_MAGIC)


# --- reading an upload --------------------------------------------------------------------------


class _Budget:
    """The caps shared by every file in one upload, zipped or loose."""

    def __init__(self) -> None:
        self.files = 0
        self.total = 0

    def check_ahead(self, entries: Iterable[tuple[str, int]]) -> None:
        """Raise if taking every (name, size) in `entries` would break a cap, without taking them."""
        trial = _Budget()
        trial.files, trial.total = self.files, self.total
        for name, size in entries:
            trial.take(name, size)

    def take(self, name: str, size: int) -> None:
        self.files += 1
        self.total += size
        if self.files > MAX_CHARACTER_FILES:
            raise CharacterError(f"a character has at most {MAX_CHARACTER_FILES} files")
        if size > MAX_CHARACTER_FILE_BYTES:
            raise CharacterError(f"{name} is over {MAX_CHARACTER_FILE_BYTES // MEGABYTE} MB")
        if self.total > MAX_CHARACTER_TOTAL_BYTES:
            raise CharacterError(f"a character is at most {MAX_CHARACTER_TOTAL_BYTES // MEGABYTE} MB in all")


def _is_junk(entry_name: str) -> bool:
    """Hidden files and macOS resource forks: archive debris, not animations."""
    # ".." isn't hidden, just a (harmless — names never become paths) attempt to climb out.
    return any(part in _JUNK_DIRS or (part.startswith(".") and part not in _DOT_DIRS) for part in _path(entry_name).parts)


def _zip_members(data: bytes, budget: _Budget) -> Iterator[tuple[str, bytes]]:
    """(base name, bytes) of each real file in the zip, within the caps; names are never paths."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise CharacterError("the .zip couldn't be read") from None
    with archive:
        members = [i for i in archive.infolist() if not i.is_dir() and not _is_junk(i.filename)]
        # Refuse a bomb from its directory alone, before decompressing a single byte of it.
        budget.check_ahead((info.filename, info.file_size) for info in members)
        for info in members:
            try:
                with archive.open(info) as fh:
                    # Read one byte past the cap, so a lying directory entry still can't get past it.
                    content = fh.read(MAX_CHARACTER_FILE_BYTES + 1)
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as e:
                raise CharacterError(f"{info.filename} couldn't be read from the .zip ({e})") from None
            budget.take(info.filename, len(content))
            yield _path(info.filename).name, content


def read_uploads(uploads: Iterable[tuple[str, bytes]]) -> tuple[list[CharacterImage], list[str]]:
    """(accepted images, ignored file names) from uploaded files, expanding any zips among them."""
    budget = _Budget()
    images: list[CharacterImage] = []
    ignored: list[str] = []
    seen: set[str] = set()

    def files() -> Iterator[tuple[str, bytes]]:
        for name, data in uploads:
            if is_zip(data):
                yield from _zip_members(data, budget)
            else:
                budget.take(name, len(data))
                yield _path(name).name, data

    for name, data in files():
        kind = sniff_image(data)
        # A second file of the same name couldn't be told apart from the first in the picker.
        if kind is None or name.lower() in seen:
            ignored.append(name)
            continue
        seen.add(name.lower())
        images.append(CharacterImage(name=name, data=data, mime_type=kind[0], extension=kind[1]))
    return images, ignored


def plan_character(uploads: list[tuple[str, bytes]]) -> CharacterPlan:
    """Read an upload and give each state its best-named file. Raises CharacterError when unusable."""
    images, ignored = read_uploads(uploads)
    if not images:
        raise CharacterError("no GIF, WebP or PNG images found — a character needs at least an idle animation")
    best: dict[str, tuple[int, CharacterImage]] = {}
    for image in images:
        match = state_for(image.name)
        if match and (match[0] not in best or match[1] < best[match[0]][0]):
            best[match[0]] = (match[1], image)
    states = {state: image for state, (_, image) in best.items()}
    idle_guessed = IDLE_STATE not in states
    if idle_guessed:
        states[IDLE_STATE] = images[0]
    zips = [_path(name).stem for name, data in uploads if is_zip(data)]
    return CharacterPlan(images=images, states=states, ignored=ignored, idle_guessed=idle_guessed, name=zips[0] if zips else None)


# --- the stored character -----------------------------------------------------------------------


def missing_states(character: dict | None) -> list[str]:
    """Canonical states the character has no animation for (the bubble falls back for these)."""
    states = (character or {}).get("states") or {}
    return [s for s in CHARACTER_STATES if s not in states]


def character_asset_ids(character: dict | None) -> list[str]:
    return [f["assetId"] for f in (character or {}).get("files") or [] if f.get("assetId")]


def character_problem(character: dict | None) -> str | None:
    """Why `character` can't be saved as the bubble's character, or None when it can (None = remove it).

    Only "states" is the caller's to set; the file list is the server's record of what it stored.
    """
    if character is None:
        return None
    states = character.get("states") if isinstance(character, dict) else None
    if not isinstance(states, dict):
        return 'a character is {"states": {state: image URL}}'
    unknown = sorted(set(states) - set(CHARACTER_STATES))
    if unknown:
        return f"unknown character state(s): {', '.join(unknown)} — use {', '.join(CHARACTER_STATES)}"
    if not states.get(IDLE_STATE):
        return "a character needs an idle animation"
    for state, url in states.items():
        problem = url_problem(url.strip()) if isinstance(url, str) else "an image must be a URL"
        if problem:
            return f"{state}: {problem}"
    return None


def assign_state(character: dict | None, state: str, file: str | None) -> dict:
    """`character` with `state` playing `file` (a name or asset id from its files), or cleared when None."""
    if not character:
        raise CharacterError("there's no character to change — upload one first")
    if state not in CHARACTER_STATES:
        raise CharacterError(f"unknown character state: {state} — use {', '.join(CHARACTER_STATES)}")
    states = dict(character.get("states") or {})
    if file is None:
        if state == IDLE_STATE:
            raise CharacterError("idle can be changed but not cleared — every other state falls back to it")
        states.pop(state, None)
    else:
        match = next((f for f in character.get("files") or [] if file in (f.get("name"), f.get("assetId"))), None)
        if match is None:
            raise CharacterError(f"{file} isn't one of this character's files")
        states[state] = match["url"]
    return {**character, "states": states}


def store_character(asset_service: AssetStorageService, group_id: UUID4, user_id: UUID4, plan: CharacterPlan) -> dict:
    """Store each planned image as a workspace asset; the new character JSON. All-or-nothing."""
    batch = uuid.uuid4().hex[:8]
    files: list[dict] = []
    try:
        for index, image in enumerate(plan.images):
            # Stored under a name of our making: the upload's own name only labels the asset.
            stored_name = f"{normalize_stem(image.name) or 'frame'}.{image.extension}"
            asset = asset_service.upload_asset(
                upload_file=UploadFile(file=io.BytesIO(image.data), filename=stored_name),
                upload_request=_upload_request(batch, index, image.name),
                group_id=group_id,
                user_id=user_id,
            )
            files.append({"name": image.name, "assetId": str(asset.id), "url": asset.public_url})
    except Exception:
        delete_character_assets(asset_service, {"files": files})
        raise
    url_by_name = {f["name"]: f["url"] for f in files}  # names are unique within a character
    states = {state: url_by_name[image.name] for state, image in plan.states.items()}
    return {**({"name": plan.name} if plan.name else {}), "states": states, "files": files}


def _upload_request(batch: str, index: int, name: str):
    from marvin.schemas.platform.assets import AssetUploadRequest

    return AssetUploadRequest(
        slug=f"bubble-character-{batch}-{index:02d}",
        name=f"Bubble character — {name}",
        alt_text="",
        metadata_json={"purpose": ASSET_PURPOSE},
    )


def delete_character_assets(asset_service: AssetStorageService, character: dict | None, keep: Iterable[str] = ()) -> None:
    """Delete the assets `character` created, except those in `keep` (still in use by its successor)."""
    kept = set(keep)
    for asset_id in character_asset_ids(character):
        if asset_id not in kept:
            asset_service.delete_asset(uuid.UUID(asset_id))


def describe(character: dict | None) -> dict | None:
    """The character as the API returns it: its states and files, plus which states it lacks."""
    if not character:
        return None
    return {
        "name": character.get("name"),
        "states": character.get("states") or {},
        "files": character.get("files") or [],
        "missing": missing_states(character),
    }


def catalog() -> list[dict]:
    """The canonical states and the file names each answers to, for the settings page."""
    return [{"key": state, "aliases": list(STATE_ALIASES[state]), "required": state == IDLE_STATE} for state in CHARACTER_STATES]
