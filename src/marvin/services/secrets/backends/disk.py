"""
Disk secret backend.

Stores per-workspace Fernet-encrypted JSON files in {SECRETS_DIR}/{group_id}.json.
Falls back to {DATA_DIR}/secrets/ if SECRETS_DIR is not set.
"""

import json
from pathlib import Path

from pydantic import UUID4
from sqlalchemy.orm import Session

from marvin.core.config import get_app_dirs, get_app_settings
from marvin.core.root_logger import get_logger

from ..base import SecretBackend
from .database import _get_fernet

logger = get_logger(__name__)


def _secrets_dir() -> Path:
    settings = get_app_settings()
    if settings.SECRETS_DIR:
        d = Path(settings.SECRETS_DIR)
    else:
        d = get_app_dirs().DATA_DIR / "secrets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _file(group_id: UUID4 | None) -> Path:
    name = str(group_id) if group_id else "_system"
    return _secrets_dir() / f"{name}.enc"


def _read(group_id: UUID4 | None) -> dict:
    f = _file(group_id)
    if not f.exists():
        return {}
    try:
        return json.loads(_get_fernet().decrypt(f.read_bytes()).decode())
    except Exception:
        logger.error(f"Failed to decrypt secrets file {f}")
        return {}


def _write(data: dict, group_id: UUID4 | None) -> None:
    f = _file(group_id)
    f.write_bytes(_get_fernet().encrypt(json.dumps(data).encode()))


class DiskSecretBackend(SecretBackend):
    """Per-workspace Fernet-encrypted JSON file on disk."""

    def get(self, slug: str, group_id: UUID4 | None = None) -> str | None:
        return _read(group_id).get(slug)

    def set(self, slug: str, value: str, group_id: UUID4 | None = None, session: Session | None = None) -> None:
        data = _read(group_id)
        data[slug] = value
        _write(data, group_id)

    def delete(self, slug: str, group_id: UUID4 | None = None, session: Session | None = None) -> None:
        data = _read(group_id)
        data.pop(slug, None)
        _write(data, group_id)

    def list_slugs(self, group_id: UUID4 | None = None) -> list[str]:
        return list(_read(group_id).keys())
