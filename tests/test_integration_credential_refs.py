"""An integration's credential can reference a workspace secret (`{{SQUARE_TOKEN}}`) instead of
holding its own copy — and deleting or re-keying the integration must never touch that shared secret."""

from types import SimpleNamespace

import pytest

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

from fastapi import HTTPException  # noqa: E402

from marvin.db.models.users.roles import PlatformRole, WorkspaceRole  # noqa: E402
from marvin.routes.groups import integrations_controller as ic  # noqa: E402

# Deleting an integration is workspace-admin only; the controller stand-ins act as an ADMIN of "G".
ADMIN = SimpleNamespace(admin=False, platform_role=PlatformRole.NONE, get_workspace_role=lambda gid: WorkspaceRole.ADMIN if gid == "G" else None)


@pytest.fixture
def secrets(monkeypatch):
    store = {"SQUARE_TOKEN": "tok-shared"}
    monkeypatch.setattr(ic, "resolve_secret", lambda slug, gid=None: store.get(slug))
    return store


def test_reference_to_an_existing_secret_is_used_as_is(secrets):
    assert ic._referenced_secret("{{ SQUARE_TOKEN }}", "G") == "SQUARE_TOKEN"


def test_a_plain_value_is_not_a_reference(secrets):
    assert ic._referenced_secret("EAAA-real-token", "G") is None


def test_reference_to_a_missing_secret_is_refused(secrets):
    with pytest.raises(HTTPException) as exc:
        ic._referenced_secret("{{NOPE}}", "G")
    assert exc.value.status_code == 422 and "NOPE" in exc.value.detail


def test_only_its_own_copy_counts_as_owned():
    assert ic._owns_secret(SimpleNamespace(slug="square", secret_ref="INTEGRATION_SQUARE"))
    assert not ic._owns_secret(SimpleNamespace(slug="square", secret_ref="SQUARE_TOKEN"))


def test_delete_leaves_a_referenced_secret_alone(monkeypatch):
    deleted = []
    monkeypatch.setattr(ic, "_delete_secret_quietly", lambda ref, gid: deleted.append(ref))
    row = SimpleNamespace(slug="square", secret_ref="SQUARE_TOKEN")
    session = SimpleNamespace(delete=lambda r: None, commit=lambda: None)
    ctrl = SimpleNamespace(_get_or_404=lambda i: row, session=session, group_id="G", user=ADMIN)

    ic.IntegrationsController.delete_integration(ctrl, "id")

    assert deleted == []


def test_delete_removes_its_own_copy(monkeypatch):
    deleted = []
    monkeypatch.setattr(ic, "_delete_secret_quietly", lambda ref, gid: deleted.append(ref))
    row = SimpleNamespace(slug="square", secret_ref="INTEGRATION_SQUARE")
    ctrl = SimpleNamespace(_get_or_404=lambda i: row, session=SimpleNamespace(delete=lambda r: None, commit=lambda: None), group_id="G", user=ADMIN)

    ic.IntegrationsController.delete_integration(ctrl, "id")

    assert deleted == ["INTEGRATION_SQUARE"]


def test_read_shows_which_workspace_secret_it_uses():
    row = SimpleNamespace(
        id="00000000-0000-4000-8000-000000000000",
        provider="square",
        name="Square",
        slug="square",
        enabled=True,
        config=None,
        secret_ref="SQUARE_TOKEN",
        status="ok",
        last_checked_at=None,
        last_error=None,
        error_overrides=None,
    )
    assert ic._to_read(row).credential_secret == "SQUARE_TOKEN"
