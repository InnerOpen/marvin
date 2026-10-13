"""Storage keys: opaque names for stored files, and the download name that travels with each one.

A new file is stored as ``<code>/<yyyy>/<mm>/<uuid>.<ext>``:

- ``<code>`` is the workspace's storage code (``groups.storage_code``): 12 random base32 characters made
  once per workspace (the migration that added it, or the workspace's creation) and never changed. It
  is random rather than derived from the instance secret, so it stays the same if ``.secret`` is
  rotated or lost, says nothing about the workspace (no slug, no id to brute-force), and needs no
  secret to work out. Character-library files belong to no workspace and use ``_platform`` (never a
  code: codes have no ``_``).
- ``<yyyy>/<mm>`` is the upload month, ``<uuid>`` a random UUID, ``<ext>`` the original extension,
  lower-cased and reduced to ``[a-z0-9]`` (or one guessed from the content type).

No workspace slug and no original filename appear in a key, so neither shows in a public URL. The
original filename stays on the asset row and is served as ``Content-Disposition`` (``content_disposition``):
by Marvin where it serves the file, and stored on the object at upload where a provider supports it
(the ``content_disposition`` entry of ``put``'s metadata).

Keys are stored on rows, never recomputed: older keys (``<slug>/assets/<yyyy>/<mm>/<uuid>-<name>``,
``_platform/character-packs/<pack>/<name>``) keep working until ``storage_migrate --rekey`` moves them.
"""

from __future__ import annotations

import mimetypes
import re
import secrets
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

CODE_LENGTH = 12
CODE_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"  # RFC 4648 base32, lower-case
LIBRARY_CODE = "_platform"
"""The ``<code>`` of character-library files (platform-wide, no workspace)."""
CONTENT_DISPOSITION_META = "content_disposition"
"""The ``put`` metadata entry a provider may store as the object's ``Content-Disposition``."""
REKEY_NAMESPACE = uuid.UUID("6f7e0c1a-4b0e-4d4e-9a52-2c1d1f3b8e10")
"""Namespace of the UUIDs ``storage_migrate --rekey`` derives, so an interrupted run picks the same key again."""

_MAX_EXT = 10
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_KEY = re.compile(
    rf"^(?P<code>[a-z2-7]{{{CODE_LENGTH}}}|{LIBRARY_CODE})/(?P<y>\d{{4}})/(?P<m>\d{{2}})/(?P<id>{_UUID})(?:\.[a-z0-9]{{1,{_MAX_EXT}}})?$"
)
# MIME types whose guessed extension is odd or missing (mimetypes varies by platform).
_EXT_FOR_TYPE = {"image/jpeg": "jpg", "image/svg+xml": "svg", "text/plain": "txt", "image/webp": "webp", "image/avif": "avif"}


def new_code() -> str:
    """A new workspace storage code: 12 random base32 characters (60 bits)."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def key_extension(filename: str | None, content_type: str | None = None) -> str:
    """The extension a key carries: the filename's, lower-cased and reduced to ``[a-z0-9]`` (at most 10),
    else one for ``content_type``, else none."""
    name = (filename or "").rsplit("/", 1)[-1]
    ext = re.sub(r"[^a-z0-9]", "", name.rsplit(".", 1)[1].lower()) if "." in name.strip(".") else ""
    if not ext and content_type:
        mime = content_type.split(";", 1)[0].strip().lower()
        ext = _EXT_FOR_TYPE.get(mime) or (mimetypes.guess_extension(mime) or "").lstrip(".")
    return ext[:_MAX_EXT]


def new_key(
    code: str, filename: str | None = None, content_type: str | None = None, when: datetime | None = None, key_id: uuid.UUID | None = None
) -> str:
    """``<code>/<yyyy>/<mm>/<uuid>.<ext>``. ``when`` (default now, UTC) gives the month; ``key_id`` (default
    random) the UUID."""
    when = when or datetime.now(UTC)
    ext = key_extension(filename, content_type)
    return f"{code}/{when:%Y}/{when:%m}/{key_id or uuid.uuid4()}" + (f".{ext}" if ext else "")


def is_opaque(key: str | None, code: str | None = None) -> bool:
    """Whether ``key`` has the opaque form (under ``code``, when given)."""
    m = _KEY.match(key or "")
    return bool(m) and (code is None or m["code"] == code)


def rekeyed(code: str, old_key: str, seed: str, filename: str | None = None, content_type: str | None = None, when: datetime | None = None) -> str:
    """The opaque key ``storage_migrate --rekey`` moves ``old_key`` to: the same for the same ``seed`` (a
    row id, or a pack file), so a rerun after an interruption reuses the copy it already made. The month
    is the old key's (``…/<yyyy>/<mm>/…``) when it has one, else ``when``'s."""
    m = re.search(r"(?:^|/)(\d{4})/(\d{2})/", old_key)
    if m and 1 <= int(m[2]) <= 12:
        when = datetime(int(m[1]), int(m[2]), 1, tzinfo=UTC)
    return new_key(code, filename or old_key, content_type, when, uuid.uuid5(REKEY_NAMESPACE, seed))


# --------------------------------------------------------------------------------------------------
# Workspace codes
# --------------------------------------------------------------------------------------------------


def workspace_code(session: Session, group_id: Any) -> str:
    """The workspace's storage code, made (and flushed) the first time a workspace without one needs it.
    Workspaces get one on creation and the migration gave every existing workspace one, so this is a
    safety net, not the usual path."""
    from marvin.db.models.groups import Groups

    group = session.get(Groups, group_id)
    if group is None:
        raise ValueError(f"Workspace not found: {group_id}")
    if not group.storage_code:
        group.storage_code = new_code()
        session.flush()
    return group.storage_code


# --------------------------------------------------------------------------------------------------
# Download names
# --------------------------------------------------------------------------------------------------


def _ascii_fallback(name: str) -> str:
    import unicodedata

    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    plain = re.sub(r'[^\x20-\x7e]|["\\]', "_", plain).strip() or "download"
    return plain


def content_disposition(filename: str | None, disposition: str = "inline") -> str | None:
    """``inline; filename="…"`` for ``filename``, plus ``filename*=UTF-8''…`` (RFC 5987/6266) when it isn't
    plain ASCII. Control characters, quotes and path separators never reach the header. None without
    a usable name."""
    name = re.sub(r"[\x00-\x1f\x7f]", "", (filename or "").replace("\\", "/").rsplit("/", 1)[-1]).strip()
    if not name:
        return None
    fallback = _ascii_fallback(name)
    header = f'{disposition}; filename="{fallback}"'
    if fallback != name:
        header += f"; filename*=UTF-8''{quote(name, safe='')}"
    return header


def object_metadata(filename: str | None, metadata: dict | None = None) -> dict | None:
    """``metadata`` plus the ``content_disposition`` entry a provider stores on the object."""
    cd = content_disposition(filename)
    if cd is None:
        return metadata
    return {**(metadata or {}), CONTENT_DISPOSITION_META: cd}


__all__ = [
    "CODE_LENGTH",
    "CONTENT_DISPOSITION_META",
    "LIBRARY_CODE",
    "content_disposition",
    "is_opaque",
    "key_extension",
    "new_code",
    "new_key",
    "object_metadata",
    "rekeyed",
    "workspace_code",
]
