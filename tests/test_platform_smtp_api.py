"""Admin → Email → Platform SMTP (/api/admin/email/platform-smtp): per-field overrides over the environment.

The password is write-only (stored as the platform secret PLATFORM_SMTP_PASSWORD, never returned), every change is
audited as ``platform_settings_changed`` with no workspace, and "Use environment settings" clears every admin field.
"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pytest import fixture

from marvin.app import app
from marvin.core.config import get_app_settings
from marvin.core.dependencies import get_current_user
from marvin.db.models.groups.secrets import WorkspaceSecret
from marvin.db.models.platform.event_log import EventLogModel
from marvin.db.models.users.roles import PlatformRole
from marvin.services import platform_smtp
from marvin.services.email import email_senders
from marvin.services.secrets.platform import get_platform_secret

API = "/api/admin/email/platform-smtp"
ENV = {
    "SMTP_HOST": "env.test",
    "SMTP_PORT": "587",
    "SMTP_USER": "env-user",
    "SMTP_PASSWORD": "env-pass",
    "SMTP_AUTH_STRATEGY": "TLS",
    "SMTP_FROM_NAME": "Env Marvin",
    "SMTP_FROM_EMAIL": "env@env.test",
}


@fixture(autouse=True)
def world(db_session, monkeypatch, admin_user):
    settings = get_app_settings()
    for key in ENV:
        monkeypatch.setattr(settings, key, ENV[key])
    platform_smtp.reset(db_session)
    db_session.query(EventLogModel).filter(EventLogModel.integration_id == "platform_settings").delete(synchronize_session=False)
    db_session.commit()
    yield
    app.dependency_overrides.pop(get_current_user, None)
    db_session.rollback()
    platform_smtp.reset(db_session)
    db_session.query(EventLogModel).filter(EventLogModel.integration_id == "platform_settings").delete(synchronize_session=False)
    db_session.commit()


@fixture(scope="module")
def admin_user():
    """A real user row: the audit event points at it."""
    from marvin.db.db_setup import session_context
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users

    gid, uid = uuid.uuid4(), uuid.uuid4()
    with session_context() as session:
        group = Groups(session=session, name=f"smtp-{gid.hex[:8]}", slug=f"smtp-{gid.hex[:8]}")
        group.id = gid
        session.add(group)
        session.flush()
        session.execute(
            Users.__table__.insert().values(
                id=uid, group_id=gid, username=f"ada-{gid.hex[:8]}", email=f"ada-{gid.hex[:8]}@example.test", full_name="Ada Person",
                password="x", is_superuser=False, platform_role="SUPER_ADMIN", auth_method="MARVIN",
            )
        )  # fmt: skip
        session.commit()
    _USER["id"] = uid
    yield uid
    with session_context() as session:
        session.query(EventLogModel).filter(EventLogModel.user_id == uid).delete(synchronize_session=False)
        session.query(Users).filter(Users.id == uid).delete()
        session.query(Groups).filter(Groups.id == gid).delete()
        session.commit()


_USER: dict = {}


def _admin(role=PlatformRole.SUPER_ADMIN, email="ada@example.test") -> TestClient:
    user = SimpleNamespace(
        id=_USER["id"],
        group_id=None,
        active_group_id=None,
        platform_role=role,
        is_superuser=False,
        admin=True,
        full_name="Ada Person",
        username="ada",
        email=email,
    )
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _audit(db_session) -> list[EventLogModel]:
    db_session.expire_all()
    return (
        db_session.query(EventLogModel)
        .filter(EventLogModel.event_type == "platform_settings_changed", EventLogModel.integration_id == "platform_settings")
        .order_by(EventLogModel.created_at)
        .all()
    )


def test_only_super_admins_can_read_or_write(db_session):
    client = _admin(PlatformRole.NONE)
    assert client.get(API).status_code == 403
    assert client.put(API, json={}).status_code == 403
    assert client.delete(API).status_code == 403
    assert client.post(f"{API}/test").status_code == 403


def test_get_shows_the_environment_per_field(db_session):
    body = _admin().get(API).json()

    assert body["ready"] and body["source"] == "env" and body["problem"] is None
    assert body["host"] == {"value": "env.test", "envValue": "env.test", "source": "env"}
    assert body["port"]["value"] == "587" and body["authStrategy"]["value"] == "TLS" and body["fromEmail"]["source"] == "env"
    assert body["passwordSet"] and body["passwordSource"] == "env" and not body["passwordMissing"] and body["canStorePassword"]
    assert body["envAvailable"] and body["envSummary"] == "env.test:587 · TLS · Env Marvin <env@env.test>"
    assert "env-pass" not in str(body)


def test_put_overrides_per_field_and_never_returns_the_password(db_session):
    client = _admin()
    res = client.put(API, json={"host": "mail.admin.test", "fromEmail": "ops@admin.test", "password": "s3cret-pw"})
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["source"] == "admin" and body["ready"]
    assert body["host"] == {"value": "mail.admin.test", "envValue": "env.test", "source": "admin"}
    assert body["fromEmail"]["source"] == "admin" and body["fromEmail"]["envValue"] == "env@env.test"
    assert body["port"]["source"] == "env" and body["username"]["source"] == "env" and body["fromName"]["source"] == "env"
    assert body["passwordSet"] and body["passwordSource"] == "admin"
    assert "s3cret-pw" not in res.text and "s3cret-pw" not in client.get(API).text

    assert get_platform_secret("PLATFORM_SMTP_PASSWORD") == "s3cret-pw"
    row = db_session.query(WorkspaceSecret).filter(WorkspaceSecret.slug == "PLATFORM_SMTP_PASSWORD").one()
    assert row.group_id is None and "s3cret-pw" not in row.encrypted_value
    assert platform_smtp.stored_block(db_session) == {
        "host": "mail.admin.test",
        "from_email": "ops@admin.test",
        "password_ref": "PLATFORM_SMTP_PASSWORD",
    }


def test_put_replaces_the_admin_fields_blank_ones_go_back_and_a_blank_password_is_kept(db_session):
    client = _admin()
    client.put(API, json={"host": "mail.admin.test", "port": 2525, "password": "pw-one"})

    body = client.put(API, json={"host": "mail.admin.test", "fromName": "Ops"}).json()  # port left out: back to env; password left alone
    assert body["port"]["source"] == "env" and body["fromName"] == {"value": "Ops", "envValue": "Env Marvin", "source": "admin"}
    assert body["passwordSource"] == "admin" and get_platform_secret("PLATFORM_SMTP_PASSWORD") == "pw-one"

    body = client.put(API, json={"host": "mail.admin.test", "password": ""}).json()
    assert body["passwordSource"] == "admin"

    body = client.put(API, json={"host": "mail.admin.test", "clearPassword": True}).json()
    assert body["passwordSource"] == "env" and get_platform_secret("PLATFORM_SMTP_PASSWORD") is None


def test_a_value_equal_to_the_environments_is_not_pinned(db_session):
    body = _admin().put(API, json={"host": "env.test", "port": 587, "authStrategy": "tls", "fromName": "Env Marvin"}).json()

    assert body["source"] == "env" and platform_smtp.stored_block(db_session) == {}
    assert _audit(db_session) == []  # nothing changed, nothing audited


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"port": 0}, "between 1 and 65535"),
        ({"port": 70000}, "between 1 and 65535"),
        ({"authStrategy": "STARTTLS"}, "TLS, SSL or None"),
        ({"fromEmail": "not-an-email"}, "email address"),
        ({"host": "http://x/y"}, "server name"),
    ],
)
def test_bad_values_are_refused_and_nothing_is_saved(db_session, payload, detail):
    res = _admin().put(API, json=payload)
    assert res.status_code == 422 and detail in res.json()["detail"]
    assert platform_smtp.stored_block(db_session) == {}


def test_changes_are_audited_without_the_password(db_session):
    client = _admin()
    client.put(API, json={"host": "mail.admin.test", "password": "very-secret-pw"})
    client.put(API, json={"host": "mail.admin.test", "port": 2525})  # password kept
    client.delete(API)

    first, second, third = _audit(db_session)
    assert first.workspace_id is None and second.workspace_id is None
    assert first.event_data["documentData"]["setting"] == "smtp"
    assert first.event_data["documentData"]["changes"] == ["host set to mail.admin.test", "password changed"]
    assert second.event_data["documentData"]["changes"] == ["port set to 2525"]
    assert third.event_data["documentData"]["changes"] == ["host back to the environment's", "port back to the environment's", "password cleared"]
    assert "very-secret-pw" not in str([r.event_data for r in (first, second, third)])


def test_use_environment_settings_clears_everything(db_session):
    client = _admin()
    client.put(API, json={"host": "mail.admin.test", "fromEmail": "ops@admin.test", "password": "pw"})
    body = client.delete(API).json()

    assert body["source"] == "env" and {body[f]["source"] for f in ("host", "port", "fromEmail")} == {"env"}
    assert body["passwordSource"] == "env"
    assert platform_smtp.stored_block(db_session) == {} and get_platform_secret("PLATFORM_SMTP_PASSWORD") is None


def test_the_env_secret_backend_cannot_store_a_password(db_session, monkeypatch):
    from marvin.services.secrets import platform
    from marvin.services.secrets.backends.env import EnvSecretBackend

    monkeypatch.setattr(platform, "get_secret_backend", lambda: EnvSecretBackend())
    monkeypatch.setattr(get_app_settings(), "SECRET_BACKEND", "env")
    client = _admin()
    assert client.get(API).json()["canStorePassword"] is False

    res = client.put(API, json={"host": "mail.admin.test", "password": "pw"})
    assert res.status_code == 422 and "PLATFORM_SMTP_PASSWORD" in res.json()["detail"]
    assert platform_smtp.stored_block(db_session) == {}


def test_a_saved_password_the_store_cannot_produce_is_reported_missing(db_session):
    from marvin.services.secrets.platform import delete_platform_secret

    client = _admin()
    client.put(API, json={"host": "mail.admin.test", "password": "pw"})
    delete_platform_secret("PLATFORM_SMTP_PASSWORD")
    db_session.commit()
    platform_smtp.clear_cache()

    body = client.get(API).json()
    assert body["passwordMissing"] is True and body["passwordSource"] == "env"  # the environment's applies meanwhile


class _Wire:
    def __init__(self, monkeypatch):
        self.calls = []
        self.response = email_senders.SMTPResponse(success=True, message="ok", errors={})

        def send(message, to_address, smtp_config):
            self.calls.append((to_address, smtp_config.host, message.subject, message.mail_from_address))
            return self.response

        monkeypatch.setattr(email_senders.Message, "send", send)


def test_send_test_goes_to_the_caller_through_the_saved_settings(db_session, monkeypatch):
    wire = _Wire(monkeypatch)
    client = _admin(email="ada@example.test")
    client.put(API, json={"host": "mail.admin.test"})

    res = client.post(f"{API}/test")
    assert res.json() == {"success": True, "error": None}
    assert wire.calls == [("ada@example.test", "mail.admin.test", "Test email from Marvin", "env@env.test")]


def test_send_test_says_what_the_server_answered_or_what_is_missing(db_session, monkeypatch):
    wire = _Wire(monkeypatch)
    wire.response = email_senders.SMTPResponse(success=False, message="SMTP error: (535) bad login", errors={"x": 1})
    res = _admin().post(f"{API}/test").json()
    assert res == {"success": False, "error": "SMTP error: (535) bad login"}

    assert _admin(email=None).post(f"{API}/test").status_code == 422

    monkeypatch.setattr(get_app_settings(), "SMTP_HOST", None)
    res = _admin().post(f"{API}/test").json()
    assert res["success"] is False and "SMTP_HOST" in res["error"]
