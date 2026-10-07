"""Asset storage as the platform admin sees it (Admin → Storage): where new uploads go, which providers
could take them, and how many files live on each.

The choice of provider for new uploads is the admin's (``provider_factory.upload_target``); existing
files stay where they are (each row names its provider) until ``scripts/storage_migrate.py`` moves them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import sqlalchemy as sa

from . import provider_factory, registry

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class UnavailableProviderError(ValueError):
    """The provider can't take uploads: not installed, or its settings are incomplete."""


@dataclass
class ProviderOption:
    slug: str
    name: str
    source: str
    """``builtin``, ``core`` (core's temporary s3), or the plugin entry point that adds it."""
    available: bool
    error: str | None = None
    assets: int = 0
    bytes: int = 0
    library_files: int = 0


@dataclass
class WorkspaceUsage:
    workspace_id: str
    workspace: str
    provider: str
    assets: int
    bytes: int


@dataclass
class WorkspaceStorage:
    """A workspace's storage settings: the opaque prefix its keys get, and its own public domain."""

    workspace_id: str
    workspace: str
    storage_code: str | None
    asset_public_base_url: str | None


@dataclass
class StorageStatus:
    target: provider_factory.UploadTarget
    providers: list[ProviderOption]
    workspaces: list[WorkspaceUsage] = field(default_factory=list)
    workspace_settings: list[WorkspaceStorage] = field(default_factory=list)
    remote_public_base_url: str | None = None
    """``STORAGE_REMOTE_PUBLIC_URL``: the public domain of remote files whose workspace has none of its own."""


class InvalidPublicBaseURLError(ValueError):
    """Not a URL a workspace's files can be served from."""


MAX_PUBLIC_BASE_URL = 255


def validate_public_base_url(url: str | None, *, allow_http: bool = False) -> str | None:
    """``url`` as stored (no trailing ``/``), or None for empty. It must be an absolute ``https://`` URL
    with a host and nothing else: no user info, query or fragment (a path prefix is allowed).
    ``allow_http`` also accepts ``http://`` (development only)."""
    from urllib.parse import urlsplit

    url = (url or "").strip()
    if not url:
        return None
    if len(url) > MAX_PUBLIC_BASE_URL:
        raise InvalidPublicBaseURLError(f"at most {MAX_PUBLIC_BASE_URL} characters")
    try:
        parts = urlsplit(url)
        host, _ = parts.hostname, parts.port  # .port raises for a malformed port
    except ValueError as e:
        raise InvalidPublicBaseURLError(f"not a URL ({e})") from None
    schemes = ("https", "http") if allow_http else ("https",)
    if parts.scheme not in schemes:
        raise InvalidPublicBaseURLError("must start with https://" if not allow_http else "must start with https:// or http://")
    if not host or not all(c.isalnum() or c in ".-" for c in host) or host.startswith((".", "-")) or ".." in host:
        raise InvalidPublicBaseURLError("needs a host name, e.g. https://assets.example.com")
    if parts.username or parts.password or "@" in parts.netloc:
        raise InvalidPublicBaseURLError("must not carry a user name or password")
    if parts.query or parts.fragment or "?" in url or "#" in url:
        raise InvalidPublicBaseURLError("must not have a query string or fragment")
    if any(c.isspace() for c in url):
        raise InvalidPublicBaseURLError("must not contain spaces")
    return url.rstrip("/")


def workspace_settings(session: Session) -> list[WorkspaceStorage]:
    from marvin.db.models.groups import Groups

    rows = session.query(Groups.id, Groups.name, Groups.storage_code, Groups.asset_public_base_url).order_by(Groups.name)
    return [WorkspaceStorage(str(gid), name or str(gid), code, url) for gid, name, code, url in rows]


def set_workspace_public_base_url(session: Session, workspace_id, url: str | None, *, allow_http: bool = False) -> tuple[str, str | None, str | None]:
    """Give a workspace its own public domain for files on a remote provider (None: the provider's own).
    Returns (workspace name, previous, new). Raises ``InvalidPublicBaseURLError``, or ``LookupError``
    for an unknown workspace. The caller commits."""
    from marvin.db.models.groups import Groups

    url = validate_public_base_url(url, allow_http=allow_http)
    group = session.get(Groups, workspace_id)
    if group is None:
        raise LookupError(f"no workspace {workspace_id}")
    previous = group.asset_public_base_url
    group.asset_public_base_url = url
    session.flush()
    provider_factory.reset_workspace_public_bases()
    return group.name, previous, url


def remote_public_base_url() -> str | None:
    """``STORAGE_REMOTE_PUBLIC_URL`` as configured (shown next to the workspaces' own)."""
    try:
        return registry.settings_source(provider_factory._settings())[provider_factory.PUBLIC_URL_SETTING] or None
    except KeyError:
        return None


def check_available(slug: str) -> None:
    """Raise ``UnavailableProviderError`` unless ``slug`` is an installed, configured asset provider."""
    try:
        registry.get_plugin(slug, needs="provider")
        provider_factory.build_provider(slug, provider_factory._settings())
    except Exception as e:
        raise UnavailableProviderError(str(e) or type(e).__name__) from e


def library_file_counts(session: Session) -> dict[str, int]:
    """Character-library files per provider (a file without one predates per-file providers: local)."""
    from marvin.services.ai.character_library import library_file_provider, list_packs

    counts: dict[str, int] = {}
    for pack in list_packs(session):
        for f in (pack.pack or {}).get("files") or []:
            if f.get("key"):
                slug = library_file_provider(f)
                counts[slug] = counts.get(slug, 0) + 1
    return counts


def storage_status(session: Session) -> StorageStatus:
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import Assets

    provider_factory.reset_upload_choice()  # the admin page shows the stored choice, not a cached one
    target = provider_factory.upload_target()
    totals = {
        slug: (n, int(size or 0))
        for slug, n, size in session.query(Assets.storage_provider, sa.func.count(Assets.id), sa.func.sum(Assets.file_size)).group_by(
            Assets.storage_provider
        )
    }
    library = library_file_counts(session)

    options: list[ProviderOption] = []
    for slug, plugin in sorted(registry.plugins().items(), key=lambda kv: (kv[0] != registry.LOCAL, kv[0])):
        if plugin.provider is None:
            continue
        try:
            check_available(slug)
            available, error = True, None
        except UnavailableProviderError as e:
            available, error = False, str(e)
        n, size = totals.get(slug, (0, 0))
        options.append(
            ProviderOption(
                slug=slug,
                name=plugin.name or slug,
                source=registry.source_of(slug) or "",
                available=available,
                error=error,
                assets=n,
                bytes=size,
                library_files=library.get(slug, 0),
            )
        )
    # Rows on a provider that is no longer installed still count (and can't be served until it is back).
    known = {o.slug for o in options}
    for slug in sorted(set(totals) | set(library)):
        if slug not in known:
            n, size = totals.get(slug, (0, 0))
            options.append(
                ProviderOption(
                    slug=slug,
                    name=slug,
                    source="",
                    available=False,
                    error="not installed",
                    assets=n,
                    bytes=size,
                    library_files=library.get(slug, 0),
                )
            )

    rows = (
        session.query(Assets.group_id, Groups.name, Assets.storage_provider, sa.func.count(Assets.id), sa.func.sum(Assets.file_size))
        .join(Groups, Groups.id == Assets.group_id)
        .group_by(Assets.group_id, Groups.name, Assets.storage_provider)
        .order_by(Groups.name, Assets.storage_provider)
    )
    workspaces = [WorkspaceUsage(str(gid), name or str(gid), slug, n, int(size or 0)) for gid, name, slug, n, size in rows]
    return StorageStatus(
        target=target,
        providers=options,
        workspaces=workspaces,
        workspace_settings=workspace_settings(session),
        remote_public_base_url=remote_public_base_url(),
    )


def set_upload_provider(session: Session, slug: str | None) -> tuple[str | None, str | None]:
    """Make ``slug`` the provider for new uploads (None: follow ``STORAGE_PROVIDER``). Returns
    (previous choice, new choice). Raises ``UnavailableProviderError`` for a provider that can't take
    uploads now, so an admin can't pick one that would fall back at once."""
    slug = (slug or "").strip() or None
    if slug is not None:
        check_available(slug)
    provider_factory.reset_upload_choice()
    previous = provider_factory.chosen_upload_provider()
    provider_factory.save_upload_choice(session, slug)
    return previous, slug
