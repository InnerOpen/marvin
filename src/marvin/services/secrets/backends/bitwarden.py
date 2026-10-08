"""
Bitwarden Secrets Manager backend.

Secrets are stored in a Bitwarden Secrets Manager project, identified
by BITWARDEN_PROJECT_ID. Workspace isolation is achieved by naming
convention: "{group_id}/{slug}".

Settings:
    BITWARDEN_ACCESS_TOKEN   Machine account access token
    BITWARDEN_PROJECT_ID     Project UUID to scope secrets to
    BITWARDEN_API_URL        (optional) Custom API URL for self-hosted
    BITWARDEN_IDENTITY_URL   (optional) Custom identity URL for self-hosted
"""

from pydantic import UUID4
from sqlalchemy.orm import Session

from marvin.core.config import get_app_settings
from marvin.core.root_logger import get_logger

from ..base import SecretBackend

logger = get_logger(__name__)


def _get_client():
    try:
        import bitwarden_sdk as bw
    except ImportError:
        raise RuntimeError(
            "The 'bitwarden-sdk' package is required for the Bitwarden secret backend. Install it: pip install bitwarden-sdk"
        ) from None
    settings = get_app_settings()
    if not settings.BITWARDEN_ACCESS_TOKEN:
        raise RuntimeError("BITWARDEN_ACCESS_TOKEN must be set for the bitwarden backend.")

    client = bw.BitwardenClient(
        bw.ClientSettings(
            api_url=settings.BITWARDEN_API_URL or "https://api.bitwarden.com",
            identity_url=settings.BITWARDEN_IDENTITY_URL or "https://identity.bitwarden.com",
            user_agent="Marvin CMS",
            device_type=bw.DeviceType.SDK,
        )
    )
    client.access_token_login(settings.BITWARDEN_ACCESS_TOKEN)
    return client


def _key(slug: str, group_id: UUID4 | None) -> str:
    group_part = str(group_id) if group_id else "_system"
    return f"{group_part}/{slug}"


class BitwardenSecretBackend(SecretBackend):
    """Bitwarden Secrets Manager backend."""

    def get(self, slug: str, group_id: UUID4 | None = None) -> str | None:
        settings = get_app_settings()
        key = _key(slug, group_id)
        try:
            client = _get_client()
            secrets = client.secrets().list(settings.BITWARDEN_PROJECT_ID)
            for secret in secrets.data.data if secrets.data else []:
                if secret.key == key:
                    detail = client.secrets().get(secret.id)
                    return detail.data.value if detail.data else None
        except Exception as e:
            logger.debug(f"Bitwarden get '{slug}': {e}")
        return None

    def set(self, slug: str, value: str, group_id: UUID4 | None = None, session: Session | None = None) -> None:
        settings = get_app_settings()
        key = _key(slug, group_id)
        client = _get_client()
        # Check if it exists first
        secrets = client.secrets().list(settings.BITWARDEN_PROJECT_ID)
        existing_id = None
        for secret in secrets.data.data if secrets.data else []:
            if secret.key == key:
                existing_id = secret.id
                break

        if existing_id:
            client.secrets().update(
                existing_id,
                key=key,
                value=value,
                note="Managed by Marvin CMS",
                project_ids=[settings.BITWARDEN_PROJECT_ID],
            )
        else:
            client.secrets().create(
                key=key,
                value=value,
                note="Managed by Marvin CMS",
                project_ids=[settings.BITWARDEN_PROJECT_ID],
            )

    def delete(self, slug: str, group_id: UUID4 | None = None, session: Session | None = None) -> None:
        settings = get_app_settings()
        key = _key(slug, group_id)
        client = _get_client()
        secrets = client.secrets().list(settings.BITWARDEN_PROJECT_ID)
        ids_to_delete = [s.id for s in (secrets.data.data if secrets.data else []) if s.key == key]
        if ids_to_delete:
            client.secrets().delete(ids_to_delete)

    def list_slugs(self, group_id: UUID4 | None = None) -> list[str]:
        settings = get_app_settings()
        prefix = _key("", group_id)  # e.g. "abc-123/"
        try:
            client = _get_client()
            secrets = client.secrets().list(settings.BITWARDEN_PROJECT_ID)
            return [s.key[len(prefix) :] for s in (secrets.data.data if secrets.data else []) if s.key.startswith(prefix)]
        except Exception:
            return []
