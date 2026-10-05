"""Email templates are scoped to their workspace.

/api/platform/workspaces/{group_id}/email-templates/{template_id} looked templates up by id alone, so a
member of workspace A could read workspace B's template through A's path, and an A admin could edit,
delete or test-send it. Email event subscriptions took any template_id, so an A subscription could send
B's template. Now a template resolves only if it is the path workspace's or a system template (no
workspace), and anything else gets the same 404 as a missing id. System templates read and test-send as
before and still can't be edited or deleted from the workspace routes.
"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pytest import fixture

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole

NOPE = "00000000-0000-4000-8000-000000000000"
SUBS = "/api/groups/email-event-subscriptions"


def _templates(gid) -> str:
    return f"/api/platform/workspaces/{gid}/email-templates"


@fixture
def world(db_session):
    """Workspaces A (the caller's) and B, a template in each, and a system template."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.email_event_subscriptions import EmailEventSubscriptionModel
    from marvin.db.models.groups.email_templates import EmailTemplateModel
    from marvin.db.models.users.users import Users

    marker = uuid.uuid4().hex[:8]
    a, b, uid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for gid, name in ((a, f"scope-a-{marker}"), (b, f"scope-b-{marker}")):
        group = Groups(session=db_session, name=name, slug=name)
        group.id = gid
        db_session.add(group)
    db_session.flush()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=a,
            username=f"scope-{marker}",
            email=f"scope-{marker}@t.test",
            full_name="SCOPE",
            password="x",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
        )
    )

    def template(group_id, name):
        row = EmailTemplateModel(session=db_session)
        row.group_id = group_id
        row.template_type = f"scope_test_{marker}"
        row.name = name
        row.subject = f"{name} subject"
        row.body_markdown = "Hello"
        row.enabled = True
        db_session.add(row)
        db_session.flush()
        return row.id

    ta, tb, system = template(a, "A's"), template(b, "B's"), template(None, "System")
    sub_b = EmailEventSubscriptionModel(session=db_session)
    sub_b.group_id, sub_b.template_id, sub_b.event_type, sub_b.enabled = b, tb, "entry_created", True
    db_session.add(sub_b)
    db_session.commit()
    sub_b_id = sub_b.id

    yield SimpleNamespace(a=a, b=b, uid=uid, ta=ta, tb=tb, system=system, sub_b=sub_b_id)

    app.dependency_overrides.pop(get_current_user, None)
    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    for gid in (a, b):
        db_session.query(EmailEventSubscriptionModel).filter(EmailEventSubscriptionModel.group_id == gid).delete()
        purge_group_dependents(db_session, gid)
    db_session.query(EmailTemplateModel).filter(EmailTemplateModel.template_type == f"scope_test_{marker}").delete()
    db_session.query(Users).filter(Users.id == uid).delete()
    db_session.query(Groups).filter(Groups.id.in_([a, b])).delete()
    db_session.commit()


def _sign_in(world, role: WorkspaceRole) -> TestClient:
    """The caller holds `role` in A and nothing in B (both role APIs agree)."""
    from marvin.db.models.users.roles import workspace_role_has_higher_or_equal_privilege

    def role_in(group_id):
        return role if str(group_id) == str(world.a) else None

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=world.uid,
        group_id=world.a,
        active_group_id=world.a,
        admin=False,
        is_superuser=False,
        full_name="SCOPE",
        email="scope@t.test",
        platform_role=PlatformRole.NONE,
        workspace_memberships=[SimpleNamespace(group_id=world.a, workspace_role=role)],
        get_workspace_role=role_in,
        has_workspace_role=lambda group_id, required: role_in(group_id) is not None
        and workspace_role_has_higher_or_equal_privilege(role_in(group_id), required),
    )
    return TestClient(app)


def _looks_missing(res, template_id) -> None:
    """Exactly the response a made-up id gets, so B's template ids don't leak."""
    assert res.status_code == 404, res.text
    assert res.json() == {"detail": f"Email template not found: {template_id}"}


def _template_row(db_session, template_id):
    from marvin.db.models.groups.email_templates import EmailTemplateModel

    db_session.expire_all()
    return db_session.get(EmailTemplateModel, template_id)


@pytest.mark.parametrize("role", [WorkspaceRole.VIEWER, WorkspaceRole.OWNER])
def test_another_workspaces_template_reads_as_missing(world, role):
    client = _sign_in(world, role)
    _looks_missing(client.get(f"{_templates(world.a)}/{world.tb}"), world.tb)
    _looks_missing(client.get(f"{_templates(world.a)}/{NOPE}"), NOPE)


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("PATCH", "", {"name": "Hijacked"}),
        ("DELETE", "", None),
        ("POST", "/test", {"recipient_email": "attacker@example.com"}),
    ],
    ids=["update", "delete", "test-send"],
)
@pytest.mark.parametrize("role", [WorkspaceRole.ADMIN, WorkspaceRole.OWNER])
def test_admin_cannot_change_or_send_another_workspaces_template(world, db_session, role, method, suffix, body):
    kwargs = {"json": body} if body is not None else {}
    res = _sign_in(world, role).request(method, f"{_templates(world.a)}/{world.tb}{suffix}", **kwargs)

    _looks_missing(res, world.tb)
    row = _template_row(db_session, world.tb)
    assert row is not None and row.name == "B's"


def test_own_templates_still_read_and_change(world):
    assert _sign_in(world, WorkspaceRole.VIEWER).get(f"{_templates(world.a)}/{world.ta}").json()["name"] == "A's"
    res = _sign_in(world, WorkspaceRole.ADMIN).patch(f"{_templates(world.a)}/{world.ta}", json={"name": "A renamed"})
    assert res.status_code == 200, res.text
    assert res.json()["name"] == "A renamed"


def test_system_templates_read_as_before_and_stay_read_only(world, db_session):
    member = _sign_in(world, WorkspaceRole.VIEWER)
    assert member.get(f"{_templates(world.a)}/{world.system}").json()["name"] == "System"
    assert str(world.system) in {t["id"] for t in member.get(_templates(world.a)).json()}

    admin = _sign_in(world, WorkspaceRole.ADMIN)
    assert admin.patch(f"{_templates(world.a)}/{world.system}", json={"name": "Edited"}).status_code == 403
    assert admin.delete(f"{_templates(world.a)}/{world.system}").status_code == 403
    sent = admin.post(f"{_templates(world.a)}/{world.system}/test", json={"recipient_email": "a@example.com"})
    assert sent.status_code not in (403, 404), sent.text
    assert _template_row(db_session, world.system).name == "System"


def _subscribe(client, template_id):
    return client.post(SUBS, json={"template_id": str(template_id), "event_type": "entry_created"})


def test_subscription_cannot_point_at_another_workspaces_template(world, db_session):
    from marvin.db.models.groups.email_event_subscriptions import EmailEventSubscriptionModel

    admin = _sign_in(world, WorkspaceRole.ADMIN)
    foreign, missing = _subscribe(admin, world.tb), _subscribe(admin, NOPE)

    assert foreign.status_code == missing.status_code == 404, foreign.text
    assert foreign.json() == missing.json()
    db_session.expire_all()
    assert db_session.query(EmailEventSubscriptionModel).filter_by(group_id=world.a).count() == 0


@pytest.mark.parametrize("which", ["ta", "system"])
def test_subscription_can_use_own_or_system_template(world, which):
    res = _subscribe(_sign_in(world, WorkspaceRole.ADMIN), getattr(world, which))
    assert res.status_code == 201, res.text


def test_admin_cannot_delete_another_workspaces_subscription(world, db_session):
    from marvin.db.models.groups.email_event_subscriptions import EmailEventSubscriptionModel

    res = _sign_in(world, WorkspaceRole.ADMIN).delete(f"{SUBS}/{world.sub_b}")

    assert res.status_code == 404, res.text
    db_session.expire_all()
    assert db_session.get(EmailEventSubscriptionModel, world.sub_b) is not None
