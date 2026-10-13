"""Secrets + variables through the Vault backend, plus the {{SLUG}} resolver.

The Vault-specific tests run only when Vault is configured (SECRET_BACKEND=vault +
VAULT_ADDR + VAULT_TOKEN) — the CI `vault-tests` job provides a Vault service container,
so the normal SQLite/Postgres runs skip them. The variable/resolver test needs no backend
and runs everywhere.
"""

import os
import uuid

import pytest

_VAULT_READY = os.getenv("SECRET_BACKEND") == "vault" and bool(os.getenv("VAULT_ADDR")) and bool(os.getenv("VAULT_TOKEN"))
requires_vault = pytest.mark.skipif(
    not _VAULT_READY,
    reason="Vault not configured (set SECRET_BACKEND=vault, VAULT_ADDR, VAULT_TOKEN)",
)


@pytest.fixture
def vault_backend():
    from marvin.services.secrets.factory import get_secret_backend

    return get_secret_backend()


@requires_vault
def test_factory_selects_vault(vault_backend):
    assert type(vault_backend).__name__ == "VaultSecretBackend"


@requires_vault
def test_secret_round_trips_and_deletes(vault_backend):
    gid = uuid.uuid4()
    vault_backend.set("MY_API_KEY", "sk-secret-123", gid)
    try:
        assert vault_backend.get("MY_API_KEY", gid) == "sk-secret-123"
        assert "MY_API_KEY" in vault_backend.list_slugs(gid)
    finally:
        vault_backend.delete("MY_API_KEY", gid)
    assert vault_backend.get("MY_API_KEY", gid) is None  # gone after delete


@requires_vault
def test_secret_is_group_scoped(vault_backend):
    gid = uuid.uuid4()
    vault_backend.set("SCOPED", "value", gid)
    try:
        assert vault_backend.get("SCOPED", uuid.uuid4()) is None  # a different workspace can't read it
    finally:
        vault_backend.delete("SCOPED", gid)


@requires_vault
def test_resolver_injects_vault_secret_and_guards_leaks(vault_backend):
    from marvin.services.secrets.resolver import resolve

    gid = uuid.uuid4()
    vault_backend.set("TOKEN", "abc123", gid)
    try:
        assert resolve("Bearer {{TOKEN}}", gid, allow_secrets=True) == "Bearer abc123"
        # allow_secrets=False (e.g. email-template content) must never surface the value
        assert "abc123" not in resolve("{{TOKEN}}", gid, allow_secrets=False)
    finally:
        vault_backend.delete("TOKEN", gid)


def test_resolver_injects_a_plaintext_variable(db_session):
    """Variables are plaintext DB config, resolved via {{SLUG}} — no secret backend needed."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.variables import WorkspaceVariable
    from marvin.services.secrets.resolver import resolve

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"vt-{marker}", slug=f"vt-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.commit()
    try:
        db_session.add(
            WorkspaceVariable(
                session=db_session,
                group_id=gid,
                name="Site URL",
                slug="SITE_URL",
                value="https://mashburn.co",
            )
        )
        db_session.commit()
        assert resolve("Visit {{SITE_URL}}", gid) == "Visit https://mashburn.co"
    finally:
        db_session.query(WorkspaceVariable).filter_by(group_id=gid).delete()
        db_session.query(Groups).filter_by(id=gid).delete()
        db_session.commit()
