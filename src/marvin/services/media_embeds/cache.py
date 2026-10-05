"""The platform-wide media-embed cache (``media_embed_cache``): read in bulk for publishing, written on resolve."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from marvin.db.models._model_utils.datetime import get_utc_now
from marvin.db.models.platform.media_embed_cache import MediaEmbedCacheModel

from .resolver import ResolvedEmbed, resolve

OK_TTL = timedelta(days=30)
RETRY_TTL = timedelta(days=1)


def url_hash(url: str) -> str:
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()


def cached(session: Session, urls: Iterable[str]) -> dict[str, MediaEmbedCacheModel]:
    """Cached rows for these links (expired ones included — stale beats nothing on a read), keyed by link.
    One query; never calls out."""
    by_hash = {url_hash(u): u for u in urls if u}
    if not by_hash:
        return {}
    rows = session.query(MediaEmbedCacheModel).filter(MediaEmbedCacheModel.url_hash.in_(list(by_hash))).all()
    return {by_hash[r.url_hash]: r for r in rows if r.url_hash in by_hash}


def _is_fresh(row: MediaEmbedCacheModel | None) -> bool:
    if row is None or row.expires_at is None:
        return False
    return row.expires_at > get_utc_now()


def store(session: Session, resolved: ResolvedEmbed) -> MediaEmbedCacheModel:
    """Upsert one resolution (commits). A concurrent insert of the same link wins harmlessly."""
    now = get_utc_now()
    clean_ok = resolved.status == "ok" and resolved.settled and not resolved.error
    values = {
        "url": resolved.url,
        "provider": resolved.provider,
        "kind": resolved.kind,
        "status": resolved.status,
        "canonical_url": resolved.canonical_url,
        "embed_src": resolved.embed_src,
        "title": resolved.title,
        "author_name": resolved.author_name,
        "thumbnail_url": resolved.thumbnail_url,
        "width": resolved.width,
        "height": resolved.height,
        "aspect_ratio": resolved.aspect_ratio,
        "error": resolved.error,
        "fetched_at": now,
        "expires_at": now + (OK_TTL if clean_ok else RETRY_TTL),
    }
    h = url_hash(resolved.url)
    row = session.query(MediaEmbedCacheModel).filter(MediaEmbedCacheModel.url_hash == h).first()
    if row is None:
        row = MediaEmbedCacheModel(session=session, url_hash=h, **values)
        session.add(row)
    else:
        for k, v in values.items():
            setattr(row, k, v)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        row = session.query(MediaEmbedCacheModel).filter(MediaEmbedCacheModel.url_hash == h).first()
    return row


def resolve_cached(session: Session, url: str, *, refresh: bool = False, http=None) -> MediaEmbedCacheModel | None:
    """The cached resolution of a link, resolving (and caching) it when missing or expired.
    None when the link isn't a supported media link."""
    url = (url or "").strip()
    existing = cached(session, [url]).get(url)
    if existing is not None and not refresh and _is_fresh(existing):
        return existing
    resolved = resolve(url, http=http)
    if resolved is None:
        return None
    return store(session, resolved)


def warm(session: Session, urls: Iterable[str], *, limit: int = 20, http=None) -> int:
    """Resolve the links that have no fresh cache row (at most ``limit``). Returns how many were resolved."""
    wanted = list(dict.fromkeys(u.strip() for u in urls if u and u.strip()))[:limit]
    rows = cached(session, wanted)
    done = 0
    for url in wanted:
        if _is_fresh(rows.get(url)):
            continue
        resolved = resolve(url, http=http)
        if resolved is not None:
            store(session, resolved)
            done += 1
    return done
