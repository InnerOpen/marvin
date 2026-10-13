"""Record where the drawing sits in each bubble-character file stored before uploads measured it.

Uploads now note each file's `inset` — the empty frame around the drawing on each side (services/ai/character.py:
measure_inset) — so a tucked bubble lines up the drawing, not the frame, with the screen edge (a peek's drawn ledge
lands on it). Files stored earlier have none, and their peeks come out by the whole frame. This measures every
stored file without one — the library's packs and each workspace's and agent's own upload — and, with --apply,
records it in the character's file list. The files themselves are only read.

    python -m marvin.scripts.measure_character_insets            # dry run: list what would be recorded
    python -m marvin.scripts.measure_character_insets --apply    # record it
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from marvin.services.ai.character import CharacterImage, library_ref, measure_inset, sniff_image

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from marvin.services.storage.base_provider import BaseStorageProvider


@dataclass
class Measured:
    """A file measured (or, in a dry run, that would be); or why it couldn't be."""

    owner: str
    name: str
    inset: dict | None = None
    error: str | None = None


def _characters(session: Session) -> Iterator[tuple[str, object, str]]:
    """(owner, row, attribute) of every character holding files of its own: library packs, workspaces, agents."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.agents import WorkspaceAgentModel
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.services.ai.character_library import list_packs

    for pack in list_packs(session):
        yield f"library pack {pack.slug}", pack, "pack"
    slugs = dict(session.query(Groups.id, Groups.slug))
    for row in session.query(WorkspaceAISettingsModel).filter(WorkspaceAISettingsModel.assistant_character.isnot(None)):
        yield f"workspace {slugs.get(row.group_id, row.group_id)}", row, "assistant_character"
    for row in session.query(WorkspaceAgentModel).filter(WorkspaceAgentModel.character.isnot(None)):
        yield f"agent {row.slug} in {slugs.get(row.group_id, row.group_id)}", row, "character"


def _read(session: Session, storage: BaseStorageProvider | None, file: dict) -> bytes:
    """A character file's bytes, from the provider it lives in (`storage`, when given, stands in for all)."""
    from marvin.db.models.platform import Assets
    from marvin.services.ai.character_library import library_file_provider
    from marvin.services.storage.provider_factory import provider_for

    if file.get("assetId"):
        asset = session.get(Assets, uuid.UUID(file["assetId"]))
        if asset is None:
            raise FileNotFoundError("its asset is gone")
        key, provider = asset.storage_key, asset.storage_provider
    else:
        key, provider = file["key"], library_file_provider(file)
    return (storage or provider_for(provider)).get(key).read()


def _measure(session: Session, storage: BaseStorageProvider | None, owner: str, file: dict) -> Measured:
    name = file.get("name") or "?"
    try:
        data = _read(session, storage, file)
    except Exception as e:  # one unreadable file (gone, say) shouldn't stop the rest
        return Measured(owner, name, error=f"couldn't read it: {e}")
    kind = sniff_image(data)
    inset = measure_inset(CharacterImage(name=name, data=data, mime_type=kind[0], extension=kind[1])) if kind else None
    return Measured(owner, name, inset=inset, error=None if inset else "nothing drawn, or not an image")


def measure_stored_insets(session: Session, storage: BaseStorageProvider | None = None, apply: bool = False) -> list[Measured]:
    """Every stored character file without an `inset`, measured; recorded in its character's file list when
    `apply` (a dry run otherwise). Each character is saved as soon as its files are measured."""
    measured: list[Measured] = []
    for owner, row, attr in _characters(session):
        character = getattr(row, attr)
        if not isinstance(character, dict) or library_ref(character):
            continue
        files, changed = [], False
        for file in character.get("files") or []:
            if isinstance(file, dict) and not file.get("inset"):
                result = _measure(session, storage, owner, file)
                measured.append(result)
                if result.inset:
                    file, changed = {**file, "inset": result.inset}, True
            files.append(file)
        if changed and apply:
            setattr(row, attr, {**character, "files": files})  # a new dict: the JSON column sees the change
            session.commit()
    return measured


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="record the insets (default: dry run)")
    args = parser.parse_args(argv)

    from marvin.db.db_setup import session_context

    with session_context() as session:
        measured = measure_stored_insets(session, apply=args.apply)
    for m in measured:
        detail = m.error or ", ".join(f"{side} {share:.0%}" for side, share in (m.inset or {}).items())
        sys.stdout.write(f"{m.owner}: {m.name}: {detail}\n")
    done = sum(1 for m in measured if m.inset)
    verb = "Recorded" if args.apply else "Would record (dry run; --apply to write)"
    sys.stdout.write(f"{verb} where the drawing sits in {done} file(s).\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
