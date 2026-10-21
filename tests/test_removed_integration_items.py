# ruff: noqa: F811  (the `workspace` fixture is imported)
"""Automation Lists 10: "Delete all of these" on a page's From a removed integration section.

An integration's delete sets ``source_integration_id`` to NULL on everything it installed (ON DELETE SET NULL) and leaves
``source_blueprint``, so a removed-integration item is one with a blueprint and no integration. Driven at the REST seam
(``DELETE /api/groups/removed-integration-items/{kind}``): ADMIN only, one kind at a time, only this workspace's removed items,
never an item of a live integration or one a person made.
"""

import uuid

import pytest

from marvin.db.models.groups import Groups
from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel
from marvin.db.models.groups.integrations import IntegrationModel
from marvin.db.models.groups.webhooks import GroupWebhooksModel
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
from marvin.db.models.users.roles import WorkspaceRole
from tests import test_content_role_gates as gates
from tests.test_content_role_gates import workspace  # noqa: F401

ED, AD = WorkspaceRole.EDITOR, WorkspaceRole.ADMIN
URL = "/api/groups/removed-integration-items"
KINDS = ["workflows", "incoming-webhooks", "scheduled-tasks", "outgoing-webhooks"]
_DEFINITION = {"trigger": {"type": "manual"}, "actions": []}


def _make(kind, session, gid, name, **provenance):
    slug = f"{name}-{uuid.uuid4().hex[:6]}"
    if kind == "workflows":
        row = WorkspaceAutomationModel(session=session, group_id=gid, name=name, slug=slug, enabled=True, definition=_DEFINITION)
    elif kind == "incoming-webhooks":
        row = WorkspaceIncomingWebhookModel(session=session, group_id=gid, name=name, slug=slug, enabled=True)
    elif kind == "scheduled-tasks":
        row = ScheduledTaskModel(
            session=session, group_id=gid, name=name, slug=slug, enabled=True, schedule_type="interval",
            schedule_config={"interval_seconds": 3600}, task_type="publish", task_config={},
        )  # fmt: skip
    else:
        row = GroupWebhooksModel(session=session, group_id=gid, name=name, enabled=True, url="https://example.com/h")
    for column, value in provenance.items():
        setattr(row, column, value)
    session.add(row)
    session.flush()
    return row.id, type(row)


def _live_integration(session, gid, provider="acme"):
    row = IntegrationModel(session=session, group_id=gid, provider=provider, name=provider, slug=f"{provider}-{uuid.uuid4().hex[:4]}", enabled=True)
    session.add(row)
    session.flush()
    return row.id


def _names(session, model, gid):
    return {r.name for r in session.query(model).filter(model.group_id == gid)}


@pytest.mark.parametrize("kind", KINDS)
def test_admin_deletes_only_the_removed_items_of_that_kind(kind, workspace, db_session):
    gid = workspace.gid
    live = _live_integration(db_session, gid)
    _, model = _make(kind, db_session, gid, "gone-1", source_blueprint="acme-flow")
    _make(kind, db_session, gid, "gone-2", source_blueprint="acme-flow")
    _make(kind, db_session, gid, "kept-live", source_integration_id=live, source_blueprint="acme-flow")
    _make(kind, db_session, gid, "kept-mine")
    db_session.commit()

    res = gates._sign_in(workspace, AD).delete(f"{URL}/{kind}")

    assert res.status_code == 200, res.text
    assert res.json()["deleted"] == 2
    assert sorted(res.json()["names"]) == ["gone-1", "gone-2"]
    db_session.expire_all()
    assert _names(db_session, model, gid) == {"kept-live", "kept-mine"}


def test_it_only_touches_the_kind_asked_for(workspace, db_session):
    gid = workspace.gid
    for kind in KINDS:
        _make(kind, db_session, gid, f"gone-{kind}", source_blueprint="acme-flow")
    db_session.commit()

    gates._sign_in(workspace, AD).delete(f"{URL}/workflows")

    db_session.expire_all()
    assert _names(db_session, WorkspaceAutomationModel, gid) == set()
    for model in (WorkspaceIncomingWebhookModel, ScheduledTaskModel, GroupWebhooksModel):
        assert len(_names(db_session, model, gid)) == 1


@pytest.mark.parametrize("role", [WorkspaceRole.VIEWER, WorkspaceRole.AUTHOR, ED])
@pytest.mark.parametrize("kind", KINDS)
def test_below_admin_is_refused_and_nothing_is_deleted(kind, role, workspace, db_session):
    _, model = _make(kind, db_session, workspace.gid, "gone", source_blueprint="acme-flow")
    db_session.commit()

    res = gates._sign_in(workspace, role).delete(f"{URL}/{kind}")

    assert res.status_code == 403
    db_session.expire_all()
    assert _names(db_session, model, workspace.gid) == {"gone"}


def test_owner_is_allowed(workspace, db_session):
    _make("workflows", db_session, workspace.gid, "gone", source_blueprint="acme-flow")
    db_session.commit()
    assert gates._sign_in(workspace, WorkspaceRole.OWNER).delete(f"{URL}/workflows").json()["deleted"] == 1


@pytest.mark.parametrize("kind", KINDS)
def test_another_workspaces_removed_items_are_left_alone(kind, workspace, db_session):
    other = uuid.uuid4()
    group = Groups(session=db_session, name=f"rm-{other.hex[:8]}", slug=f"rm-{other.hex[:8]}")
    group.id = other
    db_session.add(group)
    db_session.flush()
    try:
        _, model = _make(kind, db_session, other, "theirs", source_blueprint="acme-flow")
        _make(kind, db_session, workspace.gid, "ours", source_blueprint="acme-flow")
        db_session.commit()

        res = gates._sign_in(workspace, AD).delete(f"{URL}/{kind}")

        assert res.json()["names"] == ["ours"]
        db_session.expire_all()
        assert _names(db_session, model, other) == {"theirs"}
    finally:
        db_session.rollback()
        from marvin.services.group.group_purge import purge_group_dependents

        purge_group_dependents(db_session, other)
        db_session.query(Groups).filter(Groups.id == other).delete()
        db_session.commit()


def test_a_workflows_backing_schedule_goes_with_it(workspace, db_session):
    wf_id, _ = _make("workflows", db_session, workspace.gid, "gone", source_blueprint="acme-flow")
    task = ScheduledTaskModel(
        session=db_session, group_id=workspace.gid, name="wf", slug=f"wf-{wf_id}", enabled=True, schedule_type="interval",
        schedule_config={"interval_seconds": 60}, task_type="run_automation", task_config={},
    )  # fmt: skip
    db_session.add(task)
    db_session.commit()

    gates._sign_in(workspace, AD).delete(f"{URL}/workflows")

    db_session.expire_all()
    assert _names(db_session, ScheduledTaskModel, workspace.gid) == set()


def test_an_item_whose_providers_connection_is_still_here_is_skipped(workspace, db_session, monkeypatch):
    """No connection could be told at install (two of one provider): blueprint set, integration NULL, yet not removed."""
    from marvin.services.automation import removed_integration as removed

    gid = workspace.gid
    _live_integration(db_session, gid, provider="acme")
    _make("workflows", db_session, gid, "ambiguous", source_blueprint="acme-flow")
    _make("workflows", db_session, gid, "orphan", source_blueprint="other-flow")
    db_session.commit()
    monkeypatch.setattr(removed, "_provider_of", lambda slug: {"acme-flow": "acme"}.get(slug))  # the catalog's slug -> provider
    res = gates._sign_in(workspace, AD).delete(f"{URL}/workflows")

    assert res.json()["names"] == ["orphan"] and res.json()["skipped"] == 1


def test_an_unknown_kind_is_a_422(workspace):
    assert gates._sign_in(workspace, AD).delete(f"{URL}/collections").status_code == 422
