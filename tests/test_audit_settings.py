"""Per-workspace audit settings: an admin chooses which event types the Event Log records.

The catalog sets each type's default (`audited`); a workspace override wins over it, except for locked
(security) types, which are always audited, as is any type the catalog doesn't know. The listener reads the
overrides through a per-workspace cache that a write drops, and audits if the read fails. The API is
ADMIN/OWNER (the excluded list any member), refuses unknown (422) and locked (409) types, and records the
change itself as `workspace_settings_changed`, which is locked. Platform-scope types (the admin Events page's)
aren't workspace settings at all: never listed, refused (422), always audited.
"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pytest import fixture

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.services.event_bus_service.event_bus_listener import AuditLogListener
from marvin.services.event_bus_service.event_types import Event, EventBusMessage, EventTypes
from marvin.services.events import audit_settings
from marvin.services.events.event_catalog import CATALOG, PLATFORM_EVENT_TYPES, get_catalog_entry

URL = "/api/groups/audit-settings"
V, A, E, AD, OW = WorkspaceRole.VIEWER, WorkspaceRole.AUTHOR, WorkspaceRole.EDITOR, WorkspaceRole.ADMIN, WorkspaceRole.OWNER

# Default on, not locked: what the tests switch off.
ON = "entry_updated"
# Default off (internal plumbing), not locked.
OFF = "scheduled_task_started"


@fixture
def workspace(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.preferences import GroupPreferencesModel
    from marvin.db.models.users.users import Users

    gid, uid = uuid.uuid4(), uuid.uuid4()
    slug = f"audit-{gid.hex[:8]}"
    group = Groups(session=db_session, name=slug, slug=slug)
    group.id = gid
    db_session.add(group)
    db_session.flush()
    if db_session.query(GroupPreferencesModel).filter_by(group_id=gid).first() is None:
        db_session.add(GroupPreferencesModel(session=db_session, group_id=gid))
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=gid,
            username=slug,
            email=f"{slug}@t.test",
            full_name="AUDIT",
            password="x",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
        )
    )
    db_session.commit()
    audit_settings.invalidate()
    yield SimpleNamespace(gid=gid, uid=uid, slug=slug)
    app.dependency_overrides.pop(get_current_user, None)
    audit_settings.invalidate()
    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    purge_group_dependents(db_session, gid)
    db_session.query(Users).filter(Users.id == uid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _sign_in(workspace, role: WorkspaceRole | None, platform_role: PlatformRole = PlatformRole.NONE) -> TestClient:
    members = [SimpleNamespace(group_id=workspace.gid, workspace_role=role)] if role else []
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=workspace.uid,
        group_id=workspace.gid,
        active_group_id=workspace.gid,
        admin=False,
        is_superuser=False,
        full_name="AUDIT",
        email=f"{workspace.slug}@t.test",
        platform_role=platform_role,
        workspace_memberships=members,
        get_workspace_role=lambda group_id: role if str(group_id) == str(workspace.gid) else None,
    )
    return TestClient(app)


def _event(event_type: EventTypes) -> Event:
    return Event(message=EventBusMessage.from_type(event_type, ""), event_type=event_type, integration_id="test", document_data=None)


def _audited(gid, event_type: str) -> bool:
    return AuditLogListener(gid).get_subscribers(_event(EventTypes[event_type])) == ["database"]


def _store(db_session, gid, raw):
    """Write the overrides column directly (as another process would), bypassing the service."""
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    db_session.query(GroupPreferencesModel).filter_by(group_id=gid).update({"audit_overrides_json": raw})
    db_session.commit()


# ── catalog ─────────────────────────────────────────────────────────────────


def test_security_events_are_locked():
    locked = {e.event_type for e in CATALOG if e.audit_locked}
    for event_type in (
        "member_added",
        "member_role_changed",
        "member_removed",
        "invitation_created",
        "invitation_sent",
        "invitation_accepted",
        "invitation_revoked",
        "user_signup",
        "user_password_reset_requested",
        "workspace_settings_changed",  # the audit change itself is recorded as this
        "workspace_updated",
        "api_client_created",
        "api_client_token_rotated",
        "api_token_created",
        "secret_updated",
        "approval_granted",
    ):
        assert event_type in locked, event_type
    assert ON not in locked and OFF not in locked


def test_a_locked_entry_is_audited_by_default():
    assert [e.event_type for e in CATALOG if e.audit_locked and not e.audited] == []


def test_platform_events_are_locked():
    assert PLATFORM_EVENT_TYPES and all(get_catalog_entry(t).audit_locked for t in PLATFORM_EVENT_TYPES)


# ── listener ────────────────────────────────────────────────────────────────


def test_listener_uses_the_catalog_default_without_an_override(workspace):
    assert _audited(workspace.gid, ON)
    assert not _audited(workspace.gid, OFF)


def test_listener_honours_the_workspace_override(workspace, db_session):
    audit_settings.apply_changes(db_session, workspace.gid, {ON: False, OFF: True})
    assert not _audited(workspace.gid, ON)
    assert _audited(workspace.gid, OFF)


def test_override_is_per_workspace(workspace, db_session):
    audit_settings.apply_changes(db_session, workspace.gid, {ON: False})
    assert _audited(uuid.uuid4(), ON)


def test_listener_ignores_a_stored_override_on_a_locked_type(workspace, db_session):
    _store(db_session, workspace.gid, {"member_role_changed": False, "workspace_settings_changed": False})
    assert _audited(workspace.gid, "member_role_changed")
    assert _audited(workspace.gid, "workspace_settings_changed")


def test_an_uncatalogued_event_type_is_audited(workspace):
    assert get_catalog_entry("test_message") is None
    assert _audited(workspace.gid, "test_message")


def test_a_system_event_uses_the_default(workspace):
    assert AuditLogListener(None).get_subscribers(_event(EventTypes[ON])) == ["database"]
    assert AuditLogListener(None).get_subscribers(_event(EventTypes[OFF])) == []


def test_listener_audits_when_the_setting_cannot_be_read(workspace, db_session, monkeypatch):
    audit_settings.apply_changes(db_session, workspace.gid, {ON: False})
    audit_settings.invalidate()

    def broken(*_a, **_k):
        raise RuntimeError("database down")

    monkeypatch.setattr(audit_settings, "read_overrides", broken)
    assert _audited(workspace.gid, ON)
    monkeypatch.undo()
    assert not _audited(workspace.gid, ON)  # the failure wasn't cached


# ── cache ───────────────────────────────────────────────────────────────────


def test_a_write_drops_the_cache(workspace, db_session):
    assert _audited(workspace.gid, ON)  # cached: no overrides
    audit_settings.apply_changes(db_session, workspace.gid, {ON: False})
    assert not _audited(workspace.gid, ON)
    audit_settings.apply_changes(db_session, workspace.gid, {ON: None})
    assert _audited(workspace.gid, ON)


def test_the_cache_serves_repeat_reads_and_expires(workspace, db_session, monkeypatch):
    assert _audited(workspace.gid, ON)
    calls = []
    real = audit_settings.read_overrides
    monkeypatch.setattr(audit_settings, "read_overrides", lambda *a: calls.append(1) or real(*a))
    _store(db_session, workspace.gid, {ON: False})  # another process's write: no invalidation here
    assert _audited(workspace.gid, ON)  # still the cached map
    assert calls == []
    monkeypatch.setattr(audit_settings, "CACHE_TTL_SECONDS", 0.0)
    assert not _audited(workspace.gid, ON)  # expired: re-read
    assert calls == [1]


# ── service ─────────────────────────────────────────────────────────────────


def test_only_differences_from_the_default_are_stored(workspace, db_session):
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    overrides, changed = audit_settings.apply_changes(db_session, workspace.gid, {ON: True, OFF: False})
    assert overrides == {} and changed == {}
    overrides, changed = audit_settings.apply_changes(db_session, workspace.gid, {ON: False})
    assert overrides == {ON: False} and changed == {ON: False}
    overrides, changed = audit_settings.apply_changes(db_session, workspace.gid, {ON: None})
    assert overrides == {} and changed == {ON: None}
    prefs = db_session.query(GroupPreferencesModel).filter_by(group_id=workspace.gid).one()
    db_session.refresh(prefs)
    assert prefs.audit_overrides_json is None


def test_a_rejected_change_saves_nothing(workspace, db_session):
    with pytest.raises(audit_settings.LockedEventTypes):
        audit_settings.apply_changes(db_session, workspace.gid, {ON: False, "member_added": False})
    with pytest.raises(audit_settings.UnknownEventTypes):
        audit_settings.apply_changes(db_session, workspace.gid, {ON: False, "not_an_event": False})
    with pytest.raises(audit_settings.PlatformEventTypes):
        audit_settings.apply_changes(db_session, workspace.gid, {ON: False, "backup_started": False})
    assert audit_settings.read_overrides(db_session, workspace.gid) == {}


def test_listener_always_audits_a_platform_type(workspace, db_session):
    # backup_started sits in System (not a locked category): only its platform scope keeps it on.
    _store(db_session, workspace.gid, {"backup_started": False, "user_signup": False})
    assert _audited(workspace.gid, "backup_started")
    assert _audited(workspace.gid, "user_signup")
    assert audit_settings.read_overrides(db_session, workspace.gid) == {}


# ── API ─────────────────────────────────────────────────────────────────────


def test_get_lists_every_workspace_catalog_type(workspace):
    res = _sign_in(workspace, AD).get(URL)
    assert res.status_code == 200, res.text
    rows = {r["eventType"]: r for r in res.json()}
    assert set(rows) == {e.event_type for e in CATALOG if e.scope == "workspace"}
    assert not set(rows) & PLATFORM_EVENT_TYPES
    assert rows[ON] == {"eventType": ON, "name": "Entry Updated", "category": "Content", "defaultAudited": True, "audited": True, "locked": False}
    assert rows[OFF]["defaultAudited"] is False and rows[OFF]["audited"] is False
    assert rows["member_added"]["locked"] is True and rows["member_added"]["audited"] is True


def test_patch_sets_and_resets_overrides(workspace):
    client = _sign_in(workspace, AD)
    res = client.patch(URL, json={"overrides": {ON: False, OFF: True}})
    assert res.status_code == 200, res.text
    rows = {r["eventType"]: r for r in res.json()}
    assert rows[ON]["audited"] is False and rows[ON]["defaultAudited"] is True
    assert rows[OFF]["audited"] is True
    assert {r["eventType"] for r in client.get(f"{URL}/excluded").json()} >= {ON}
    assert OFF not in {r["eventType"] for r in client.get(f"{URL}/excluded").json()}

    rows = {r["eventType"]: r for r in client.patch(URL, json={"overrides": {ON: None}}).json()}
    assert rows[ON]["audited"] is True
    assert rows[OFF]["audited"] is True  # left out: kept


def test_patch_refuses_a_locked_type(workspace):
    res = _sign_in(workspace, AD).patch(URL, json={"overrides": {"member_role_changed": False}})
    assert res.status_code == 409
    assert "member_role_changed" in res.json()["detail"]


@pytest.mark.parametrize("event_type", ["user_signup", "workspace_created", "backup_completed"])
def test_patch_refuses_a_platform_type(workspace, event_type):
    res = _sign_in(workspace, AD).patch(URL, json={"overrides": {ON: False, event_type: False}})
    assert res.status_code == 422
    assert event_type in res.json()["detail"] and "Not a workspace event" in res.json()["detail"]


def test_patch_refuses_an_unknown_type(workspace):
    res = _sign_in(workspace, AD).patch(URL, json={"overrides": {"not_an_event": False}})
    assert res.status_code == 422
    assert "not_an_event" in res.json()["detail"]


def test_the_change_is_itself_logged(workspace, db_session):
    from marvin.db.models.platform.event_log import EventLogModel

    def logged():
        db_session.expire_all()
        return (
            db_session.query(EventLogModel)
            .filter(EventLogModel.workspace_id == workspace.gid, EventLogModel.event_type == "workspace_settings_changed")
            .all()
        )

    client = _sign_in(workspace, AD)
    # Switching everything that can be switched off still records the change.
    switchable = [e.event_type for e in CATALOG if not e.audit_locked]
    assert client.patch(URL, json={"overrides": dict.fromkeys(switchable, False)}).status_code == 200
    rows = logged()
    assert len(rows) == 1
    assert f"{ON} off" in rows[0].message_body
    assert str(rows[0].user_id) == str(workspace.uid)

    # A request that changes nothing records nothing.
    assert client.patch(URL, json={"overrides": {ON: False}}).status_code == 200
    assert len(logged()) == 1


@pytest.mark.parametrize("role", [V, A, E], ids=lambda r: r.value)
def test_below_admin_cannot_read_or_change(workspace, role):
    client = _sign_in(workspace, role)
    assert client.get(URL).status_code == 403
    assert client.patch(URL, json={"overrides": {ON: False}}).status_code == 403


@pytest.mark.parametrize("role", [AD, OW], ids=lambda r: r.value)
def test_admin_and_owner_can_read_and_change(workspace, role):
    client = _sign_in(workspace, role)
    assert client.get(URL).status_code == 200
    assert client.patch(URL, json={"overrides": {ON: False}}).status_code == 200


def test_super_admin_passes_and_non_member_is_refused(workspace):
    assert _sign_in(workspace, None, PlatformRole.SUPER_ADMIN).get(URL).status_code == 200
    outsider = _sign_in(workspace, None)
    assert outsider.get(URL).status_code == 403
    assert outsider.patch(URL, json={"overrides": {ON: False}}).status_code == 403
    assert outsider.get(f"{URL}/excluded").status_code == 403


def test_any_member_reads_the_excluded_list(workspace):
    res = _sign_in(workspace, V).get(f"{URL}/excluded")
    assert res.status_code == 200, res.text
    excluded = {r["eventType"] for r in res.json()}
    assert excluded == {e.event_type for e in CATALOG if not e.audited and not e.audit_locked}
    assert not excluded & PLATFORM_EVENT_TYPES
    assert set(res.json()[0]) == {"eventType", "name", "category"}
