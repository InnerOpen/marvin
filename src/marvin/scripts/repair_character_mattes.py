"""Clear the solid backgrounds of bubble-character files stored before uploads did it themselves.

Uploads now make a file's opaque solid background ("matte") transparent (services/ai/character.py:
clear_matte); files already stored still show a box around the character. This runs the same clearing
over every stored file — the library's packs and each workspace's and agent's own upload — and, with
--apply, overwrites each changed file in place at its storage key, so every stored URL keeps working.
Browsers that cached a file may show the old one until a hard refresh.

    python -m marvin.scripts.repair_character_mattes            # dry run: list what would change
    python -m marvin.scripts.repair_character_mattes --apply    # write the changes
"""

from __future__ import annotations

import argparse
import io
import sys
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from marvin.services.ai.character import CharacterImage, clear_matte, library_ref, sniff_image

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from marvin.db.models.platform import Assets
    from marvin.services.storage.base_provider import BaseStorageProvider


@dataclass
class StoredFile:
    """One stored character file: whose it is, where it's kept, and its asset row when it's an asset."""

    owner: str
    name: str
    key: str
    asset: Assets | None = None


@dataclass
class Repair:
    """A file whose background was (or, in a dry run, would be) cleared; or why it couldn't be read."""

    owner: str
    name: str
    key: str
    before: int = 0
    after: int = 0
    error: str | None = None


def _library_files(session: Session) -> Iterator[StoredFile]:
    from marvin.services.ai.character_library import list_packs

    for pack in list_packs(session):
        for f in (pack.pack or {}).get("files") or []:
            if f.get("key"):
                yield StoredFile(owner=f"library pack {pack.slug}", name=f.get("name") or f["key"], key=f["key"])


def _own_characters(session: Session) -> Iterator[tuple[str, dict]]:
    """(owner, character) of every workspace and agent character that holds files of its own."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.agents import WorkspaceAgentModel
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    slugs = dict(session.query(Groups.id, Groups.slug))
    workspaces = session.query(WorkspaceAISettingsModel).filter(WorkspaceAISettingsModel.assistant_character.isnot(None))
    agents = session.query(WorkspaceAgentModel).filter(WorkspaceAgentModel.character.isnot(None))
    characters = [(f"workspace {slugs.get(row.group_id, row.group_id)}", row.assistant_character) for row in workspaces]
    characters += [(f"agent {row.slug} in {slugs.get(row.group_id, row.group_id)}", row.character) for row in agents]
    return ((owner, c) for owner, c in characters if isinstance(c, dict) and not library_ref(c))


def _asset_files(session: Session) -> Iterator[StoredFile]:
    from marvin.db.models.platform import Assets

    for owner, character in _own_characters(session):
        for f in character.get("files") or []:
            asset = session.get(Assets, uuid.UUID(f["assetId"])) if f.get("assetId") else None
            if asset is not None:
                yield StoredFile(owner=owner, name=f.get("name") or asset.original_filename, key=asset.storage_key, asset=asset)


def _repair(storage: BaseStorageProvider, file: StoredFile, apply: bool) -> Repair | None:
    """Clear one file's matte (writing it back when `apply`); None when it has none."""
    try:
        data = storage.get(file.key).read()
    except Exception as e:  # one unreadable file (gone, say) shouldn't stop the others' repair
        return Repair(owner=file.owner, name=file.name, key=file.key, error=f"couldn't read it: {e}")
    kind = sniff_image(data)
    fixed = clear_matte(CharacterImage(name=file.name, data=data, mime_type=kind[0], extension=kind[1])) if kind else None
    if fixed is None:
        return None
    if apply:
        stored = storage.put(storage_key=file.key, file_data=io.BytesIO(fixed.data), content_type=fixed.mime_type)
        if file.asset is not None:
            file.asset.file_size, file.asset.checksum = stored.size, stored.checksum or file.asset.checksum
    return Repair(owner=file.owner, name=file.name, key=file.key, before=len(data), after=len(fixed.data))


def repair_stored_mattes(session: Session, storage: BaseStorageProvider, apply: bool = False) -> list[Repair]:
    """Every stored character file with a solid background, cleared in place when `apply` (a dry run
    otherwise). Files a character references but storage can't give back are reported, not fatal."""
    repairs = []
    for file in [*_library_files(session), *_asset_files(session)]:
        repair = _repair(storage, file, apply)
        if repair is None:
            continue
        repairs.append(repair)
        if apply and file.asset is not None:
            session.commit()  # each file's size and checksum as soon as it's rewritten, should a later one fail
    return repairs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="overwrite the changed files (default: dry run)")
    args = parser.parse_args(argv)

    from marvin.db.db_setup import session_context
    from marvin.services.storage.provider_factory import get_storage_provider

    with session_context() as session:
        repairs = repair_stored_mattes(session, get_storage_provider(), apply=args.apply)
    for r in repairs:
        detail = r.error or f"{r.before:,} -> {r.after:,} bytes"
        sys.stdout.write(f"{r.owner}: {r.name} ({r.key}): {detail}\n")
    cleared = sum(1 for r in repairs if not r.error)
    verb = "Cleared" if args.apply else "Would clear (dry run; --apply to write)"
    sys.stdout.write(f"{verb} a solid background in {cleared} file(s).\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
