# ruff: noqa: F811  (the `workspace` fixture is imported)
"""Automation Lists 10: "Delete all of these" on a page's From a removed integration section.

An integration's delete sets ``source_integration_id`` to NULL on everything it installed (ON DELETE SET NULL) and leaves
``source_blueprint``, so a removed-integration item is one with a blueprint and no integration. Driven at the REST seam
(``DELETE /api/groups/removed-integration-items/{kind}``): ADMIN only, one kind at a time, only this workspace's removed items,
never an item of a live integration or one a person made; what the section lists is what goes.
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
from marvin.services.automation import removed_integration
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


@pytest.mark.parametrize("kind", ["workflows", "incoming-webhooks", "scheduled-tasks"])
def test_what_a_package_installed_is_never_taken_for_a_removed_integrations_leftovers(kind, workspace, db_session):
    # A package installs from blueprints with no integration behind them: the same two columns a removed integration leaves.
    gid = workspace.gid
    _, model = _make(kind, db_session, gid, "gone", source_blueprint="acme-flow")
    _make(kind, db_session, gid, "in-a-package", source_blueprint="story-flow", source_package="story-kit")
    db_session.commit()

    res = gates._sign_in(workspace, AD).delete(f"{URL}/{kind}")

    assert res.json()["names"] == ["gone"]
    db_session.expire_all()
    assert _names(db_session, model, gid) == {"in-a-package"}


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


def test_a_sibling_connection_of_the_same_provider_does_not_keep_the_leftovers(workspace, db_session):
    """A sandbox connection deleted, a production one of the same provider left: its six workflows are removed ones and go.
    The section lists them by that rule and the person confirmed them by name, so the server deletes exactly that list."""
    gid = workspace.gid
    _live_integration(db_session, gid, provider="acme")
    _make("workflows", db_session, gid, "left by the old acme", source_blueprint="acme-flow")
    _make("workflows", db_session, gid, "orphan", source_blueprint="other-flow")
    db_session.commit()
    res = gates._sign_in(workspace, AD).delete(f"{URL}/workflows")

    assert res.status_code == 200 and res.json()["names"] == ["left by the old acme", "orphan"]
    assert "skipped" not in res.json()
    db_session.expire_all()
    assert _names(db_session, WorkspaceAutomationModel, gid) == set()


# ---- the one exception: an incoming webhook stays with its provider -------------------------------------------------------


@pytest.fixture
def acme_webhook(monkeypatch):
    """The acme provider ships the `acme-events` incoming-webhook blueprint."""
    monkeypatch.setattr(removed_integration, "_webhook_providers", lambda: {"acme-events": "acme"})


def test_the_catalog_says_which_provider_ships_each_webhook_blueprint(monkeypatch):
    """Read from the providers themselves: only incoming-webhook blueprints, and a slug two providers both use says nothing."""
    sdk = pytest.importorskip("marvin_integration_sdk")

    def ship(provider, *blueprints):
        class _P(sdk.IntegrationProvider):
            name = provider

        _P.slug = provider
        _P.content = tuple(sdk.ContentBlueprint(kind=kind, slug=slug, name=slug, description="", payload={}) for kind, slug in blueprints)
        monkeypatch.setitem(sdk.INTEGRATION_REGISTRY, provider, _P())

    ship("acme", ("incoming_webhook", "acme-events"), ("workflow", "acme-flow"), ("incoming_webhook", "shared-events"))
    ship("other", ("incoming_webhook", "shared-events"))

    found = removed_integration._webhook_providers()

    assert found.get("acme-events") == "acme"
    assert "acme-flow" not in found and "shared-events" not in found


def _webhook_owner(session, webhook_id):
    session.expire_all()
    return session.get(WorkspaceIncomingWebhookModel, webhook_id).source_integration_id


def test_deleting_a_connection_hands_its_webhook_to_the_same_providers_connection_that_stays(workspace, db_session, acme_webhook):
    """Sandbox deleted, production left: the address the service posts to is production's now, and no longer a removed one's.
    The workflow the sandbox installed is still a removed integration's (that rule stands)."""
    gid = workspace.gid
    sandbox, production = _live_integration(db_session, gid), _live_integration(db_session, gid)
    hook, _ = _make("incoming-webhooks", db_session, gid, "Acme events", source_integration_id=sandbox, source_blueprint="acme-events")
    flow, _ = _make("workflows", db_session, gid, "Acme flow", source_integration_id=sandbox, source_blueprint="acme-flow")
    db_session.commit()
    admin = gates._sign_in(workspace, AD)

    assert admin.delete(f"/api/groups/integrations/{sandbox}").status_code == 204

    assert _webhook_owner(db_session, hook) == production
    assert db_session.get(WorkspaceAutomationModel, flow).source_integration_id is None
    assert admin.delete(f"{URL}/incoming-webhooks").json()["deleted"] == 0  # "Delete all of these" no longer reaches it


def test_a_webhook_whose_provider_has_no_connection_left_is_still_a_removed_one(workspace, db_session, acme_webhook):
    gid = workspace.gid
    only = _live_integration(db_session, gid)
    _live_integration(db_session, gid, provider="other")
    hook, _ = _make("incoming-webhooks", db_session, gid, "Acme events", source_integration_id=only, source_blueprint="acme-events")
    db_session.commit()

    assert gates._sign_in(workspace, AD).delete(f"/api/groups/integrations/{only}").status_code == 204

    assert _webhook_owner(db_session, hook) is None


def test_webhooks_orphaned_earlier_are_handed_over_and_the_rest_are_left(workspace, db_session, acme_webhook):
    """What startup does for the ones left behind before the rule: only a provider's own webhook, never a package's or a person's,
    and the connection that is switched on comes before one that is off."""
    gid = workspace.gid
    off, on = _live_integration(db_session, gid), _live_integration(db_session, gid)
    db_session.get(IntegrationModel, off).enabled = False
    orphan, _ = _make("incoming-webhooks", db_session, gid, "Acme events", source_blueprint="acme-events")
    unknown, _ = _make("incoming-webhooks", db_session, gid, "Unknown", source_blueprint="nobody-knows")
    packaged, _ = _make("incoming-webhooks", db_session, gid, "Packaged", source_blueprint="acme-events", source_package="kit")
    mine, _ = _make("incoming-webhooks", db_session, gid, "Mine")
    db_session.commit()

    assert removed_integration.keep_webhooks(db_session) == 1

    assert _webhook_owner(db_session, orphan) == on
    assert [_webhook_owner(db_session, i) for i in (unknown, packaged, mine)] == [None, None, None]
    assert removed_integration.keep_webhooks(db_session, gid) == 0  # nothing left to move


def test_of_two_connections_the_one_with_the_workflows_takes_the_webhook(workspace, db_session, acme_webhook):
    """A sandbox added back beside production: the webhook starts production's workflows, so it is production's, older or not."""
    gid = workspace.gid
    sandbox, production = _live_integration(db_session, gid), _live_integration(db_session, gid)
    _make("workflows", db_session, gid, "sandbox flow", source_integration_id=sandbox, source_blueprint="acme-flow")
    for n in range(3):
        _make("workflows", db_session, gid, f"production flow {n}", source_integration_id=production, source_blueprint="acme-flow")
    orphan, _ = _make("incoming-webhooks", db_session, gid, "Acme events", source_blueprint="acme-events")
    db_session.commit()

    assert removed_integration.keep_webhooks(db_session, gid) == 1

    assert _webhook_owner(db_session, orphan) == production


def test_an_unknown_kind_is_a_422(workspace):
    assert gates._sign_in(workspace, AD).delete(f"{URL}/collections").status_code == 422
