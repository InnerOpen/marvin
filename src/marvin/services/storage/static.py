"""The local provider's files, served at ``STORAGE_LOCAL_PUBLIC_URL`` (``/assets``), whatever provider
new uploads go to: rows on local disk stay there until they are moved.

A file that isn't on disk but whose row (or character-library file) now lives on another provider
redirects there, so ``/assets/…`` URLs stored before a move (entry bodies, settings, sites built
earlier) keep working after ``storage_migrate --prune-local`` has removed the local copy. The same goes
for a key ``storage_migrate --rekey`` moved away from (``storage_key_aliases``): once ``--prune-old``
has deleted the old copy, its URL redirects to the file's new one. The redirect is temporary (302):
moving files back (``--to local``) must win over any cache.

Files under opaque keys (services/storage/keys.py) carry no name, so they are served with
``Content-Disposition: inline; filename="<the name it was uploaded with>"``.
"""

from __future__ import annotations

import logging
import uuid
from functools import lru_cache

from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException  # what StaticFiles raises (fastapi's is a subclass)

logger = logging.getLogger(__name__)


def _library_file(session, key: str) -> tuple[object, dict] | None:
    """(pack, file entry) of the character-library file stored under ``key``."""
    from marvin.db.models.platform.character_packs import CharacterPackModel
    from marvin.services.ai.character_library import LIBRARY_STORAGE_PREFIX, list_packs

    if key.startswith(f"{LIBRARY_STORAGE_PREFIX}/"):
        try:
            pack = session.get(CharacterPackModel, uuid.UUID(key[len(LIBRARY_STORAGE_PREFIX) + 1 :].split("/", 1)[0]))
        except ValueError:
            return None
        packs = [pack] if pack else []
    else:
        packs = list_packs(session)
    for pack in packs:
        for f in (pack.pack or {}).get("files") or []:
            if f.get("key") == key:
                return pack, f
    return None


def _current_url(session, key: str, *, moved_only: bool) -> str | None:
    """The URL the file stored under ``key`` is served at now. With ``moved_only``, None when that is
    still the local copy at ``key`` itself."""
    from marvin.db.models.platform import Assets
    from marvin.services.ai.character_library import library_file_provider

    from .keys import LIBRARY_CODE
    from .provider_factory import asset_public_url, provider_for
    from .registry import LOCAL

    row = session.query(Assets).filter(Assets.storage_key == key).first()
    if row is not None:
        return asset_public_url(row) if not (moved_only and row.storage_provider == LOCAL) else None
    if key.startswith(f"{LIBRARY_CODE}/"):
        found = _library_file(session, key)
        if found is not None:
            slug = library_file_provider(found[1])
            return provider_for(slug).get_public_url(key) if not (moved_only and slug == LOCAL) else None
    return None


def moved_url(key: str) -> str | None:
    """The URL of ``key`` when its file now lives elsewhere: its row (or library file) is on a provider
    other than local, or it was rekeyed (any provider). Else None."""
    from marvin.db.db_setup import session_context
    from marvin.db.models.platform import StorageKeyAliasModel

    key = key.replace("\\", "/").lstrip("/")
    try:
        with session_context() as session:
            url = _current_url(session, key, moved_only=True)
            if url is not None:
                return url
            # Any provider's: a /assets/ URL stored before a move to s3 names the key the row had then.
            alias = session.query(StorageKeyAliasModel).filter(StorageKeyAliasModel.storage_key == key).first()
            if alias is not None:
                return _current_url(session, alias.current_key, moved_only=False)
    except Exception as e:  # unreadable database or provider: a plain 404, as before
        logger.warning(f"storage: couldn't look up where {key!r} moved: {e}")
    return None


@lru_cache(maxsize=4096)
def _download_name(key: str) -> str | None:
    """The name the file under an opaque ``key`` was uploaded with (cached: a key never changes owner)."""
    from marvin.db.db_setup import session_context
    from marvin.db.models.platform import Assets

    with session_context() as session:
        name = session.query(Assets.original_filename).filter(Assets.storage_key == key).scalar()
        if name is None:
            from marvin.services.ai.character_library import library_download_name

            found = _library_file(session, key)
            name = library_download_name(found[1]) if found else None
    if name is None:
        raise LookupError(key)  # not cached: a row may appear for it later
    return name


def download_name(key: str) -> str | None:
    try:
        return _download_name(key)
    except LookupError:
        return None
    except Exception as e:
        logger.debug(f"storage: no download name for {key!r}: {e}")
        return None


class LocalAssetFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        from .keys import content_disposition, is_opaque

        try:
            response = await super().get_response(path, scope)
        except HTTPException as e:
            if e.status_code != 404:
                raise
            url = await run_in_threadpool(moved_url, path)
            if url is None:
                raise
            return RedirectResponse(url, status_code=302)
        key = path.replace("\\", "/").lstrip("/")
        if response.status_code in (200, 206) and is_opaque(key):
            disposition = content_disposition(await run_in_threadpool(download_name, key))
            if disposition:
                response.headers["content-disposition"] = disposition
        return response
