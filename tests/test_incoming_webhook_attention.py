"""Incoming webhooks that need a look: enabled and never received (Marvin does not record rejected deliveries, so that is the whole rule),
counted in the Automation summary, and the list API carrying the source fields the page groups by."""

# ruff: noqa: F811 — `workspace` is a fixture
import uuid
from datetime import UTC, datetime

from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel
from marvin.db.models.users.roles import WorkspaceRole
from marvin.services.automation import attention
from tests import test_content_role_gates as gates
from tests.test_automation_attention import _integration
from tests.test_content_role_gates import workspace  # noqa: F401 — fixture


def _hook(session, gid, name, *, enabled=True, received=0, integration=None, blueprint=None):
    row = WorkspaceIncomingWebhookModel(
        session=session,
        group_id=gid,
        name=name,
        slug=name.lower().replace(" ", "-"),
        enabled=enabled,
        token="tok-" + uuid.uuid4().hex,
        received_count=received,
        last_received_at=datetime.now(UTC) if received else None,
        source_integration_id=integration.id if integration else None,
        source_blueprint=blueprint,
    )
    session.add(row)
    session.commit()
    return row


def _client(workspace, role=WorkspaceRole.ADMIN):
    return gates._sign_in(workspace, role)


def test_an_enabled_webhook_that_never_received_anything_is_flagged(db_session, workspace):
    _hook(db_session, workspace.gid, "Silent")
    _hook(db_session, workspace.gid, "Live", received=4)
    _hook(db_session, workspace.gid, "Off and silent", enabled=False)

    assert attention.incoming_webhooks_needing_a_look(db_session, workspace.gid) == 1


def test_it_is_in_the_summary_with_its_page(db_session, workspace):
    _hook(db_session, workspace.gid, "Silent")

    found = _client(workspace).get("/api/automations/attention").json()

    assert found["kinds"]["incoming_webhooks"] == 1
    assert found["firstPage"] == "/automation/incoming-webhooks?status=attention"


def test_another_workspaces_webhooks_never_count(db_session, workspace):
    from marvin.db.models.groups import Groups
    from marvin.services.group.group_purge import purge_group_dependents

    other = Groups(session=db_session, name="iwa-x", slug=f"iwa-x-{uuid.uuid4().hex[:6]}")
    db_session.add(other)
    db_session.commit()
    try:
        _hook(db_session, other.id, "Theirs")
        assert attention.incoming_webhooks_needing_a_look(db_session, workspace.gid) == 0
        assert attention.incoming_webhooks_needing_a_look(db_session, other.id) == 1
    finally:
        db_session.rollback()
        purge_group_dependents(db_session, other.id)
        db_session.query(Groups).filter(Groups.id == other.id).delete()
        db_session.commit()


def test_the_list_carries_the_source_the_page_groups_by(db_session, workspace):
    integration = _integration(db_session, workspace.gid)
    _hook(db_session, workspace.gid, "Installed", integration=integration, blueprint="acme-hook")
    _hook(db_session, workspace.gid, "Orphan", blueprint="acme-old")  # its integration was removed
    _hook(db_session, workspace.gid, "Mine")

    rows = {r["name"]: r for r in _client(workspace).get("/api/incoming-webhooks").json()}

    assert (rows["Installed"]["sourceIntegrationId"], rows["Installed"]["sourceBlueprint"]) == (str(integration.id), "acme-hook")
    assert (rows["Orphan"]["sourceIntegrationId"], rows["Orphan"]["sourceBlueprint"]) == (None, "acme-old")
    assert (rows["Mine"]["sourceIntegrationId"], rows["Mine"]["sourceBlueprint"]) == (None, None)
