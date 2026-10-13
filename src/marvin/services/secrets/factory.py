"""Secret backend factory — returns the configured backend instance."""

from functools import lru_cache

from marvin.core.config import get_app_settings

from .base import SecretBackend


@lru_cache(maxsize=1)
def get_secret_backend() -> SecretBackend:
    """Return the configured secret backend (cached per process)."""
    backend = get_app_settings().SECRET_BACKEND.lower()

    if backend == "vault":
        from .backends.vault import VaultSecretBackend

        return VaultSecretBackend()

    if backend == "bitwarden":
        from .backends.bitwarden import BitwardenSecretBackend

        return BitwardenSecretBackend()

    if backend == "disk":
        from .backends.disk import DiskSecretBackend

        return DiskSecretBackend()

    if backend == "env":
        from .backends.env import EnvSecretBackend

        return EnvSecretBackend()

    # Default: database
    from .backends.database import DatabaseSecretBackend

    return DatabaseSecretBackend()
