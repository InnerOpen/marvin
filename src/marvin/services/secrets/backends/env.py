"""
Environment variable secret backend.

Reads secrets from server environment variables. Values are set by the
sysadmin (Docker secrets, Kubernetes secrets, Doppler, etc.) — Marvin
never writes to the environment. Zero storage, zero encryption overhead.

Slugs are resolved directly: {{MY_SECRET}} -> os.environ.get("MY_SECRET")
"""

import os

from pydantic import UUID4
from sqlalchemy.orm import Session

from ..base import SecretBackend

GLOBAL_PREFIX = "MARVIN_SECRET_"


def _workspace_prefix(group_id: UUID4 | None) -> str:
    """
    Build a workspace-scoped env var prefix.

    Resolution order for {{MY_KEY}} in workspace abc123:
      1. MARVIN_SECRET_ABC123_MY_KEY   (workspace-specific)
      2. MARVIN_SECRET_MY_KEY          (global fallback)
      3. MY_KEY                        (bare name fallback)
    """
    if group_id is None:
        return GLOBAL_PREFIX
    slug = str(group_id).replace("-", "").upper()[:8]  # first 8 hex chars
    return f"MARVIN_SECRET_{slug}_"


class EnvSecretBackend(SecretBackend):
    """
    Read-only backend that resolves secrets from environment variables.

    Lookup order for slug MY_KEY in workspace abc12345-...:
      MARVIN_SECRET_ABC12345_MY_KEY → MARVIN_SECRET_MY_KEY → MY_KEY

    This means operators can set global defaults and override per-workspace.
    list_slugs() returns both workspace-specific and global slugs visible
    to the given workspace.
    """

    def get(self, slug: str, group_id: UUID4 | None = None) -> str | None:
        ws_prefix = _workspace_prefix(group_id)
        return os.environ.get(f"{ws_prefix}{slug}") or os.environ.get(f"{GLOBAL_PREFIX}{slug}") or os.environ.get(slug)

    def set(self, slug: str, value: str, group_id: UUID4 | None = None, session: Session | None = None) -> None:
        raise NotImplementedError(
            "EnvSecretBackend is read-only. Set secrets in your environment (Docker secrets, Kubernetes secrets, .env file, etc.)"
        )

    def delete(self, slug: str, group_id: UUID4 | None = None, session: Session | None = None) -> None:
        raise NotImplementedError("EnvSecretBackend is read-only.")

    def list_slugs(self, group_id: UUID4 | None = None) -> list[str]:
        """Return slugs visible to this workspace (workspace-specific + global)."""
        ws_prefix = _workspace_prefix(group_id)
        slugs: set[str] = set()

        for key in os.environ:
            if key.startswith(ws_prefix):
                slugs.add(key[len(ws_prefix) :])
            elif key.startswith(GLOBAL_PREFIX):
                slugs.add(key[len(GLOBAL_PREFIX) :])

        return sorted(slugs)
