"""Blueprint kinds an integration needs beyond content: fields on an existing type, an incoming
webhook, and workflows. Same contract as every blueprint — create what is missing, never overwrite —
and anything that acts once switched on (webhooks, workflows) arrives switched off.

Driven by Square: it needs `sellOnline`/`shippingFee` on the workspace's own artwork type, a signed
webhook for Square's events, and three workflows that wire them together.
"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pytest import fixture

from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.groups.groups import Groups
from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel
from marvin.db.models.platform.entry_types import EntryTypes
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.routes._base.checks import OperationChecks
from marvin.schemas.platform.blueprints import Blueprint
from marvin.services.blueprints import already_applied, apply_blueprint, apply_many

ARTWORK_FIELDS = Blueprint(
    kind="entry_fields",
    slug="shop-fields",
    name="Shop fields",
    source="shop",
    parameters=[{"key": "entry_type", "label": "Which type", "kind": "entry_type", "default": "artwork"}],
    payload={
        "entry_type": "{{entry_type}}",
        "fields": [
            {"key": "sellOnline", "label": "Sell online", "type": "boolean"},
            {"key": "status", "label": "Status (shop's idea)", "type": "text"},
        ],
    },
)

WEBHOOK = Blueprint(
    kind="incoming_webhook",
    slug="shop-events",
    name="Shop events",
    source="shop",
    payload={"name": "Shop events", "signature_scheme": "square", "signing_secret_ref": "SHOP_SIGNATURE_KEY"},
)

WORKFLOW = Blueprint(
    kind="workflow",
    slug="shop-mark-sold",
    name="Shop: mark sold",
    source="shop",
    payload={
        "definition": {
            "trigger": {"type": "incoming_webhook", "webhook": "shop-events"},
            "conditions": [],
            "actions": [{"kind": "entry", "op": "set_data", "data": {"status": "sold"}}],
        }
    },
)


@fixture
def workspace(db_session):
    """A workspace with an `artwork` type (whose `status` is a customised select) and one user."""
    from marvin.db.models.users.users import Users

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"bk-{marker}", slug=f"bk-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    status_field = {"key": "status", "label": "Status", "type": "select", "options": ["available", "sold"]}
    db_session.add(EntryTypes(session=db_session, group_id=gid, name="Artwork", slug="artwork", schema_json={"fields": [status_field]}))
    uid = uuid.uuid4()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=gid,
            username=f"u-{marker}",
            email=f"u-{marker}@t.test",
            full_name="U",
            password="x",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
        )
    )
    db_session.commit()
    yield SimpleNamespace(id=gid, user_id=uid, status_field=status_field)

    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    purge_group_dependents(db_session, gid)
    db_session.query(Users).filter(Users.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _artwork(db_session, gid):
    db_session.expire_all()
    return db_session.query(EntryTypes).filter_by(group_id=gid, slug="artwork").one()


# --- entry_fields ---------------------------------------------------------------------------------


def test_entry_fields_adds_missing_fields_and_leaves_existing_ones_alone(db_session, workspace):
    result = apply_blueprint(db_session, workspace.id, ARTWORK_FIELDS, {"entry_type": "artwork"})

    fields = _artwork(db_session, workspace.id).schema_json["fields"]
    assert result.created and "sellOnline" in result.detail
    assert [f["key"] for f in fields] == ["status", "sellOnline"]
    assert fields[0] == workspace.status_field  # the customised select was not replaced by the declared text field


def test_entry_fields_second_apply_is_a_no_op(db_session, workspace):
    apply_blueprint(db_session, workspace.id, ARTWORK_FIELDS, {"entry_type": "artwork"})
    again = apply_blueprint(db_session, workspace.id, ARTWORK_FIELDS, {"entry_type": "artwork"})

    assert not again.created and "already has every field" in again.detail
    assert already_applied(db_session, workspace.id, ARTWORK_FIELDS, {"entry_type": "artwork"})


def test_entry_fields_on_a_type_the_workspace_lacks_is_refused(db_session, workspace):
    result = apply_blueprint(db_session, workspace.id, ARTWORK_FIELDS, {"entry_type": "painting"})
    assert not result.created and "painting" in result.detail


def test_entry_fields_that_break_the_schema_rules_change_nothing(db_session, workspace):
    bad = ARTWORK_FIELDS.model_copy(update={"payload": {"entry_type": "artwork", "fields": [{"key": "bad-key!", "label": "Bad", "type": "text"}]}})

    result = apply_blueprint(db_session, workspace.id, bad, {"entry_type": "artwork"})

    assert not result.created and "don't fit" in result.detail
    assert [f["key"] for f in _artwork(db_session, workspace.id).schema_json["fields"]] == ["status"]


# --- incoming_webhook -----------------------------------------------------------------------------


def test_incoming_webhook_is_created_disabled_without_a_token(db_session, workspace):
    result = apply_blueprint(db_session, workspace.id, WEBHOOK)

    hook = db_session.query(WorkspaceIncomingWebhookModel).filter_by(group_id=workspace.id, slug="shop-events").one()
    assert result.created
    assert hook.enabled is False and hook.token is None
    assert hook.signature_scheme == "square" and hook.signing_secret_ref == "SHOP_SIGNATURE_KEY"


def test_incoming_webhook_blueprint_cannot_carry_a_token():
    with pytest.raises(ValueError, match="token"):
        Blueprint(kind="incoming_webhook", slug="x", name="X", payload={"token": "leaked"})


# --- workflow -------------------------------------------------------------------------------------


def test_workflow_is_created_disabled_and_authored_by_whoever_applied_it(db_session, workspace):
    result = apply_blueprint(db_session, workspace.id, WORKFLOW, actor_id=workspace.user_id)

    row = db_session.query(WorkspaceAutomationModel).filter_by(group_id=workspace.id, slug="shop-mark-sold").one()
    assert result.created
    assert row.enabled is False and row.created_by == workspace.user_id
    assert row.definition["actions"][0]["op"] == "set_data"


def test_workflow_with_an_invalid_definition_is_not_created(db_session, workspace):
    broken = WORKFLOW.model_copy(update={"payload": {"definition": {"trigger": {"type": "telepathy"}, "actions": []}}})

    result = apply_blueprint(db_session, workspace.id, broken, actor_id=workspace.user_id)

    assert not result.created and "invalid" in result.detail
    assert db_session.query(WorkspaceAutomationModel).filter_by(group_id=workspace.id).count() == 0


def test_workflow_blueprint_needs_a_definition():
    with pytest.raises(ValueError, match="definition"):
        Blueprint(kind="workflow", slug="x", name="X", payload={})


def test_apply_many_builds_fields_and_webhook_before_workflows(db_session, workspace):
    results = apply_many(
        db_session, workspace.id, [WORKFLOW, WEBHOOK, ARTWORK_FIELDS], {"shop-fields": {"entry_type": "artwork"}}, actor_id=workspace.user_id
    )

    assert [r.kind for r in results] == ["entry_fields", "incoming_webhook", "workflow"]
    assert all(r.created for r in results)


# --- who may apply --------------------------------------------------------------------------------


def _checks(platform_role=PlatformRole.NONE, role=None, gid=None):
    user = SimpleNamespace(platform_role=platform_role, get_workspace_role=lambda group_id: role if group_id == gid else None)
    return OperationChecks(user)  # type: ignore[arg-type]


@pytest.mark.parametrize("role", [WorkspaceRole.OWNER, WorkspaceRole.ADMIN])
def test_applying_blueprints_is_allowed_for_owners_and_admins(role):
    gid = uuid.uuid4()
    assert _checks(role=role, gid=gid).can_manage_settings(gid)


@pytest.mark.parametrize("role", [WorkspaceRole.EDITOR, WorkspaceRole.VIEWER, None])
def test_applying_blueprints_is_refused_below_admin(role):
    gid = uuid.uuid4()
    with pytest.raises(HTTPException) as exc:
        _checks(role=role, gid=gid).can_manage_settings(gid)
    assert exc.value.status_code == 403


def test_parameterised_blueprint_applied_with_defaults_reads_as_applied(db_session, workspace):
    apply_blueprint(db_session, workspace.id, ARTWORK_FIELDS, {"entry_type": "artwork"})

    # The integration card checks without parameters; the default ("artwork") is what it applies.
    assert already_applied(db_session, workspace.id, ARTWORK_FIELDS) is True


def test_integration_parameter_must_name_a_connection_in_this_workspace(db_session, workspace):
    from marvin.db.models.groups.integrations import IntegrationModel

    db_session.add(IntegrationModel(session=db_session, group_id=workspace.id, provider="shop", name="Shop", slug="shop", enabled=True))
    db_session.commit()
    workflow = Blueprint(
        **{
            **WORKFLOW.model_dump(),
            "slug": "shop-uses-{{integration}}",
            "parameters": [{"key": "integration", "label": "Which connection", "kind": "integration", "default": "shop"}],
        }
    )

    refused = apply_blueprint(db_session, workspace.id, workflow, {"integration": "nope"}, actor_id=workspace.user_id)
    created = apply_blueprint(db_session, workspace.id, workflow, {"integration": "shop"}, actor_id=workspace.user_id)

    assert not refused.created and "no integration 'nope'" in refused.detail
    assert created.created and created.slug == "shop-uses-shop"


def test_integration_parameter_falls_back_to_the_only_connection(db_session, workspace):
    """The provider guesses "shop"; the workspace named its one connection "shop_main"."""
    from marvin.db.models.groups.integrations import IntegrationModel

    db_session.add(IntegrationModel(session=db_session, group_id=workspace.id, provider="shop", name="Shop", slug="shop_main", enabled=True))
    db_session.commit()
    workflow = Blueprint(
        **{
            **WORKFLOW.model_dump(),
            "slug": "shop-calls",
            "parameters": [{"key": "integration", "label": "Which connection", "kind": "integration", "default": "shop"}],
            "payload": {
                "definition": {
                    "trigger": {"type": "event", "event": "entry_published"},
                    "conditions": [],
                    "actions": [{"kind": "integration", "integration": "{{integration}}", "action": "ping"}],
                }
            },
        }
    )

    assert not already_applied(db_session, workspace.id, workflow)
    result = apply_blueprint(db_session, workspace.id, workflow, actor_id=workspace.user_id)

    row = db_session.query(WorkspaceAutomationModel).filter_by(group_id=workspace.id, slug="shop-calls").one()
    assert result.created and row.definition["actions"][0]["integration"] == "shop_main"
    assert already_applied(db_session, workspace.id, workflow)  # the card now ticks it
