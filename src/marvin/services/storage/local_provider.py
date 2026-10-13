"""Local filesystem storage provider."""

import hashlib
import os
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from .base_provider import BaseStorageProvider, StorageMetadata


class LocalStorageProvider(BaseStorageProvider):
    """
    Storage provider that stores files on local filesystem.

    Files are stored under a root directory with the storage_key as the relative path.
    """

    slug = "local"

    def __init__(self, root: Path, public_base_url: str = "/uploads"):
        """
        Initialize local storage provider.

        Args:
            root: Root directory for file storage
            public_base_url: Base URL for public access (e.g. /uploads)
        """
        self.root = Path(root)
        self.public_base_url = public_base_url.rstrip("/")

        # Ensure root directory exists
        self.root.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, storage_key: str) -> Path:
        """Get absolute filesystem path from storage key."""
        return self.root / storage_key

    def put(
        self,
        storage_key: str,
        file_data: BinaryIO,
        content_type: str,
        metadata: dict | None = None,
    ) -> StorageMetadata:
        """Store a file on local filesystem."""
        file_path = self._get_file_path(storage_key)

        # Create parent directories
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Calculate checksum while writing
        hasher = hashlib.sha256()
        size = 0

        # Write file and calculate checksum
        with open(file_path, "wb") as f:
            while chunk := file_data.read(8192):
                hasher.update(chunk)
                f.write(chunk)
                size += len(chunk)

        checksum = hasher.hexdigest()

        return StorageMetadata(
            storage_key=storage_key,
            size=size,
            content_type=content_type,
            checksum=checksum,
            metadata=metadata,
            checksum_algorithm="sha256",
        )

    def get(self, storage_key: str) -> BinaryIO:
        """Retrieve a file from local filesystem."""
        file_path = self._get_file_path(storage_key)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {storage_key}")

        return open(file_path, "rb")

    def delete(self, storage_key: str) -> bool:
        """Delete a file from local filesystem."""
        file_path = self._get_file_path(storage_key)

        if not file_path.exists():
            return False

        file_path.unlink()
        return True

    def exists(self, storage_key: str) -> bool:
        """Check if a file exists on local filesystem."""
        return self._get_file_path(storage_key).exists()

    def get_public_url(self, storage_key: str) -> str:
        """Get public URL for accessing a file."""
        return f"{self.public_base_url}/{storage_key}"

    def get_metadata(self, storage_key: str) -> StorageMetadata:
        """Get metadata about a stored file."""
        file_path = self._get_file_path(storage_key)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {storage_key}")

        stat = file_path.stat()

        # Calculate checksum
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)

        return StorageMetadata(
            storage_key=storage_key,
            size=stat.st_size,
            content_type="application/octet-stream",  # We don't store content type in local files
            checksum=hasher.hexdigest(),
            checksum_algorithm="sha256",
        )

    def checksum(self, storage_key: str, algorithm: str = "sha256") -> str | None:
        """The file's digest in ``algorithm`` (read from disk)."""
        file_path = self._get_file_path(storage_key)
        if not file_path.is_file():
            raise FileNotFoundError(f"File not found: {storage_key}")
        hasher = hashlib.new(algorithm)
        with open(file_path, "rb") as f:
            while chunk := f.read(1024 * 1024):
                hasher.update(chunk)
        return hasher.hexdigest()

    def iter_keys(self, prefix: str = "") -> Iterator[str]:
        """Every regular file under the root whose key starts with ``prefix``, sorted; symlinks are skipped."""
        # Walk only the deepest directory the prefix names fully (``ws/assets/20`` → ``ws/assets``).
        start = self.root / prefix.rpartition("/")[0] if "/" in prefix else self.root
        if not start.is_dir():
            return
        keys = []
        for root, dirs, files in os.walk(start):
            dirs[:] = [d for d in dirs if not Path(root, d).is_symlink()]
            for name in files:
                path = Path(root, name)
                if path.is_file() and not path.is_symlink():
                    key = path.relative_to(self.root).as_posix()
                    if key.startswith(prefix):
                        keys.append(key)
        yield from sorted(keys)
