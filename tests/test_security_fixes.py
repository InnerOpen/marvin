"""Fixes from the 2026-10-14 settings scan: reset links expire and a new one replaces the old; one minimum password
length everywhere; admin edits to system email templates survive a reseed; the agent step limit is a real setting."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from pydantic import ValidationError

from marvin.core import security

PASSWORD = "correct horse battery"


@pytest.fixture
def user(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.users import PasswordResetModel, Users

    gid, uid = uuid.uuid4(), uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"Reset {marker}", slug=f"reset-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    db_session.execute(
        sa.insert(Users.__table__).values(
            id=uid, group_id=gid, full_name="Reset Test", username=f"reset-{marker}", email=f"reset-{marker}@x.test",
            password=security.hash_password(PASSWORD), auth_method="MARVIN", is_superuser=False, platform_role="NONE", admin=False,
        )
    )  # fmt: skip
    db_session.commit()
    yield {"id": uid, "email": f"reset-{marker}@x.test"}
    db_session.rollback()
    db_session.query(PasswordResetModel).filter_by(user_id=uid).delete()
    db_session.query(Users).filter_by(id=uid).delete()
    db_session.query(Groups).filter_by(id=gid).delete()
    db_session.commit()


def _service(db_session):
    from marvin.services.user.password_reset_service import PasswordResetService

    return PasswordResetService(db_session)


def test_a_new_reset_request_replaces_the_earlier_link(db_session, user):
    from marvin.db.models.users import PasswordResetModel

    first = _service(db_session).generate_reset_token(user["email"]).token
    second = _service(db_session).generate_reset_token(user["email"]).token
    db_session.expire_all()
    live = [t.token for t in db_session.query(PasswordResetModel).filter_by(user_id=user["id"])]
    assert live == [second] and first != second


def test_an_expired_reset_link_is_refused_and_deleted(db_session, user):
    from marvin.db.models.users import PasswordResetModel

    token = _service(db_session).generate_reset_token(user["email"]).token
    row = db_session.query(PasswordResetModel).filter_by(token=token).one()
    row.created_at = (datetime.now(UTC) - timedelta(minutes=61)).replace(tzinfo=None)
    db_session.commit()

    with pytest.raises(HTTPException) as refused:
        _service(db_session).reset_password(token, "a brand new password", "a brand new password")
    assert refused.value.status_code == 400 and "expired" in refused.value.detail
    db_session.expire_all()
    assert db_session.query(PasswordResetModel).filter_by(token=token).count() == 0


def test_a_fresh_reset_link_still_works(db_session, user):
    token = _service(db_session).generate_reset_token(user["email"]).token
    assert _service(db_session).reset_password(token, "a brand new password", "a brand new password")


def test_the_daily_prune_deletes_expired_reset_links(db_session, user):
    from marvin.db.models.users import PasswordResetModel
    from marvin.services.scheduled_tasks.handlers.maintenance import _delete_expired_reset_tokens

    token = _service(db_session).generate_reset_token(user["email"]).token
    db_session.query(PasswordResetModel).filter_by(token=token).update({"created_at": datetime(2026, 1, 1, tzinfo=UTC)})
    db_session.commit()
    assert _delete_expired_reset_tokens(db_session) >= 1
    db_session.commit()
    assert db_session.query(PasswordResetModel).filter_by(token=token).count() == 0


@pytest.mark.parametrize(
    ("schema", "fields"),
    [
        ("marvin.schemas.user.registration:UserRegistrationCreate", {"email": "a@b.test", "username": "abc", "full_name": "A", "group": "g"}),
        ("marvin.schemas.user.password:ResetPassword", {"token": "t", "email": "a@b.test"}),
        ("marvin.schemas.user.user:ChangePassword", {"current_password": "x"}),
    ],
)
def test_one_minimum_password_length_everywhere(schema, fields):
    import importlib

    module, name = schema.split(":")
    cls = getattr(importlib.import_module(module), name)
    key = "new_password" if name == "ChangePassword" else "password"
    extra = {"password_confirm": "short"} if name == "UserRegistrationCreate" else {"passwordConfirm": "short"} if name == "ResetPassword" else {}
    with pytest.raises(ValidationError, match="at least 8 characters"):
        cls(**fields, **{key: "short"}, **extra)
    ok = {"password_confirm": PASSWORD} if name == "UserRegistrationCreate" else {"passwordConfirm": PASSWORD} if name == "ResetPassword" else {}
    cls(**fields, **{key: PASSWORD}, **ok)


def test_an_admin_edit_to_a_system_template_survives_a_reseed(db_session):
    from marvin.db.models.groups.email_templates import EmailTemplateModel
    from marvin.services.email.system_templates import SYSTEM_TEMPLATES, seed_system_templates

    seed_system_templates(db_session)
    defn = SYSTEM_TEMPLATES[0]
    tpl = db_session.query(EmailTemplateModel).filter_by(template_type=defn.template_type, group_id=None).one()
    original = (tpl.subject, tpl.body_markdown)
    try:
        tpl.subject = "Our own subject line"
        db_session.commit()
        seed_system_templates(db_session)  # a restart
        db_session.expire_all()
        tpl = db_session.query(EmailTemplateModel).filter_by(template_type=defn.template_type, group_id=None).one()
        assert tpl.subject == "Our own subject line"
    finally:
        tpl.subject, tpl.body_markdown = original
        db_session.commit()


def test_the_agent_step_limit_is_a_setting_with_a_cap(monkeypatch):
    from types import SimpleNamespace

    from marvin.core.config import get_app_settings
    from marvin.routes.ai.operations_controller import AIOperationsController

    settings = get_app_settings()
    monkeypatch.setattr(settings, "AI_AGENT_MAX_STEPS", 9)
    monkeypatch.setattr(settings, "AI_AGENT_MAX_STEPS_CAP", 10)
    no_workspace = SimpleNamespace(session=None, group_id=None)  # no workspace setting: the platform's applies

    def steps(body):
        return AIOperationsController._agent_max_steps(no_workspace, body)

    assert steps(SimpleNamespace(max_steps=None)) == 9
    assert steps(SimpleNamespace(max_steps=50)) == 10
    assert steps(SimpleNamespace(max_steps=3)) == 3
