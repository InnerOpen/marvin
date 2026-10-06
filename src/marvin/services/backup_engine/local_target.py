"""The built-in ``local`` backup target: a directory on a mounted volume (a NAS export, a second disk).

Each object is a file at ``<root>/<key>``; its size, sha256 and metadata sit beside it in
``<key>.meta.json``. A ``.meta.json`` file counts as a sidecar only while its data file exists, so an
uploaded asset that happens to end in ``.meta.json`` is still an object. Writes go to a temp file in
the destination directory and are renamed into place (atomic within a directory, on NFS too), the data
file before its sidecar; a reader never sees a partial object.

Guardrail: the root must already exist (a missing mount must not quietly fill the container's own
disk), and it may not be inside DATA_DIR or on the same filesystem as it: a copy on the live volume
doesn't survive losing that volume.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from marvin_integration_sdk.storage import BackupTarget, Setting, StorageConfigError, TargetObject

SIDECAR = ".meta.json"
TMP_PREFIX = ".marvin-tmp-"
CHUNK = 1024 * 1024


def _device(path: Path) -> int:
    return path.stat().st_dev


class LocalBackupTarget(BackupTarget):
    slug = "local"
    settings = (
        Setting("BACKUP_LOCAL_ROOT", "Backup directory", required=True, help="A mounted volume other than the data volume."),
        Setting("BACKUP_DATA_DIR", "Data directory (refused as a target)", default="/app/data"),
    )

    def __init__(self, root: Path, data_dir: Path | None = None) -> None:
        root = Path(root)
        if not root.is_dir():
            raise StorageConfigError(f"backup directory {root} does not exist (is the volume mounted?)")
        self.root = root.resolve()
        if data_dir is not None:
            data = Path(data_dir).resolve()
            if self.root == data or self.root.is_relative_to(data):
                raise StorageConfigError(f"backup directory {self.root} is inside the data directory {data}; use a different volume")
            if data.exists() and _device(self.root) == _device(data):
                raise StorageConfigError(
                    f"backup directory {self.root} is on the same filesystem as the data directory {data}; use a different volume"
                )

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> LocalBackupTarget:
        data_dir = config.get("BACKUP_DATA_DIR")
        return cls(Path(config["BACKUP_LOCAL_ROOT"]), data_dir=Path(data_dir) if data_dir else None)

    def describe(self) -> str:
        return f"local:{self.root}"

    # --- paths ------------------------------------------------------------------------------------

    def _path(self, key: str) -> Path:
        parts = key.split("/")
        if not key or "\\" in key or any(p in ("", ".", "..") for p in parts):  # also catches a leading or trailing "/"
            raise ValueError(f"invalid backup key: {key!r}")
        if parts[-1].startswith(TMP_PREFIX):
            raise ValueError(f"invalid backup key: {key!r}")
        path = self.root.joinpath(*parts)
        if not path.resolve().is_relative_to(self.root):
            raise ValueError(f"backup key leaves the target: {key!r}")
        return path

    @staticmethod
    def _sidecar(path: Path) -> Path:
        return path.with_name(path.name + SIDECAR)

    @staticmethod
    def _atomic_write(dest: Path, write) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f"{TMP_PREFIX}{secrets.token_hex(6)}-{dest.name}")
        try:
            with tmp.open("wb") as fh:
                write(fh)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, dest)
        finally:
            tmp.unlink(missing_ok=True)

    def _read_sidecar(self, path: Path) -> dict[str, Any]:
        try:
            return json.loads(self._sidecar(path).read_text())
        except (OSError, ValueError):
            return {}

    def _object(self, key: str, path: Path) -> TargetObject:
        size = path.stat().st_size
        side = self._read_sidecar(path)
        # A digest recorded for a different size (the file changed under it) vouches for nothing; the
        # metadata stays, so a restore still checks the file against the sha256 it was written with.
        trusted = side.get("size") == size and side.get("algorithm") and side.get("digest")
        return TargetObject(
            key=key,
            size=size,
            digest=side["digest"] if trusted else "",
            algorithm=side["algorithm"] if trusted else "",
            metadata=dict(side.get("metadata") or {}),
        )

    # --- the contract -----------------------------------------------------------------------------

    def put_file(self, key: str, path: Path, metadata: Mapping[str, str] | None = None, content_type: str | None = None) -> None:
        dest = self._path(key)
        hasher, size = hashlib.sha256(), 0

        def copy(out) -> None:
            nonlocal size
            with Path(path).open("rb") as src:
                while chunk := src.read(CHUNK):
                    hasher.update(chunk)
                    out.write(chunk)
                    size += len(chunk)

        self._sidecar(dest).unlink(missing_ok=True)  # never leave the old sidecar vouching for new bytes
        self._atomic_write(dest, copy)
        side = {
            "size": size,
            "algorithm": "sha256",
            "digest": hasher.hexdigest(),
            "content_type": content_type,
            "metadata": {str(k).lower(): str(v) for k, v in (metadata or {}).items()},
        }
        self._atomic_write(self._sidecar(dest), lambda out: out.write(json.dumps(side, sort_keys=True).encode()))

    def get(self, key: str, dest: Path) -> dict[str, str]:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError(f"no such backup object: {key}")
        with path.open("rb") as src, Path(dest).open("wb") as out:
            shutil.copyfileobj(src, out, CHUNK)
        return dict(self._object(key, path).metadata)

    def head(self, key: str) -> TargetObject | None:
        path = self._path(key)
        return self._object(key, path) if path.is_file() else None

    def list(self, prefix: str) -> dict[str, TargetObject]:
        # Walk only the deepest directory the prefix names fully (``assets/ws/20`` → ``assets/ws``).
        start = self.root.joinpath(*PurePosixPath(prefix.rpartition("/")[0]).parts) if "/" in prefix else self.root
        found: dict[str, TargetObject] = {}
        if not start.is_dir() or not start.resolve().is_relative_to(self.root):
            return found
        for dirpath, dirs, files in os.walk(start):
            dirs[:] = sorted(d for d in dirs if not Path(dirpath, d).is_symlink())
            names = set(files)
            for name in sorted(files):
                path = Path(dirpath, name)
                if name.startswith(TMP_PREFIX) or path.is_symlink() or not path.is_file():
                    continue
                if name.endswith(SIDECAR) and name[: -len(SIDECAR)] in names:
                    continue  # the sidecar of a data file beside it
                key = path.relative_to(self.root).as_posix()
                if key.startswith(prefix):
                    found[key] = self._object(key, path)
        return found

    def delete(self, keys: Iterable[str]) -> None:
        for key in keys:
            path = self._path(key)
            # Sidecar first: an interrupted delete leaves a file without a digest, never a stray sidecar.
            self._sidecar(path).unlink(missing_ok=True)
            path.unlink(missing_ok=True)
