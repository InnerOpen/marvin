"""The local provider's files, served at ``STORAGE_LOCAL_PUBLIC_URL`` (``/assets``), whatever provider
new uploads go to: rows on local disk stay there until they are moved.

A file that isn't on disk but whose row (or character-library file) now lives on another provider
redirects there, so ``/assets/…`` URLs stored before a move (entry bodies, settings, sites built
earlier) keep working after ``storage_migrate --prune-local`` has removed the local copy. The redirect
is temporary (302): moving files back (``--to local``) must win over any cache.
"""

from __future__ import annotations

import logging
import uuid

from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException  # what StaticFiles raises (fastapi's is a subclass)

logger = logging.getLogger(__name__)


def moved_url(key: str) -> str | None:
    """The URL of ``key`` when its row (or library file) lives on a provider other than local, else None."""
    from marvin.db.db_setup import session_context
    from marvin.db.models.platform import Assets
    from marvin.db.models.platform.character_packs import CharacterPackModel
    from marvin.services.ai.character_library import LIBRARY_STORAGE_PREFIX, library_file_provider

    from .provider_factory import provider_for
    from .registry import LOCAL

    key = key.replace("\\", "/").lstrip("/")
    try:
        with session_context() as session:
            row = session.query(Assets.storage_provider).filter(Assets.storage_key == key).first()
            if row is not None:
                return provider_for(row.storage_provider).get_public_url(key) if row.storage_provider != LOCAL else None
            if key.startswith(f"{LIBRARY_STORAGE_PREFIX}/"):
                pack_id = key[len(LIBRARY_STORAGE_PREFIX) + 1 :].split("/", 1)[0]
                pack = session.get(CharacterPackModel, uuid.UUID(pack_id))
                for f in ((pack.pack if pack else None) or {}).get("files") or []:
                    if f.get("key") == key and library_file_provider(f) != LOCAL:
                        return provider_for(library_file_provider(f)).get_public_url(key)
    except Exception as e:  # unreadable database or provider: a plain 404, as before
        logger.warning(f"storage: couldn't look up where {key!r} moved: {e}")
    return None


class LocalAssetFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as e:
            if e.status_code != 404:
                raise
            url = await run_in_threadpool(moved_url, path)
            if url is None:
                raise
            return RedirectResponse(url, status_code=302)
