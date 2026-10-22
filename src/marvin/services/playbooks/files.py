"""A Playbook's reference files: assets linked to the Playbook entry whose junction ``role`` is the file's relative path
(``references/tone.md``). ``attach_reference`` / ``reference_files`` / ``remove_reference`` manage them and
``published_playbook_file`` is the one place that says which one an agent may read. No column of its own: the junction
already has ``role``, and the existing attach/detach tools and routes keep working with it.

An imported file is a ``playbook``-scope asset (services/assets/scope.py): out of the library and the asset tools, reachable
only through these paths."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass

from marvin.services.playbooks import PLAYBOOK_TYPE, PlaybookScope, find_published

PATH_MAX = 255
_MIME = {".md": "text/markdown", ".txt": "text/plain", ".json": "application/json", ".csv": "text/csv", ".yaml": "application/yaml"}
FILES_MAX = 100  # reference files per Playbook


class PlaybookFileError(ValueError):
    """A reference file that can't be attached; the message says why and is safe to show."""


def normalize_path(path) -> str:
    """A reference file's path as kept: relative, forward slashes, no ``.``/``..`` parts (``references/tone.md``).

    Raises PlaybookFileError for anything that could point outside the Playbook's own folder."""
    raw = str(path or "").strip()
    if not raw or len(raw) > PATH_MAX or "\\" in raw or "\x00" in raw or raw.startswith("/"):
        raise PlaybookFileError("A reference file's path is relative, like 'references/tone.md' (at most 255 characters).")
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise PlaybookFileError("A reference file's path stays inside the Playbook: no '..' and no leading '/'.")
    return "/".join(parts)


@dataclass(frozen=True)
class ReferenceFile:
    path: str
    asset_id: str
    name: str
    mime_type: str | None
    size: int


def _playbook_entry(session, group_id, entry_id):
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_types import EntryTypes

    return (
        session.query(Entries)
        .join(EntryTypes, Entries.entry_type_id == EntryTypes.id)
        .filter(Entries.id == entry_id, Entries.group_id == group_id, EntryTypes.group_id == group_id, EntryTypes.slug == PLAYBOOK_TYPE)
        .first()
    )


def _links(session, entry_id):
    """(junction, asset) pairs of a Playbook's reference files: live assets whose role is a valid path, by path."""
    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.platform.entry_assets import EntryAssets

    rows = (
        session.query(EntryAssets, Assets)
        .join(Assets, EntryAssets.asset_id == Assets.id)
        .filter(EntryAssets.entry_id == entry_id, Assets.trashed_at.is_(None), EntryAssets.role.isnot(None))
        .all()
    )
    found = []
    for link, asset in rows:
        try:
            found.append((normalize_path(link.role), link, asset))
        except PlaybookFileError:
            continue  # some other role ('hero'): not a reference file
    return sorted(found, key=lambda t: t[0])


def _file(path, asset) -> ReferenceFile:
    return ReferenceFile(path=path, asset_id=str(asset.id), name=asset.name, mime_type=asset.mime_type, size=int(asset.file_size or 0))


def reference_files(session, entry_id) -> list[ReferenceFile]:
    """A Playbook entry's reference files by path (not workspace-checked: callers hold an entry they may see)."""
    return [_file(path, asset) for path, _link, asset in _links(session, entry_id)]


def attach_reference(session, group_id, entry_id, asset_id, path) -> ReferenceFile:
    """Attach a workspace asset to a Playbook under ``path`` (committed). Linking the same asset again moves it to the new path.

    Raises PlaybookFileError: not a Playbook of this workspace, not a live asset of it, a bad or taken path, too many files."""
    import sqlalchemy as sa

    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.platform.entry_assets import EntryAssets

    clean = normalize_path(path)
    if _playbook_entry(session, group_id, entry_id) is None:
        raise PlaybookFileError("No such Playbook in this workspace.")
    asset = session.get(Assets, asset_id)
    if asset is None or str(asset.group_id) != str(group_id) or asset.trashed_at is not None:
        raise PlaybookFileError("No such asset in this workspace.")
    current = _links(session, entry_id)
    mine = next((link for _p, link, a in current if a.id == asset.id), None)
    if any(p == clean and a.id != asset.id for p, _l, a in current):
        raise PlaybookFileError(f"The Playbook already has a file at '{clean}'.")
    if mine is None and len(current) >= FILES_MAX:
        raise PlaybookFileError(f"A Playbook holds at most {FILES_MAX} reference files.")
    if mine is None:
        mine = session.query(EntryAssets).filter_by(entry_id=entry_id, asset_id=asset.id).first()  # linked, but not as a reference
    if mine is None:
        top = session.query(sa.func.max(EntryAssets.position)).filter(EntryAssets.entry_id == entry_id).scalar()
        mine = EntryAssets(entry_id=entry_id, asset_id=asset.id, position=0 if top is None else top + 1)
        session.add(mine)
    mine.role = clean
    session.commit()
    return _file(clean, asset)


def remove_reference(session, group_id, entry_id, path) -> bool:
    """Take the file at ``path`` off a Playbook (committed; the asset itself stays). False when there was none."""
    if _playbook_entry(session, group_id, entry_id) is None:
        return False
    try:
        wanted = normalize_path(path)
    except PlaybookFileError:
        return False
    for found, link, _asset in _links(session, entry_id):
        if found == wanted:
            session.delete(link)
            session.commit()
            return True
    return False


@dataclass(frozen=True)
class SystemFile:
    """A system Playbook's reference file: text from its package, not an asset."""

    path: str
    text: str

    @property
    def name(self) -> str:
        return posixpath.basename(self.path)


def _system_index(playbook) -> list[ReferenceFile]:
    return [
        ReferenceFile(path, "", posixpath.basename(path), _MIME.get(posixpath.splitext(path)[1].lower(), "text/plain"), len(text.encode()))
        for path, text in playbook.files
    ]


def published_playbook_files(session, group_id, name: str, scope: PlaybookScope | None = None) -> list[ReferenceFile] | None:
    """The reference-file index of a published Playbook by name (a system Playbook's too, for a run's ``scope``), or None when it
    isn't one (draft, other workspace, made up, or outside the ``scope`` the run has)."""
    found = find_published(session, group_id, name, scope)
    if found is None:
        return None
    return _system_index(found[0]) if found[1].is_system else reference_files(session, found[0].id)


def published_playbook_file(session, group_id, name: str, path: str, scope: PlaybookScope | None = None):
    """The asset at ``path`` of a published Playbook of this workspace (a ``SystemFile`` for a system Playbook), or None: a draft,
    another workspace's Playbook, one outside the ``scope``, a path it doesn't hold and a malformed path all look the same."""
    found = find_published(session, group_id, name, scope)
    if found is None:
        return None
    try:
        wanted = normalize_path(path)
    except PlaybookFileError:
        return None
    if found[1].is_system:
        text = found[0].file(wanted)
        return SystemFile(wanted, text) if text is not None else None
    for path_found, _link, asset in _links(session, found[0].id):
        if path_found == wanted and str(asset.group_id) == str(group_id):
            return asset
    return None
