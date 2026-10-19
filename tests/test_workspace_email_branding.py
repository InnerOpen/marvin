"""A workspace's emails carry its own brand (services/email/branding.py, 2026-10-19): name, footer and colour each fall
back on their own — the name to the site title then the workspace name, the footer to "Sent by <name>", the colour to
the platform's. Emails with no workspace keep the platform's brand."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole, workspace_role_has_higher_or_equal_privilege
from marvin.services import platform_policy as pp
from marvin.services.email import branding
from marvin.services.email.email_service import EmailService, EmailTemplate

BRANDING = "/api/groups/email-branding"


@pytest.fixture
def workspace(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.preferences import GroupPreferencesModel
    from marvin.db.models.users.users import Users
    from marvin.services.group.group_purge import purge_group_dependents
    from marvin.services.platform_settings import PlatformSettingsService

    svc = PlatformSettingsService(db_session)
    saved_platform = svc.get(pp.EMAIL_BRANDING_KEY)
    pp.save_email_branding(db_session, {"product_name": "Platform Co", "footer_text": "Sent by the platform", "accent_color": "#112233"})

    marker = uuid.uuid4().hex[:8]
    gid, uid = uuid.uuid4(), uuid.uuid4()
    group = Groups(session=db_session, name=f"Brand {marker}", slug=f"brand-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    db_session.add(GroupPreferencesModel(session=db_session, group_id=gid))
    db_session.execute(
        Users.__table__.insert().values(
            id=uid, group_id=gid, username=f"brand-{marker}", email=f"brand-{marker}@t.test", full_name="BRAND",
            password="x", is_superuser=False, platform_role="NONE", auth_method="MARVIN",
        )
    )  # fmt: skip
    db_session.commit()

    yield SimpleNamespace(id=gid, uid=uid, name=group.name)

    app.dependency_overrides.pop(get_current_user, None)
    db_session.rollback()
    purge_group_dependents(db_session, gid)
    db_session.query(Users).filter(Users.id == uid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()
    svc.set(pp.EMAIL_BRANDING_KEY, saved_platform or {})
    pp.clear_cache()


def _set_site_title(db_session, gid, title):
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    prefs = db_session.query(GroupPreferencesModel).filter_by(group_id=gid).one()
    prefs.site_title = title
    db_session.commit()


def _sign_in(ws, role: WorkspaceRole) -> TestClient:
    def role_in(group_id):
        return role if str(group_id) == str(ws.id) else None

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=ws.uid, group_id=ws.id, active_group_id=ws.id, admin=False, is_superuser=False, full_name="BRAND",
        email="brand@t.test", platform_role=PlatformRole.NONE,
        workspace_memberships=[SimpleNamespace(group_id=ws.id, workspace_role=role)],
        get_workspace_role=role_in,
        has_workspace_role=lambda group_id, required: role_in(group_id) is not None
        and workspace_role_has_higher_or_equal_privilege(role_in(group_id), required),
    )  # fmt: skip
    return TestClient(app)


def _html(group_id=None) -> str:
    return EmailService(group_id=str(group_id) if group_id else None).render(EmailTemplate(subject="Hi", header_text="Hello", message_top="Body"))


# ── how the brand falls back ─────────────────────────────────────────────────


def test_an_unset_workspace_brand_is_its_name_and_the_platforms_colour(db_session, workspace):
    effective = branding.workspace_branding_view(db_session, workspace.id)["effective"]
    assert effective == {"product_name": workspace.name, "footer_text": f"Sent by {workspace.name}", "accent_color": "#112233"}


def test_the_site_title_names_the_workspace_when_it_has_one(db_session, workspace):
    _set_site_title(db_session, workspace.id, "Mash & Burn Co.")
    effective = branding.workspace_branding_view(db_session, workspace.id)["effective"]
    assert effective["product_name"] == "Mash & Burn Co." and effective["footer_text"] == "Sent by Mash & Burn Co."


def test_each_set_value_wins_and_a_blank_one_falls_back(db_session, workspace):
    view = branding.save_workspace_branding(db_session, workspace.id, {"product_name": "Workshop", "footer_text": "", "accent_color": "#AA3300"})
    assert view["product_name"] == "Workshop" and view["footer_text"] == "" and view["accent_color"] == "#aa3300"
    assert view["effective"] == {"product_name": "Workshop", "footer_text": "Sent by Workshop", "accent_color": "#aa3300"}

    cleared = branding.save_workspace_branding(db_session, workspace.id, {})
    assert cleared["effective"]["product_name"] == workspace.name and cleared["effective"]["accent_color"] == "#112233"


def test_a_bad_colour_is_refused(db_session, workspace):
    with pytest.raises(pp.PolicyError, match="hex colour"):
        branding.save_workspace_branding(db_session, workspace.id, {"accent_color": "orange"})


# ── what the email shows ─────────────────────────────────────────────────────


def test_a_workspace_email_shows_the_workspace_brand_not_the_platforms(db_session, workspace):
    branding.save_workspace_branding(db_session, workspace.id, {"product_name": "Workshop", "accent_color": "#aa3300"})
    html = _html(workspace.id)
    assert "Workshop" in html and "Sent by Workshop" in html and "#aa3300" in html
    assert "Platform Co" not in html and "Sent by the platform" not in html


def test_an_email_without_a_workspace_keeps_the_platform_brand(db_session, workspace):
    branding.save_workspace_branding(db_session, workspace.id, {"product_name": "Workshop"})
    html = _html()
    assert "Platform Co" in html and "Sent by the platform" in html and "Workshop" not in html


def test_a_per_workspace_layout_file_no_longer_replaces_the_layout(db_session, workspace):
    """Retired: the brand is what differs per workspace now, so a file in the data templates dir under the workspace's id
    is ignored."""
    service = EmailService(group_id=str(workspace.id))
    folder = service.directories.TEMPLATE_DIR / str(workspace.id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / service.settings.EMAIL_TEMPLATE).write_text("WORKSPACE FILE {{ data.subject }}")
    try:
        assert "WORKSPACE FILE" not in _html(workspace.id)
    finally:
        (folder / service.settings.EMAIL_TEMPLATE).unlink()
        folder.rmdir()


# ── the API ──────────────────────────────────────────────────────────────────


def test_an_admin_reads_and_sets_the_branding(workspace):
    client = _sign_in(workspace, WorkspaceRole.ADMIN)
    res = client.get(BRANDING)
    assert res.status_code == 200, res.text
    assert res.json()["productName"] == "" and res.json()["effective"]["productName"] == workspace.name

    res = client.put(BRANDING, json={"productName": "Workshop", "footerText": "", "accentColor": "#aa3300"})
    assert res.status_code == 200, res.text
    assert res.json()["effective"] == {"productName": "Workshop", "footerText": "Sent by Workshop", "accentColor": "#aa3300"}

    assert client.put(BRANDING, json={"accentColor": "red"}).status_code == 422


def test_an_editor_cannot_read_or_change_the_branding(workspace):
    client = _sign_in(workspace, WorkspaceRole.EDITOR)
    assert client.get(BRANDING).status_code == 403
    assert client.put(BRANDING, json={"productName": "Nope"}).status_code == 403


def test_a_template_test_goes_through_the_workspace(db_session, workspace, monkeypatch):
    """Its sender, layout and brand, with the workspace's real name — what its recipients would get."""
    from marvin.db.models.groups.email_templates import EmailTemplateModel

    row = EmailTemplateModel(session=db_session)
    row.group_id, row.template_type, row.name = workspace.id, f"brand_test_{uuid.uuid4().hex[:6]}", "Brand test"
    row.subject, row.body_markdown, row.enabled = "Hello", "Hi there", True
    db_session.add(row)
    db_session.commit()

    seen = {}

    def fake_send(self, recipient, template, variables):
        seen.update(group_id=self.group_id, workspace_name=variables["workspace_name"])
        return True

    monkeypatch.setattr(EmailService, "_send_db_template", fake_send)
    client = _sign_in(workspace, WorkspaceRole.ADMIN)
    res = client.post(f"/api/platform/workspaces/{workspace.id}/email-templates/{row.id}/test", json={"recipient_email": "someone@example.com"})
    assert res.status_code == 200, res.text
    assert seen == {"group_id": str(workspace.id), "workspace_name": workspace.name}
