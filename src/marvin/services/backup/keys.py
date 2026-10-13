"""Per-workspace backup encryption keys.

Secrets are encrypted at rest with a key derived from the installation ``SECRET``
(see the database secret backend), so the raw ciphertext isn't portable — a
different install can't decrypt it. To let secrets survive a restore onto another
instance, each workspace gets its own Fernet **backup key** that wraps secret
values *inside* the export bundle.

The key is generated once, kept on the workspace row encrypted with the instance
secret (the same protection a stored secret gets), and offered to the operator to
download. It never travels inside the bundle — restoring elsewhere means supplying
the downloaded key. Because the key is only ever used at export/import time and
never for at-rest storage, rotating it costs nothing: old bundles just need the
old key.
"""

from marvin.core.root_logger import get_logger

logger = get_logger(__name__)


def generate_backup_key() -> str:
    """Return a fresh urlsafe-base64 Fernet key."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


def _instance_fernet():
    """Fernet bound to the installation secret — wraps the backup key at rest.

    Reuses the database secret backend's derivation so the stored backup key is
    protected exactly like a workspace secret.
    """
    from marvin.services.secrets.backends.database import _get_fernet

    return _get_fernet()


def get_or_create_backup_key(session, group_id) -> str:
    """Return the workspace's plaintext backup key, generating and storing it on first use."""
    from marvin.db.models.groups.groups import Groups

    group = session.get(Groups, group_id)
    if group is None:
        raise ValueError(f"Workspace not found: {group_id}")

    if group.backup_key_encrypted:
        try:
            return _instance_fernet().decrypt(group.backup_key_encrypted.encode()).decode()
        except Exception:
            # The instance secret changed (or the blob is corrupt): the stored key can't be
            # recovered, so existing bundles now rely on their downloaded copy. Mint a new key
            # for future backups rather than leaving the workspace unable to export.
            logger.error("Stored backup key for workspace %s failed to decrypt; generating a new one", group_id)

    key = generate_backup_key()
    group.backup_key_encrypted = _instance_fernet().encrypt(key.encode()).decode()
    session.commit()
    logger.info("Generated backup key for workspace %s", group_id)
    return key


def get_stored_backup_key(session, group_id) -> str | None:
    """Return the workspace's backup key if one is stored and decryptable, else None.

    Read-only — used on import to auto-recover secrets when restoring into the same
    workspace that produced the backup (no key supplied by the operator).
    """
    from marvin.db.models.groups.groups import Groups

    if group_id is None:
        return None
    group = session.get(Groups, group_id)
    if group is None or not group.backup_key_encrypted:
        return None
    try:
        return _instance_fernet().decrypt(group.backup_key_encrypted.encode()).decode()
    except Exception:
        logger.error("Stored backup key for workspace %s failed to decrypt", group_id)
        return None


def encrypt_secret_value(plaintext: str, backup_key: str) -> str:
    """Wrap a secret value with the workspace backup key for inclusion in a bundle."""
    from cryptography.fernet import Fernet

    return Fernet(backup_key.encode()).encrypt(plaintext.encode()).decode()


def decrypt_secret_value(token: str, backup_key: str) -> str:
    """Unwrap a bundled secret value with the workspace backup key.

    Raises ``cryptography.fernet.InvalidToken`` if the key is wrong or the token is corrupt.
    """
    from cryptography.fernet import Fernet

    return Fernet(backup_key.encode()).decrypt(token.encode()).decode()
