"""Platform secrets: credentials that belong to Marvin itself, not to a workspace (the platform SMTP password,
the URLs of platform alert channels).

They live in the configured secret backend under the **platform scope** (``group_id=None``). With the database backend
that is a ``workspace_secrets`` row whose ``group_id`` is NULL — no workspace API lists, reads or resolves it, because
every workspace query filters on its own group id, and ``{{SLUG}}`` resolution in a workspace never looks at the NULL
scope. Disk and vault keep them under ``_system``; the env backend reads ``MARVIN_SECRET_<SLUG>`` or ``<SLUG>`` and
cannot write (so saving one there fails with :class:`PlatformSecretReadOnly`).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from .factory import get_secret_backend


class PlatformSecretReadOnly(RuntimeError):
    """The secret backend can't store a value (the env backend); the operator sets it in the environment."""


def get_platform_secret(slug: str) -> str | None:
    """The value, or None when unset or the backend can't produce it."""
    return get_secret_backend().get(slug, None)


def set_platform_secret(slug: str, value: str, session: Session | None = None) -> None:
    """Store or overwrite. With a ``session`` the database backend writes through it, uncommitted."""
    try:
        get_secret_backend().set(slug, value, None, session)
    except NotImplementedError as e:
        raise PlatformSecretReadOnly(f"The {type(get_secret_backend()).__name__} is read-only: set {slug} in the server's environment.") from e


def delete_platform_secret(slug: str, session: Session | None = None) -> None:
    """Remove; a missing secret is not an error, nor is a read-only backend (nothing of ours to remove)."""
    try:
        get_secret_backend().delete(slug, None, session)
    except NotImplementedError:
        return


def platform_secret_set(slug: str) -> bool:
    return get_platform_secret(slug) is not None
