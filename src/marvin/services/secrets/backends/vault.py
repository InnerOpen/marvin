"""
HashiCorp Vault secret backend (KV v2).

Secrets are stored at: {VAULT_MOUNT}/data/{VAULT_PATH_PREFIX}/{group_id}/{slug}

Settings:
    VAULT_ADDR          Vault server URL (e.g. http://127.0.0.1:8200)
    VAULT_TOKEN         Vault token (root or AppRole token)
    VAULT_MOUNT         KV v2 mount path (default: "secret")
    VAULT_PATH_PREFIX   Path prefix within mount (default: "marvin")
"""

from pydantic import UUID4
from sqlalchemy.orm import Session

from marvin.core.config import get_app_settings
from marvin.core.root_logger import get_logger

from ..base import SecretBackend

logger = get_logger(__name__)


def _get_client():
    try:
        import hvac
    except ImportError:
        raise RuntimeError("The 'hvac' package is required for the Vault secret backend. Install it: pip install hvac") from None
    settings = get_app_settings()
    if not settings.VAULT_ADDR or not settings.VAULT_TOKEN:
        raise RuntimeError("VAULT_ADDR and VAULT_TOKEN must be set for the vault backend.")
    client = hvac.Client(url=settings.VAULT_ADDR, token=settings.VAULT_TOKEN)
    if not client.is_authenticated():
        raise RuntimeError(f"Vault authentication failed at {settings.VAULT_ADDR}")
    return client


def _path(slug: str, group_id: UUID4 | None) -> str:
    settings = get_app_settings()
    prefix = settings.VAULT_PATH_PREFIX or "marvin"
    group_part = str(group_id) if group_id else "_system"
    return f"{prefix}/{group_part}/{slug}"


class VaultSecretBackend(SecretBackend):
    """HashiCorp Vault KV v2 secret backend."""

    def get(self, slug: str, group_id: UUID4 | None = None) -> str | None:
        settings = get_app_settings()
        mount = settings.VAULT_MOUNT or "secret"
        try:
            client = _get_client()
            result = client.secrets.kv.v2.read_secret_version(
                path=_path(slug, group_id),
                mount_point=mount,
                raise_on_deleted_version=True,
            )
            return result["data"]["data"].get("value")
        except Exception as e:
            logger.debug(f"Vault get '{slug}': {e}")
            return None

    def set(self, slug: str, value: str, group_id: UUID4 | None = None, session: Session | None = None) -> None:
        settings = get_app_settings()
        mount = settings.VAULT_MOUNT or "secret"
        client = _get_client()
        client.secrets.kv.v2.create_or_update_secret(
            path=_path(slug, group_id),
            secret={"value": value},
            mount_point=mount,
        )

    def delete(self, slug: str, group_id: UUID4 | None = None, session: Session | None = None) -> None:
        settings = get_app_settings()
        mount = settings.VAULT_MOUNT or "secret"
        client = _get_client()
        client.secrets.kv.v2.delete_metadata_and_all_versions(
            path=_path(slug, group_id),
            mount_point=mount,
        )

    def list_slugs(self, group_id: UUID4 | None = None) -> list[str]:
        settings = get_app_settings()
        mount = settings.VAULT_MOUNT or "secret"
        prefix = settings.VAULT_PATH_PREFIX or "marvin"
        group_part = str(group_id) if group_id else "_system"
        list_path = f"{prefix}/{group_part}"
        try:
            client = _get_client()
            result = client.secrets.kv.v2.list_secrets(
                path=list_path,
                mount_point=mount,
            )
            return result["data"].get("keys", [])
        except Exception:
            return []
