"""Factory for creating storage provider instances."""

from pathlib import Path

from marvin.core.settings.settings import AppSettings

from .base_provider import BaseStorageProvider
from .local_provider import LocalStorageProvider
from .s3_provider import S3StorageProvider


def get_storage_provider(settings: AppSettings | None = None) -> BaseStorageProvider:
    """
    Get the configured storage provider.

    Args:
        settings: Application settings. If None, uses the global settings.

    Returns:
        BaseStorageProvider instance configured based on settings

    Raises:
        ValueError: If storage provider is unknown or misconfigured
    """
    if settings is None:
        from marvin.core import config

        settings = config.get_app_settings()

    provider = getattr(settings, "STORAGE_PROVIDER", "local")

    if provider == "local":
        root = getattr(settings, "STORAGE_LOCAL_ROOT", None)
        if root is None:
            # Default to {DATA_DIR}/assets directory
            from marvin.core.config import get_app_dirs

            root = get_app_dirs().ASSETS_DIR
        else:
            root = Path(root)

        public_url = getattr(settings, "STORAGE_LOCAL_PUBLIC_URL", "/assets")

        # STORAGE_LOCAL_PUBLIC_URL doubles as the static MOUNT path (see app.py), so it must stay a
        # "/..."-rooted path. To hand clients fully-qualified URLs — a CDN, a tunnel host, or a
        # decoupled frontend on another origin — set STORAGE_LOCAL_PUBLIC_BASE_URL; it overrides the
        # URL prefix only, while files still mount at STORAGE_LOCAL_PUBLIC_URL.
        public_base = getattr(settings, "STORAGE_LOCAL_PUBLIC_BASE_URL", None)
        if public_base:
            public_url = public_base
        elif not settings.PRODUCTION and not public_url.startswith("http"):
            # Dev: frontend (4321) and API (8080) are different origins, so prepend the API origin.
            public_url = f"http://localhost:{settings.API_PORT}{public_url}"

        return LocalStorageProvider(root=root, public_base_url=public_url)

    elif provider == "s3":
        bucket = getattr(settings, "STORAGE_S3_BUCKET", None)
        if not bucket:
            raise ValueError("STORAGE_S3_BUCKET is required for S3 storage provider")

        return S3StorageProvider(
            bucket=bucket,
            region=getattr(settings, "STORAGE_S3_REGION", "auto"),
            endpoint=getattr(settings, "STORAGE_S3_ENDPOINT", None),
            access_key=getattr(settings, "STORAGE_S3_ACCESS_KEY", None),
            secret_key=getattr(settings, "STORAGE_S3_SECRET_KEY", None),
            public_base_url=getattr(settings, "STORAGE_REMOTE_PUBLIC_URL", None),
        )

    else:
        raise ValueError(f"Unknown storage provider: {provider}")
