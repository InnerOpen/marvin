"""An integration's footprint (GET /api/groups/integrations/{id}/footprint): what its blueprints installed, by kind,
from the installed-by columns, plus the entry types its field blueprints changed.

The service half (services/blueprints/footprint.py) is SDK-free; the API half needs the integrations controller, which is
only mounted with marvin_integration_sdk, so it skips without it.
"""

import uuid

import pytest
from pytest import fixture
from sqlalchemy import event

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel
from marvin.db.models.groups.integrations import IntegrationModel
from marvin.db.models.groups.webhooks import GroupWebhooksModel
from marvin.db.models.platform.collections import Collections
from marvin.db.models.platform.entry_types import EntryTypes
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
from marvin.db.models.users.roles import WorkspaceRole
from marvin.schemas.platform.blueprints import Blueprint
from marvin.services.blueprints import footprint
from tests.test_integration_health import API, NEEDS_SDK, _sign_in, other, ws  # noqa: F401  (fixtures)

KINDS = ("workflows", "incomingWebhooks", "outgoingWebhooks", "scheduledTasks", "collections")


def _integration(db_session, gid, slug="mailer"):
    row = IntegrationModel(session=db_session, group_id=gid, provider="mailco", name=slug.title(), slug=slug, enabled=True, config={})
    db_session.add(row)
    db_session.flush()
    return row


def _install(db_session, gid, integration, tag="a"):
    """One row of every kind, installed by `integration`; returns their names by kind."""
    by = {"source_integration_id": integration.id, "source_blueprint": f"bp-{tag}"}
    db_session.add(
        WorkspaceAutomationModel(session=db_session, group_id=gid, name=f"Zeta flow {tag}", slug=f"zeta-{tag}", enabled=True, definition={}, **by)
    )
    db_session.add(
        WorkspaceAutomationModel(session=db_session, group_id=gid, name=f"alpha flow {tag}", slug=f"alpha-{tag}", enabled=False, definition={}, **by)
    )
    db_session.add(
        WorkspaceIncomingWebhookModel(session=db_session, group_id=gid, name=f"Hook {tag}", slug=f"hook-{tag}", enabled=False, token=None, **by)
    )
    db_session.add(GroupWebhooksModel(session=db_session, group_id=gid, name=f"Deploy {tag}", url="https://example.com/deploy", enabled=True, **by))
    db_session.add(
        ScheduledTaskModel(
            session=db_session,
            group_id=gid,
            name=f"Digest {tag}",
            slug=f"digest-{tag}",
            enabled=False,
            task_type="noop",
            schedule_type="interval",
            schedule_config={"minutes": 60},
            **by,
        )
    )
    db_session.add(Collections(session=db_session, group_id=gid, name=f"Subscribers {tag}", slug=f"subs-{tag}", **by))
    db_session.flush()


@fixture
def cleanup(db_session):
    yield
    db_session.rollback()
    for model in (WorkspaceAutomationModel, WorkspaceIncomingWebhookModel, GroupWebhooksModel, ScheduledTaskModel, Collections, EntryTypes):
        db_session.query(model).filter(model.source_integration_id.isnot(None) if hasattr(model, "source_integration_id") else False).delete(
            synchronize_session=False
        )
    db_session.commit()


def _get(client, integration_id):
    return client.get(f"{API}/{integration_id}/footprint")


# ── the service ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_installed_items_lists_each_kind_sorted_by_name(db_session, ws, cleanup):  # noqa: F811
    mailer = _integration(db_session, ws.gid)
    _install(db_session, ws.gid, mailer)
    found = footprint.installed_items(db_session, ws.gid, mailer.id)
    assert {k: [i.name for i in v] for k, v in found.items()} == {
        "workflows": ["alpha flow a", "Zeta flow a"],
        "incoming_webhooks": ["Hook a"],
        "outgoing_webhooks": ["Deploy a"],
        "scheduled_tasks": ["Digest a"],
        "collections": ["Subscribers a"],
    }
    assert [i.enabled for i in found["workflows"]] == [False, True]
    assert found["collections"][0].enabled is None


def test_it_is_one_query(db_session, ws, cleanup):  # noqa: F811
    mailer = _integration(db_session, ws.gid)
    _install(db_session, ws.gid, mailer)
    db_session.commit()
    gid, integration_id = ws.gid, mailer.id  # read now: after the commit they would reload
    seen = []
    bind = db_session.get_bind()

    def count(conn, cursor, statement, *a):
        seen.append(statement)

    event.listen(bind, "before_cursor_execute", count)
    try:
        footprint.installed_items(db_session, gid, integration_id)
    finally:
        event.remove(bind, "before_cursor_execute", count)
    assert len(seen) == 1


def test_other_integrations_and_your_own_items_are_left_out(db_session, ws, cleanup):  # noqa: F811
    mailer = _integration(db_session, ws.gid)
    shop = _integration(db_session, ws.gid, "shop2")
    _install(db_session, ws.gid, shop, "s")
    db_session.add(WorkspaceAutomationModel(session=db_session, group_id=ws.gid, name="Mine", slug="mine", enabled=True, definition={}))
    db_session.flush()
    found = footprint.installed_items(db_session, ws.gid, mailer.id)
    assert all(items == [] for items in found.values())


# ── entry-type fields and form settings ─────────────────────────────────────────────────────────────────────────


def _fields_bp(slug="signup-fields", entry_type="newsletter", fields=({"key": "email", "label": "Email", "type": "text"},), submission=None):
    payload = {"entry_type": entry_type, "fields": list(fields)}
    if submission:
        payload["submission"] = submission
    return Blueprint(kind="entry_fields", slug=slug, name=slug, source="mailco", payload=payload)


def _type(db_session, gid, slug="newsletter", name="Newsletter Signup", fields=(), caps=None):
    row = EntryTypes(session=db_session, group_id=gid, name=name, slug=slug, schema_json={"fields": list(fields)}, capabilities_json=caps)
    db_session.add(row)
    db_session.flush()
    return row


def test_field_changes_names_types_whose_blueprint_fields_are_in_place(db_session, ws, cleanup):  # noqa: F811
    mailer = _integration(db_session, ws.gid)
    _type(db_session, ws.gid, fields=[{"key": "email", "label": "Email", "type": "text"}])
    changes = footprint.field_changes(db_session, ws.gid, mailer.id, "mailco", [_fields_bp()])
    assert [c.label for c in changes] == ["Added fields to Newsletter Signup"]


def test_field_changes_ignores_blueprints_not_applied_or_without_a_type(db_session, ws, cleanup):  # noqa: F811
    mailer = _integration(db_session, ws.gid)
    _type(db_session, ws.gid)  # the type lacks the email field
    assert footprint.field_changes(db_session, ws.gid, mailer.id, "mailco", [_fields_bp()]) == []
    assert footprint.field_changes(db_session, ws.gid, mailer.id, "mailco", [_fields_bp(entry_type="nope")]) == []


def test_a_settings_only_blueprint_reads_as_form_settings_and_fields_win_per_type(db_session, ws, cleanup):  # noqa: F811
    mailer = _integration(db_session, ws.gid)
    caps = {"publishable": True, "submittable": True, "listed": False, "submission": {"kind": "signup", "destination": "audience"}}
    _type(db_session, ws.gid, fields=[{"key": "email", "label": "Email", "type": "text"}], caps=caps)
    settings = _fields_bp("signup-settings", fields=(), submission={"kind": "signup", "destination": "audience"})
    assert [c.label for c in footprint.field_changes(db_session, ws.gid, mailer.id, "mailco", [settings])] == [
        "Set form settings on Newsletter Signup"
    ]
    both = footprint.field_changes(db_session, ws.gid, mailer.id, "mailco", [settings, _fields_bp()])
    assert [c.label for c in both] == ["Added fields to Newsletter Signup"]


# ── the API ─────────────────────────────────────────────────────────────────────────────────────────────────────


@NEEDS_SDK
def test_api_returns_each_kind_and_a_total(db_session, ws, cleanup):  # noqa: F811
    mailer = _integration(db_session, ws.gid)
    _install(db_session, ws.gid, mailer)
    db_session.commit()
    body = _get(_sign_in(ws, WorkspaceRole.EDITOR), mailer.id).json()
    assert body["integrationId"] == str(mailer.id)
    assert {k: [i["name"] for i in body[k]] for k in KINDS} == {
        "workflows": ["alpha flow a", "Zeta flow a"],
        "incomingWebhooks": ["Hook a"],
        "outgoingWebhooks": ["Deploy a"],
        "scheduledTasks": ["Digest a"],
        "collections": ["Subscribers a"],
    }
    assert body["total"] == 6
    assert body["fieldChanges"] == []
    assert body["workflows"][0]["enabled"] is False and body["collections"][0]["enabled"] is None


@NEEDS_SDK
def test_api_for_an_integration_that_installed_nothing(db_session, ws, cleanup):  # noqa: F811
    mailer = _integration(db_session, ws.gid)
    db_session.commit()
    response = _get(_sign_in(ws, WorkspaceRole.EDITOR), mailer.id)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0 and body["fieldChanges"] == [] and all(body[k] == [] for k in KINDS)


@NEEDS_SDK
def test_api_is_workspace_isolated(db_session, ws, other, cleanup):  # noqa: F811
    theirs = _integration(db_session, other.gid, "theirs")
    _install(db_session, other.gid, theirs, "t")
    mine = _integration(db_session, ws.gid)
    db_session.commit()
    client = _sign_in(ws, WorkspaceRole.ADMIN)
    assert _get(client, theirs.id).status_code == 404
    assert _get(client, uuid.uuid4()).status_code == 404
    assert _get(client, mine.id).json()["total"] == 0


@NEEDS_SDK
def test_api_ignores_rows_of_another_workspace_that_point_at_this_integration(db_session, ws, other, cleanup):  # noqa: F811
    mine = _integration(db_session, ws.gid)
    # Not reachable through the app, but the query must not depend on that: scoped by group as well as integration.
    db_session.add(
        WorkspaceAutomationModel(
            session=db_session, group_id=other.gid, name="Stray", slug="stray", enabled=True, definition={}, source_integration_id=mine.id
        )
    )
    db_session.commit()
    assert _get(_sign_in(ws, WorkspaceRole.EDITOR), mine.id).json()["total"] == 0


@NEEDS_SDK
@pytest.mark.parametrize("role,status", [(WorkspaceRole.AUTHOR, 403), (WorkspaceRole.EDITOR, 200), (WorkspaceRole.ADMIN, 200)])
def test_api_needs_editor_or_above(db_session, ws, cleanup, role, status):  # noqa: F811
    mailer = _integration(db_session, ws.gid)
    db_session.commit()
    assert _get(_sign_in(ws, role), mailer.id).status_code == status
    app.dependency_overrides.pop(get_current_user, None)
