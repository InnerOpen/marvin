"""Move stored files between asset storage providers without an upload freeze.

``migrate(to=...)`` copies each file that lives elsewhere to the provider ``to``, checks the copy's
sha256 against the source bytes, and only then points the row at it (``storage_provider`` + the cached
``public_url``) in a short compare-and-set transaction (``… WHERE storage_provider = <the old one>``),
so an upload, edit or delete racing it is never overwritten. Character-library files (no asset row:
their pack's JSON names each file's provider) move the same way.

- **Idempotent and resumable:** a file already on the target with the right sha256 isn't uploaded
  again; a row already on the target isn't looked at. Interrupt it and run it again.
- **No freeze:** new uploads go to the provider an admin chose (Admin → Storage), so switch that first.
  Each pass re-reads what is left, and the run repeats passes until nothing is (stragglers uploaded to
  the old provider while it ran are caught by the next pass).
- **Never deletes the source copy.** Reads keep working from either side, and ``--to local`` (the
  rollback) finds the local copy still there. ``prune_local`` deletes local copies later, only for
  rows that live elsewhere and whose copy there matches the local bytes (downloaded and hashed again).

``rekey=True`` (``--rekey``) also moves every file whose key isn't opaque yet (services/storage/keys.py)
to one that is, within its provider or together with a move to ``to``: the same copy, verify and
compare-and-set, which now repoints ``storage_key`` too and records the old key in
``storage_key_aliases`` in the same transaction. The new key is derived from the row's id (a library
file's pack and old key), so an interrupted run makes the same key again and finds its copy there. The
old copy stays (old URLs keep working: ``/assets/<old key>`` serves it, then redirects once it is gone);
``prune_old`` (``--prune-old``) deletes it later, after checking the file's current copy matches it.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from . import provider_factory
from .registry import LOCAL

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from .base_provider import BaseStorageProvider

log = logging.getLogger(__name__)

CHUNK = 1024 * 1024
MAX_PASSES = 10
PRUNE_LOCAL = "prune-local"
PRUNE_OLD = "prune-old"


class MigrationError(RuntimeError):
    pass


@dataclass
class MigrationReport:
    to: str
    dry_run: bool = False
    passes: int = 0
    copied: int = 0
    copied_bytes: int = 0
    already_there: int = 0
    """Files the target already held with the right sha256 (an earlier, interrupted run)."""
    moved: int = 0
    """Asset rows now pointing at the target."""
    rekeyed: int = 0
    """Asset rows and library files given an opaque key (counted in ``moved`` / ``library_files`` too)."""
    rekey: bool = False
    library_files: int = 0
    """Character-library files now on the target."""
    raced: int = 0
    """Rows deleted or changed while their file was copied (left as they are)."""
    checksum_mismatches: int = 0
    """Rows whose stored checksum differs from their file's bytes (moved anyway: the copy matches the bytes)."""
    pruned: int = 0
    pruned_bytes: int = 0
    failures: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.to in (PRUNE_LOCAL, PRUNE_OLD):
            verb = "would delete" if self.dry_run else "deleted"
            what = "local copies" if self.to == PRUNE_LOCAL else "copies at old keys"
            return f"{self.to}: {verb} {self.pruned} {what} ({_mb(self.pruned_bytes)}), {len(self.failures)} failed"
        verb = "would copy" if self.dry_run else "copied"
        where = f"to {self.to}" if self.to else "in place"
        parts = [
            f"{where}{' + rekey' if self.rekey else ''}: {verb} {self.copied} ({_mb(self.copied_bytes)})",
            f"{self.already_there} already there",
            f"{self.moved} asset rows moved",
            f"{self.library_files} library files moved",
            *([f"{self.rekeyed} rekeyed"] if self.rekey else []),
            f"{self.raced} changed meanwhile",
            f"{len(self.failures)} failed",
            f"{self.passes} pass{'es' if self.passes != 1 else ''}",
        ]
        if self.checksum_mismatches:
            parts.append(f"{self.checksum_mismatches} stale row checksums")
        return ", ".join(parts)


def _mb(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB"


# --------------------------------------------------------------------------------------------------
# Copy + verify
# --------------------------------------------------------------------------------------------------


@contextmanager
def _staged(provider: BaseStorageProvider, key: str) -> Iterator[tuple[Path, str, int]]:
    """``key``'s bytes from ``provider`` in a temp file: (path, sha256, size)."""
    digest, size = hashlib.sha256(), 0
    with tempfile.TemporaryDirectory(prefix="marvin-migrate-") as tmp:
        path = Path(tmp) / "object"
        with provider.get(key) as src, path.open("wb") as out:
            while chunk := src.read(CHUNK):
                digest.update(chunk)
                size += len(chunk)
                out.write(chunk)
        yield path, digest.hexdigest(), size


def _download_sha256(provider: BaseStorageProvider, key: str) -> tuple[str, int]:
    with _staged(provider, key) as (_, sha, size):
        return sha, size


def copy_matches(target: BaseStorageProvider, key: str, sha256: str, size: int, strong: bool = False) -> bool:
    """Whether ``target`` holds ``key`` with exactly these bytes. ``strong`` downloads and hashes it;
    otherwise the provider's own sha256 is trusted (local hashes the file; the s3 plugin stores the
    sha256 of what it uploaded), falling back to a download when it can't say."""
    try:
        if strong:
            got_sha, got_size = _download_sha256(target, key)
        else:
            meta = target.get_metadata(key)
            got_size = meta.size
            got_sha = meta.checksum if meta.checksum_algorithm == "sha256" else target.checksum(key, "sha256")
            if got_sha is None:
                got_sha, got_size = _download_sha256(target, key)
    except FileNotFoundError:
        return False
    return got_size == size and got_sha == sha256


def copy_file(
    source: BaseStorageProvider,
    target: BaseStorageProvider,
    key: str,
    content_type: str | None,
    verify: bool,
    *,
    dest_key: str | None = None,
    metadata: dict | None = None,
) -> tuple[str, int, bool]:
    """Copy ``key`` (to ``dest_key``, default the same key) unless the target already has the same bytes
    there. ``metadata`` goes to the target's ``put`` (the object's Content-Disposition). Returns (sha256,
    size, copied). Raises ``MigrationError`` when the copy doesn't match the source after upload."""
    dest = dest_key or key
    with _staged(source, key) as (path, sha, size):
        if target.exists(dest) and copy_matches(target, dest, sha, size, strong=verify):
            return sha, size, False
        with path.open("rb") as fh:
            target.put(storage_key=dest, file_data=fh, content_type=content_type or "application/octet-stream", metadata=metadata)
        if not copy_matches(target, dest, sha, size, strong=verify):
            raise MigrationError(f"{dest}: the copy on the target doesn't match the source (sha256/size)")
        return sha, size, True


# --------------------------------------------------------------------------------------------------
# Asset rows
# --------------------------------------------------------------------------------------------------


@dataclass
class _Row:
    id: Any
    provider: str
    key: str
    checksum: str | None
    size: int
    mime_type: str | None
    group_id: Any = None
    original_filename: str | None = None
    created_at: Any = None


def _codes(session: Session, group_id: Any = None) -> dict[Any, str]:
    """{workspace id: storage code} of the workspaces that have assets (one that has none gets one)."""
    from marvin.db.models.platform import Assets

    from .keys import workspace_code

    q = session.query(Assets.group_id).distinct()
    if group_id is not None:
        q = q.filter(Assets.group_id == group_id)
    codes = {gid: workspace_code(session, gid) for (gid,) in q}
    session.commit()
    return codes


def _pending(session: Session, to: str | None, group_id: Any = None, codes: dict[Any, str] | None = None) -> list[_Row]:
    """Rows to move: those not on ``to``, and with ``codes`` (a rekey) those whose key isn't opaque under
    their workspace's code."""
    from marvin.db.models.platform import Assets

    from .keys import is_opaque

    q = session.query(
        Assets.id,
        Assets.storage_provider,
        Assets.storage_key,
        Assets.checksum,
        Assets.file_size,
        Assets.mime_type,
        Assets.group_id,
        Assets.original_filename,
        Assets.created_at,
    )
    if codes is None:
        q = q.filter(Assets.storage_provider != to)
    if group_id is not None:
        q = q.filter(Assets.group_id == group_id)
    rows = [_Row(*r) for r in q.order_by(Assets.created_at, Assets.id)]
    if codes is None:
        return rows
    return [r for r in rows if (to is not None and r.provider != to) or not is_opaque(r.key, codes.get(r.group_id))]


def _record_alias(session: Session, provider: str, old_key: str, current_key: str, asset_id: Any = None, pack_id: Any = None) -> None:
    from marvin.db.models.platform import StorageKeyAliasModel

    alias = session.query(StorageKeyAliasModel).filter_by(provider=provider, storage_key=old_key).first()
    if alias is None:
        session.add(
            StorageKeyAliasModel(session=session, provider=provider, storage_key=old_key, current_key=current_key, asset_id=asset_id, pack_id=pack_id)
        )
    else:  # the same old copy, pointed at again (can't happen with derived keys, but never two rows for one key)
        alias.current_key, alias.asset_id, alias.pack_id, alias.pruned_at = current_key, asset_id, pack_id, None


def _flip(session_factory: Callable, row: _Row, to: str, url: str | None, new_key: str | None = None) -> str:
    """Point the row at ``to`` (and ``new_key``, recording the old key as an alias) if it still lives
    where it did: "moved", "changed" (another provider or key now) or "gone" (deleted meanwhile)."""
    from marvin.db.models.platform import Assets

    values: dict[str, Any] = {"storage_provider": to, "public_url": url}
    if new_key and new_key != row.key:
        values["storage_key"] = new_key
    with session_factory() as session:
        result = session.execute(
            sa.update(Assets).where(Assets.id == row.id, Assets.storage_provider == row.provider, Assets.storage_key == row.key).values(**values)
        )
        if result.rowcount == 1:
            if "storage_key" in values:
                _record_alias(session, row.provider, row.key, new_key, asset_id=row.id)
            session.commit()
            return "moved"
        session.rollback()
        exists = session.query(Assets.id).filter(Assets.id == row.id).first() is not None
        return "changed" if exists else "gone"


def _row_key(row: _Row, codes: dict[Any, str] | None) -> str:
    """Where the row's file goes: its opaque key when rekeying one that has none yet, else its key."""
    from .keys import is_opaque, rekeyed

    if codes is None or is_opaque(row.key, codes.get(row.group_id)):
        return row.key
    return rekeyed(codes[row.group_id], row.key, f"asset:{row.id}", row.original_filename, row.mime_type, row.created_at)


def _migrate_row(session_factory: Callable, row: _Row, to: str, report: MigrationReport, verify: bool, codes: dict[Any, str] | None = None) -> None:
    from .keys import object_metadata

    source = provider_factory.provider_for(row.provider)
    target = provider_factory.provider_for(to)
    dest = _row_key(row, codes)
    sha, size, copied = copy_file(source, target, row.key, row.mime_type, verify, dest_key=dest, metadata=object_metadata(row.original_filename))
    if row.checksum and row.checksum != sha:
        report.checksum_mismatches += 1
        log.warning(
            "asset %s (%s): stored checksum %s… differs from the file's %s… (the copy matches the file)", row.id, row.key, row.checksum[:12], sha[:12]
        )
    outcome = _flip(session_factory, row, to, _url(to, dest, row.group_id), dest)
    if outcome == "moved":
        report.moved += 1
        report.rekeyed += dest != row.key
        report.copied += copied
        report.copied_bytes += size if copied else 0
        report.already_there += not copied
    else:
        report.raced += 1
        log.info("asset %s (%s): %s while copying; left as it is", row.id, row.key, "deleted" if outcome == "gone" else "changed")
        if outcome == "gone" and copied:
            target.delete(dest)  # the row went with its source file; don't leave a copy nobody owns


def _url(slug: str, key: str, group_id: Any = None) -> str | None:
    try:
        return provider_factory.public_url_for(slug, key, group_id)
    except Exception:
        return None


# --------------------------------------------------------------------------------------------------
# Character-library files
# --------------------------------------------------------------------------------------------------


def _pending_library(session: Session, to: str | None, rekey: bool = False) -> list[tuple[Any, dict]]:
    from marvin.services.ai.character_library import library_file_provider, list_packs

    from .keys import LIBRARY_CODE, is_opaque

    return [
        (pack.id, dict(f))
        for pack in list_packs(session)
        for f in (pack.pack or {}).get("files") or []
        if f.get("key") and ((to is not None and library_file_provider(f) != to) or (rekey and not is_opaque(f["key"], LIBRARY_CODE)))
    ]


def _flip_library(session_factory: Callable, pack_id: Any, file: dict, to: str, url: str | None, new_key: str | None = None) -> bool:
    """Record the file's new provider and key (and URL, and every state playing it) in the pack's JSON,
    if the pack still has that file where it was; a new key's old one is recorded as an alias."""
    from marvin.db.models.platform.character_packs import CharacterPackModel
    from marvin.services.ai.character_library import library_file_provider

    with session_factory() as session:
        pack = session.get(CharacterPackModel, pack_id)
        files = list((pack.pack or {}).get("files") or []) if pack else []
        for i, f in enumerate(files):
            if f.get("key") == file["key"] and library_file_provider(f) == library_file_provider(file):
                old_url = f.get("url")
                files[i] = {**f, "provider": to, **({"key": new_key} if new_key else {}), **({"url": url} if url else {})}
                states = {s: (url if url and u == old_url else u) for s, u in ((pack.pack or {}).get("states") or {}).items()}
                pack.pack = {**pack.pack, "files": files, "states": states}  # a new dict: JSON columns track assignment
                if new_key and new_key != file["key"]:
                    _record_alias(session, library_file_provider(file), file["key"], new_key, pack_id=pack_id)
                session.commit()
                return True
        return False


def _migrate_library_file(session_factory: Callable, pack_id: Any, file: dict, to: str | None, report: MigrationReport, verify: bool) -> None:
    from marvin.services.ai.character_library import library_download_name, library_file_provider

    from .keys import LIBRARY_CODE, is_opaque, object_metadata, rekeyed

    slug = library_file_provider(file)
    to = to or slug
    source, target = provider_factory.provider_for(slug), provider_factory.provider_for(to)
    # No row records its type, and local disk keeps none: the name says it (GIF/WebP/PNG).
    content_type = mimetypes.guess_type(file["key"])[0]
    dest = file["key"]
    if report.rekey and not is_opaque(dest, LIBRARY_CODE):
        dest = rekeyed(LIBRARY_CODE, file["key"], f"library:{pack_id}:{file['key']}", library_download_name(file), content_type)
    metadata = object_metadata(library_download_name(file))
    _, size, copied = copy_file(source, target, file["key"], content_type, verify, dest_key=dest, metadata=metadata)
    if _flip_library(session_factory, pack_id, file, to, _url(to, dest), dest if dest != file["key"] else None):
        report.library_files += 1
        report.rekeyed += dest != file["key"]
        report.copied += copied
        report.copied_bytes += size if copied else 0
        report.already_there += not copied
    else:
        report.raced += 1
        if copied:
            target.delete(dest)


# --------------------------------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------------------------------


def _group_id(session: Session, workspace: str | None) -> Any:
    if not workspace:
        return None
    from marvin.db.models.groups import Groups

    gid = session.query(Groups.id).filter(Groups.slug == workspace).scalar()
    if gid is None:
        raise MigrationError(f"no workspace with slug {workspace!r}")
    return gid


def migrate(
    to: str | None,
    *,
    rekey: bool = False,
    session_factory: Callable | None = None,
    workspace: str | None = None,
    batch: int = 100,
    verify: bool = False,
    dry_run: bool = False,
) -> MigrationReport:
    """Move every file not on ``to`` there (one workspace's assets with ``workspace``; library files
    only in a full run). With ``rekey``, also give every file without an opaque key one (``to`` None:
    each on the provider it is on). ``verify`` downloads each copy and hashes it instead of trusting the
    provider's sha256. Raises ``StorageConfigError`` when ``to`` can't take files."""
    if to is None and not rekey:
        raise MigrationError("nothing to do: give a provider to move to, or rekey")
    if session_factory is None:
        from marvin.db.db_setup import session_context as session_factory
    if to is not None:
        provider_factory.provider_for(to)  # fail now if it can't take files
    report = MigrationReport(to=to or "", dry_run=dry_run, rekey=rekey)
    with session_factory() as session:
        group_id = _group_id(session, workspace)
        codes = _codes(session, group_id) if rekey else None
    uploads = provider_factory.upload_target()
    if to is not None and uploads.effective != to:
        log.warning("new uploads go to %r, not %r: switch Admin → Storage first, or files uploaded meanwhile stay behind", uploads.effective, to)

    failed: set[Any] = set()
    while report.passes < MAX_PASSES:
        with session_factory() as session:
            if rekey:  # a workspace created meanwhile
                codes = {**_codes(session, group_id), **(codes or {})}
            rows = [r for r in _pending(session, to, group_id, codes) if r.id not in failed]
            library = [] if group_id is not None else [(p, f) for p, f in _pending_library(session, to, rekey) if (p, f["key"]) not in failed]
        if not rows and not library:
            break
        report.passes += 1
        log.info("pass %d: %d asset rows, %d library files to %s", report.passes, len(rows), len(library), report.summary().split(":", 1)[0])
        if dry_run:
            # Nothing is downloaded: counts and the rows' sizes (library files have none recorded).
            report.copied += len(rows) + len(library)
            report.copied_bytes += sum(r.size or 0 for r in rows)
            report.moved += len(rows)
            report.library_files += len(library)
            if rekey:
                from .keys import LIBRARY_CODE, is_opaque

                report.rekeyed += sum(_row_key(r, codes) != r.key for r in rows) + sum(not is_opaque(f["key"], LIBRARY_CODE) for _, f in library)
            break
        for i, row in enumerate(rows, 1):
            try:
                _migrate_row(session_factory, row, to or row.provider, report, verify, codes)
            except Exception as exc:  # one bad file must not stop the rest
                failed.add(row.id)
                report.failures.append(f"asset {row.id} ({row.key}): {exc}")
                log.error("asset %s (%s): %s", row.id, row.key, exc)
            if i % max(batch, 1) == 0:
                log.info("pass %d: %d/%d asset rows (%s)", report.passes, i, len(rows), report.summary())
        for pack_id, f in library:
            try:
                _migrate_library_file(session_factory, pack_id, f, to, report, verify)
            except Exception as exc:
                failed.add((pack_id, f["key"]))
                report.failures.append(f"library file {f['key']}: {exc}")
                log.error("library file %s: %s", f["key"], exc)
    return report


def prune_local(*, session_factory: Callable | None = None, workspace: str | None = None, dry_run: bool = False) -> MigrationReport:
    """Delete the local copy of every file that lives on another provider, after downloading that copy
    and checking it has the local file's sha256 and size. That includes a local copy left at a key the
    file had before ``--rekey`` (checked against the file's current copy, wherever it is). Rows on
    local, files no row or pack names, and copies that don't match are never touched."""
    if session_factory is None:
        from marvin.db.db_setup import session_context as session_factory
    from marvin.db.models.platform import Assets, StorageKeyAliasModel

    local = provider_factory.provider_for(LOCAL)
    report = MigrationReport(to=PRUNE_LOCAL, dry_run=dry_run)
    with session_factory() as session:
        group_id = _group_id(session, workspace)
        q = session.query(Assets.id, Assets.storage_provider, Assets.storage_key).filter(Assets.storage_provider != LOCAL)
        if group_id is not None:
            q = q.filter(Assets.group_id == group_id)
        # (what, the provider and key of the copy to check against, the local key to delete)
        candidates = [(f"asset {i}", p, k, k) for i, p, k in q]
        if group_id is None:
            from marvin.services.ai.character_library import library_file_provider, list_packs

            candidates += [
                (f"library pack {pack.slug}", library_file_provider(f), f["key"], f["key"])
                for pack in list_packs(session)
                for f in (pack.pack or {}).get("files") or []
                if f.get("key") and library_file_provider(f) != LOCAL
            ]
        aliases = session.query(StorageKeyAliasModel)
        if group_id is not None:
            aliases = aliases.join(Assets, Assets.id == StorageKeyAliasModel.asset_id).filter(Assets.group_id == group_id)
        for alias in aliases:
            current = _current_copy(session, alias)
            if current is not None and current != (LOCAL, alias.storage_key) and not _in_use(session, LOCAL, alias.storage_key):
                candidates.append(
                    (f"old key of {'asset ' + str(alias.asset_id) if alias.asset_id else 'a library file'}", *current, alias.storage_key)
                )
    for what, provider, key, local_key in candidates:
        try:
            if not local.exists(local_key):
                continue
            sha, size = _download_sha256(local, local_key)
            if not copy_matches(provider_factory.provider_for(provider), key, sha, size, strong=True):
                report.failures.append(f"{what} ({local_key}): the copy on {provider} doesn't match the local file; kept")
                continue
            if not dry_run:
                local.delete(local_key)
            report.pruned += 1
            report.pruned_bytes += size
        except Exception as exc:
            report.failures.append(f"{what} ({local_key}): {exc}")
            log.error("%s (%s): %s", what, local_key, exc)
    return report


def _in_use(session: Session, provider: str, key: str) -> bool:
    """Whether an asset row or a library file is stored at (provider, key) now."""
    from marvin.db.models.platform import Assets
    from marvin.services.ai.character_library import library_file_provider, list_packs

    if session.query(Assets.id).filter(Assets.storage_provider == provider, Assets.storage_key == key).first() is not None:
        return True
    return any(
        f.get("key") == key and library_file_provider(f) == provider for pack in list_packs(session) for f in (pack.pack or {}).get("files") or []
    )


def _current_copy(session: Session, alias: Any) -> tuple[str, str] | None:
    """(provider, key) the aliased file lives at now, or None when its asset (or pack file) is gone."""
    from marvin.db.models.platform import Assets
    from marvin.db.models.platform.character_packs import CharacterPackModel
    from marvin.services.ai.character_library import library_file_provider

    if alias.asset_id is not None:
        row = session.get(Assets, alias.asset_id)
        return (row.storage_provider, row.storage_key) if row is not None else None
    pack = session.get(CharacterPackModel, alias.pack_id) if alias.pack_id is not None else None
    for f in ((pack.pack if pack else None) or {}).get("files") or []:
        if f.get("key") == alias.current_key:
            return library_file_provider(f), f["key"]
    return None


def prune_old(*, session_factory: Callable | None = None, workspace: str | None = None, dry_run: bool = False) -> MigrationReport:
    """Delete the copies ``--rekey`` left at old keys. Each is deleted only when nothing is stored at that
    (provider, key) any more and the file's current copy matches it (both downloaded and hashed); one
    whose asset or pack file is gone is deleted too (nobody owns it). The alias stays, marked pruned, so
    the old ``/assets/`` URL keeps redirecting. Rebuild sites that link old remote URLs first: those
    reach the bucket directly, with no redirect."""
    if session_factory is None:
        from marvin.db.db_setup import session_context as session_factory
    from marvin.db.models.platform import Assets, StorageKeyAliasModel

    report = MigrationReport(to=PRUNE_OLD, dry_run=dry_run)
    with session_factory() as session:
        group_id = _group_id(session, workspace)
        q = session.query(StorageKeyAliasModel.id).filter(StorageKeyAliasModel.pruned_at.is_(None))
        if group_id is not None:
            q = q.join(Assets, Assets.id == StorageKeyAliasModel.asset_id).filter(Assets.group_id == group_id)
        alias_ids = [a for (a,) in q.order_by(StorageKeyAliasModel.created_at)]
    for alias_id in alias_ids:
        with session_factory() as session:
            alias = session.get(StorageKeyAliasModel, alias_id)
            what = f"{alias.provider}:{alias.storage_key}"
            try:
                if _in_use(session, alias.provider, alias.storage_key):
                    report.failures.append(f"{what}: a file is stored there now; kept")
                    continue
                old = provider_factory.provider_for(alias.provider)
                if old.exists(alias.storage_key):
                    sha, size = _download_sha256(old, alias.storage_key)
                    current = _current_copy(session, alias)
                    if current is not None and not copy_matches(provider_factory.provider_for(current[0]), current[1], sha, size, strong=True):
                        report.failures.append(f"{what}: the current copy ({current[0]}:{current[1]}) doesn't match it; kept")
                        continue
                    if not dry_run:
                        old.delete(alias.storage_key)
                    report.pruned += 1
                    report.pruned_bytes += size
                if not dry_run:
                    alias.pruned_at = datetime.now(UTC).replace(tzinfo=None)
                    session.commit()
            except Exception as exc:
                session.rollback()
                report.failures.append(f"{what}: {exc}")
                log.error("%s: %s", what, exc)
    return report


__all__ = ["MigrationError", "MigrationReport", "copy_file", "copy_matches", "migrate", "prune_local", "prune_old"]
