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
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
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
        if self.to == PRUNE_LOCAL:
            verb = "would delete" if self.dry_run else "deleted"
            return f"prune-local: {verb} {self.pruned} local copies ({_mb(self.pruned_bytes)}), {len(self.failures)} failed"
        verb = "would copy" if self.dry_run else "copied"
        parts = [
            f"to {self.to}: {verb} {self.copied} ({_mb(self.copied_bytes)})",
            f"{self.already_there} already there",
            f"{self.moved} asset rows moved",
            f"{self.library_files} library files moved",
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


def copy_file(source: BaseStorageProvider, target: BaseStorageProvider, key: str, content_type: str | None, verify: bool) -> tuple[str, int, bool]:
    """Copy ``key`` unless the target already has the same bytes. Returns (sha256, size, copied).
    Raises ``MigrationError`` when the copy doesn't match the source after upload."""
    with _staged(source, key) as (path, sha, size):
        if target.exists(key) and copy_matches(target, key, sha, size, strong=verify):
            return sha, size, False
        with path.open("rb") as fh:
            target.put(storage_key=key, file_data=fh, content_type=content_type or "application/octet-stream")
        if not copy_matches(target, key, sha, size, strong=verify):
            raise MigrationError(f"{key}: the copy on the target doesn't match the source (sha256/size)")
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


def _pending(session: Session, to: str, group_id: Any = None) -> list[_Row]:
    from marvin.db.models.platform import Assets

    q = session.query(Assets.id, Assets.storage_provider, Assets.storage_key, Assets.checksum, Assets.file_size, Assets.mime_type).filter(
        Assets.storage_provider != to
    )
    if group_id is not None:
        q = q.filter(Assets.group_id == group_id)
    return [_Row(*r) for r in q.order_by(Assets.created_at, Assets.id)]


def _flip(session_factory: Callable, row: _Row, to: str, url: str | None) -> str:
    """Point the row at ``to`` if it still lives where it did: "moved", "changed" (another provider
    now) or "gone" (deleted meanwhile)."""
    from marvin.db.models.platform import Assets

    with session_factory() as session:
        result = session.execute(
            sa.update(Assets)
            .where(Assets.id == row.id, Assets.storage_provider == row.provider, Assets.storage_key == row.key)
            .values(storage_provider=to, public_url=url)
        )
        if result.rowcount == 1:
            session.commit()
            return "moved"
        session.rollback()
        exists = session.query(Assets.id).filter(Assets.id == row.id).first() is not None
        return "changed" if exists else "gone"


def _migrate_row(session_factory: Callable, row: _Row, target: BaseStorageProvider, report: MigrationReport, verify: bool) -> None:
    source = provider_factory.provider_for(row.provider)
    sha, size, copied = copy_file(source, target, row.key, row.mime_type, verify)
    if row.checksum and row.checksum != sha:
        report.checksum_mismatches += 1
        log.warning(
            "asset %s (%s): stored checksum %s… differs from the file's %s… (the copy matches the file)", row.id, row.key, row.checksum[:12], sha[:12]
        )
    outcome = _flip(session_factory, row, report.to, _url(target, row.key))
    if outcome == "moved":
        report.moved += 1
        report.copied += copied
        report.copied_bytes += size if copied else 0
        report.already_there += not copied
    else:
        report.raced += 1
        log.info("asset %s (%s): %s while copying; left as it is", row.id, row.key, "deleted" if outcome == "gone" else "changed")
        if outcome == "gone" and copied:
            target.delete(row.key)  # the row went with its source file; don't leave a copy nobody owns


def _url(provider: BaseStorageProvider, key: str) -> str | None:
    try:
        return provider.get_public_url(key)
    except Exception:
        return None


# --------------------------------------------------------------------------------------------------
# Character-library files
# --------------------------------------------------------------------------------------------------


def _pending_library(session: Session, to: str) -> list[tuple[Any, dict]]:
    from marvin.services.ai.character_library import library_file_provider, list_packs

    return [
        (pack.id, dict(f))
        for pack in list_packs(session)
        for f in (pack.pack or {}).get("files") or []
        if f.get("key") and library_file_provider(f) != to
    ]


def _flip_library(session_factory: Callable, pack_id: Any, file: dict, to: str, url: str | None) -> bool:
    """Record the file's new provider (and URL, and every state playing it) in the pack's JSON, if the
    pack still has that file where it was."""
    from marvin.db.models.platform.character_packs import CharacterPackModel
    from marvin.services.ai.character_library import library_file_provider

    with session_factory() as session:
        pack = session.get(CharacterPackModel, pack_id)
        files = list((pack.pack or {}).get("files") or []) if pack else []
        for i, f in enumerate(files):
            if f.get("key") == file["key"] and library_file_provider(f) == library_file_provider(file):
                old_url = f.get("url")
                files[i] = {**f, "provider": to, **({"url": url} if url else {})}
                states = {s: (url if url and u == old_url else u) for s, u in ((pack.pack or {}).get("states") or {}).items()}
                pack.pack = {**pack.pack, "files": files, "states": states}  # a new dict: JSON columns track assignment
                session.commit()
                return True
        return False


def _migrate_library_file(
    session_factory: Callable, pack_id: Any, file: dict, target: BaseStorageProvider, report: MigrationReport, verify: bool
) -> None:
    from marvin.services.ai.character_library import library_file_provider

    source = provider_factory.provider_for(library_file_provider(file))
    # No row records its type, and local disk keeps none: the name says it (GIF/WebP/PNG).
    content_type = mimetypes.guess_type(file["key"])[0]
    _, size, copied = copy_file(source, target, file["key"], content_type, verify)
    if _flip_library(session_factory, pack_id, file, report.to, _url(target, file["key"])):
        report.library_files += 1
        report.copied += copied
        report.copied_bytes += size if copied else 0
        report.already_there += not copied
    else:
        report.raced += 1
        if copied:
            target.delete(file["key"])


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
    to: str,
    *,
    session_factory: Callable | None = None,
    workspace: str | None = None,
    batch: int = 100,
    verify: bool = False,
    dry_run: bool = False,
) -> MigrationReport:
    """Move every file not on ``to`` there (one workspace's assets with ``workspace``; library files
    only in a full run). ``verify`` downloads each copy and hashes it instead of trusting the
    provider's sha256. Raises ``StorageConfigError`` when ``to`` can't take files."""
    if session_factory is None:
        from marvin.db.db_setup import session_context as session_factory
    target = provider_factory.provider_for(to)
    report = MigrationReport(to=to, dry_run=dry_run)
    with session_factory() as session:
        group_id = _group_id(session, workspace)
    uploads = provider_factory.upload_target()
    if uploads.effective != to:
        log.warning("new uploads go to %r, not %r: switch Admin → Storage first, or files uploaded meanwhile stay behind", uploads.effective, to)

    failed: set[Any] = set()
    while report.passes < MAX_PASSES:
        with session_factory() as session:
            rows = [r for r in _pending(session, to, group_id) if r.id not in failed]
            library = [] if group_id is not None else [(p, f) for p, f in _pending_library(session, to) if (p, f["key"]) not in failed]
        if not rows and not library:
            break
        report.passes += 1
        log.info("pass %d: %d asset rows, %d library files to move to %s", report.passes, len(rows), len(library), to)
        if dry_run:
            # Nothing is downloaded: counts and the rows' sizes (library files have none recorded).
            report.copied += len(rows) + len(library)
            report.copied_bytes += sum(r.size or 0 for r in rows)
            report.moved += len(rows)
            report.library_files += len(library)
            break
        for i, row in enumerate(rows, 1):
            try:
                _migrate_row(session_factory, row, target, report, verify)
            except Exception as exc:  # one bad file must not stop the rest
                failed.add(row.id)
                report.failures.append(f"asset {row.id} ({row.key}): {exc}")
                log.error("asset %s (%s): %s", row.id, row.key, exc)
            if i % max(batch, 1) == 0:
                log.info("pass %d: %d/%d asset rows (%s)", report.passes, i, len(rows), report.summary())
        for pack_id, f in library:
            try:
                _migrate_library_file(session_factory, pack_id, f, target, report, verify)
            except Exception as exc:
                failed.add((pack_id, f["key"]))
                report.failures.append(f"library file {f['key']}: {exc}")
                log.error("library file %s: %s", f["key"], exc)
    return report


def prune_local(*, session_factory: Callable | None = None, workspace: str | None = None, dry_run: bool = False) -> MigrationReport:
    """Delete the local copy of every file that lives on another provider, after downloading that copy
    and checking it has the local file's sha256 and size. Rows on local, files no row or pack names,
    and copies that don't match are never touched."""
    if session_factory is None:
        from marvin.db.db_setup import session_context as session_factory
    from marvin.db.models.platform import Assets

    local = provider_factory.provider_for(LOCAL)
    report = MigrationReport(to=PRUNE_LOCAL, dry_run=dry_run)
    with session_factory() as session:
        group_id = _group_id(session, workspace)
        q = session.query(Assets.id, Assets.storage_provider, Assets.storage_key).filter(Assets.storage_provider != LOCAL)
        if group_id is not None:
            q = q.filter(Assets.group_id == group_id)
        candidates = [(f"asset {i}", p, k) for i, p, k in q]
        if group_id is None:
            from marvin.services.ai.character_library import library_file_provider, list_packs

            candidates += [
                (f"library pack {pack.slug}", library_file_provider(f), f["key"])
                for pack in list_packs(session)
                for f in (pack.pack or {}).get("files") or []
                if f.get("key") and library_file_provider(f) != LOCAL
            ]
    for what, provider, key in candidates:
        try:
            if not local.exists(key):
                continue
            sha, size = _download_sha256(local, key)
            if not copy_matches(provider_factory.provider_for(provider), key, sha, size, strong=True):
                report.failures.append(f"{what} ({key}): the copy on {provider} doesn't match the local file; kept")
                continue
            if not dry_run:
                local.delete(key)
            report.pruned += 1
            report.pruned_bytes += size
        except Exception as exc:
            report.failures.append(f"{what} ({key}): {exc}")
            log.error("%s (%s): %s", what, key, exc)
    return report


__all__ = ["MigrationError", "MigrationReport", "copy_file", "copy_matches", "migrate", "prune_local"]
