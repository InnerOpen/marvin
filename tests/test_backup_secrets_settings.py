"""Backup/restore must carry workspace settings — variables, AI policy, and secrets.

Secrets are the interesting case: their values are encrypted at rest with the installation SECRET,
so the raw ciphertext isn't portable. The exporter re-wraps each value under a per-workspace *backup
key* (downloadable, never in the bundle); the importer decrypts with the supplied key. Without a
usable key a secret restores as a valueless shell rather than failing the whole import.
"""

import uuid

import pytest
from pytest import fixture

from marvin.db.models.groups import Groups
from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
from marvin.db.models.groups.secrets import WorkspaceSecret
from marvin.db.models.groups.variables import WorkspaceVariable
from marvin.repos.all_repositories import get_repositories
from marvin.repos.seed.workspace_exporter import WorkspaceExporter
from marvin.repos.seed.workspace_seed_loader import WorkspaceSeedLoader
from marvin.services.backup.keys import (
    decrypt_secret_value,
    encrypt_secret_value,
    generate_backup_key,
    get_stored_backup_key,
)
from marvin.services.secrets import get_secret_backend
from marvin.services.secrets.backends.database import _get_fernet

SECRET_SLUG = "OPENAI_API_KEY"
SECRET_VALUE = "sk-live-super-secret-value"


def _make_group(db_session, marker: str) -> uuid.UUID:
    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"bk-{marker}", slug=f"bk-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.commit()
    return gid


@fixture
def source(db_session):
    """A source workspace with one secret, one variable, and an AI settings row."""
    marker = uuid.uuid4().hex[:8]
    gid = _make_group(db_session, marker)

    db_session.add(
        WorkspaceSecret(
            session=db_session,
            group_id=gid,
            name="OpenAI Key",
            slug=SECRET_SLUG,
            description="LLM credential",
            encrypted_value=_get_fernet().encrypt(SECRET_VALUE.encode()).decode(),
        )
    )
    db_session.add(
        WorkspaceVariable(
            session=db_session,
            group_id=gid,
            name="Site URL",
            slug="SITE_URL",
            description="canonical",
            value="https://example.com",
        )
    )
    db_session.add(
        WorkspaceAISettingsModel(
            session=db_session,
            group_id=gid,
            provider="openai",
            model="gpt-4o",
            secret_ref=SECRET_SLUG,
            assistant_name="Ziggy",
            default_register="playful",
        )
    )
    db_session.commit()

    created = [gid]
    yield gid, created

    for g in created:
        db_session.query(WorkspaceSecret).filter(WorkspaceSecret.group_id == g).delete()
        db_session.query(WorkspaceVariable).filter(WorkspaceVariable.group_id == g).delete()
        db_session.query(WorkspaceAISettingsModel).filter(WorkspaceAISettingsModel.group_id == g).delete()
        db_session.query(Groups).filter(Groups.id == g).delete()
    db_session.commit()


def test_backup_key_crypto_roundtrip():
    key = generate_backup_key()
    token = encrypt_secret_value(SECRET_VALUE, key)
    assert token != SECRET_VALUE
    assert decrypt_secret_value(token, key) == SECRET_VALUE

    # A different key cannot unwrap the value — this is what makes the bundle safe at rest.
    from cryptography.fernet import InvalidToken

    with pytest.raises(InvalidToken):
        decrypt_secret_value(token, generate_backup_key())


def test_export_wraps_secret_and_carries_settings(db_session, source):
    gid, _ = source
    repos = get_repositories(db_session, group_id=gid)

    data = WorkspaceExporter(repos).export_workspace()

    # Variables travel in plaintext.
    variables = {v["slug"]: v for v in data["variables"]}
    assert variables["SITE_URL"]["value"] == "https://example.com"

    # AI settings map camelCase; a secret is referenced by slug, never by value.
    assert data["ai_settings"]["provider"] == "openai"
    assert data["ai_settings"]["secretRef"] == SECRET_SLUG
    assert data["ai_settings"]["assistantName"] == "Ziggy"

    # The secret value is present but wrapped under the workspace backup key — not plaintext, and not
    # the at-rest ciphertext (which the installation SECRET, not the backup key, can decrypt).
    secret = next(s for s in data["secrets"] if s["slug"] == SECRET_SLUG)
    token = secret["encryptedBackupValue"]
    assert SECRET_VALUE not in token
    key = get_stored_backup_key(db_session, gid)
    assert key is not None
    assert decrypt_secret_value(token, key) == SECRET_VALUE


def test_restore_to_other_workspace_with_key_recovers_secret(db_session, source):
    gid, created = source
    repos = get_repositories(db_session, group_id=gid)
    data = WorkspaceExporter(repos).export_workspace()
    key = get_stored_backup_key(db_session, gid)

    # A different workspace, standing in for a different install — needs the downloaded key.
    target = _make_group(db_session, uuid.uuid4().hex[:8])
    created.append(target)

    result = WorkspaceSeedLoader(repos)._load_data(data, overwrite=True, target_group_id=str(target), backup_key=key)

    assert result["secrets"] == 1
    assert result["variables"] == 1
    assert result["ai_settings"] == 1

    # Secret value recovered and re-encrypted under the target instance backend.
    assert get_secret_backend().get(SECRET_SLUG, target) == SECRET_VALUE

    var = db_session.query(WorkspaceVariable).filter_by(group_id=target, slug="SITE_URL").one()
    assert var.value == "https://example.com"

    ai = db_session.query(WorkspaceAISettingsModel).filter_by(group_id=target).one()
    assert ai.provider == "openai" and ai.assistant_name == "Ziggy" and ai.default_register == "playful"


def test_restore_without_key_creates_valueless_shell(db_session, source):
    gid, created = source
    repos = get_repositories(db_session, group_id=gid)
    data = WorkspaceExporter(repos).export_workspace()

    target = _make_group(db_session, uuid.uuid4().hex[:8])
    created.append(target)

    # No key supplied and none stored for the target: the secret shell is created for re-entry.
    result = WorkspaceSeedLoader(repos)._load_data(data, overwrite=True, target_group_id=str(target), backup_key=None)

    assert result["secrets"] == 1
    shell = db_session.query(WorkspaceSecret).filter_by(group_id=target, slug=SECRET_SLUG).one()
    assert shell.name == "OpenAI Key"  # metadata preserved
    assert get_secret_backend().get(SECRET_SLUG, target) is None  # but no usable value


def test_restore_with_wrong_key_creates_shell_not_error(db_session, source):
    gid, created = source
    repos = get_repositories(db_session, group_id=gid)
    data = WorkspaceExporter(repos).export_workspace()

    target = _make_group(db_session, uuid.uuid4().hex[:8])
    created.append(target)

    result = WorkspaceSeedLoader(repos)._load_data(data, overwrite=True, target_group_id=str(target), backup_key=generate_backup_key())

    assert result["secrets"] == 1 and result["errors"] == 0
    assert get_secret_backend().get(SECRET_SLUG, target) is None
