"""Platform mail: who sends it, and when it can go out.

Password resets, platform alerts and the admin test email have no workspace of their own. They go through the platform
SMTP server (services/platform_smtp): the environment's SMTP_* settings with whatever an admin overrode in Admin → Email,
merged field by field. A workspace without an active SMTP profile of its own falls back to the same sender. No workspace
is special: a profile in any workspace is only ever that workspace's.
"""

import uuid

from pytest import fixture

from marvin.core.config import get_app_settings
from marvin.db.models.groups import Groups
from marvin.db.models.groups.smtp_profiles import WorkspaceSMTPProfileModel
from marvin.services import platform_alerts, platform_smtp, workspace_alerts
from marvin.services.email import email_senders
from marvin.services.email.email_senders import DefaultEmailSender, WorkspaceEmailSender, email_ready, platform_sender
from marvin.services.email.email_service import EmailService

ENV_KEYS = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_AUTH_STRATEGY", "SMTP_FROM_NAME", "SMTP_FROM_EMAIL")


@fixture(autouse=True)
def clean_platform_smtp(db_session):
    platform_smtp.reset(db_session)
    yield
    db_session.rollback()
    platform_smtp.reset(db_session)


@fixture
def env(monkeypatch):
    """Set the environment's SMTP_* settings: whatever is not given is unset (the dev .env has a Mailpit)."""

    def set_env(**values):
        settings = get_app_settings()
        for key in ENV_KEYS:
            monkeypatch.setattr(settings, key, values.get(key))

    return set_env


COMPLETE_ENV = {
    "SMTP_HOST": "env.test",
    "SMTP_PORT": "587",
    "SMTP_USER": "env-user",
    "SMTP_PASSWORD": "env-pass",
    "SMTP_AUTH_STRATEGY": "TLS",
    "SMTP_FROM_NAME": "Env Marvin",
    "SMTP_FROM_EMAIL": "env@env.test",
}


def _profile(session, group_id, host, *, active=True):
    profile = WorkspaceSMTPProfileModel(
        session=session,
        group_id=group_id,
        name=f"p-{uuid.uuid4().hex[:6]}",
        host=host,
        port=1025,
        from_email=f"alerts@{host}",
        auth_strategy="NONE",
        is_active=active,
    )
    session.add(profile)
    session.commit()
    return profile


@fixture
def profiles(db_session):
    ids = []

    def make(group_id, host, **kw):
        profile = _profile(db_session, group_id, host, **kw)
        ids.append(profile.id)
        return profile

    yield make
    db_session.query(WorkspaceSMTPProfileModel).filter(WorkspaceSMTPProfileModel.id.in_(ids)).delete()
    db_session.commit()


@fixture
def workspace(db_session):
    gid = uuid.uuid4()
    group = Groups(session=db_session, name=f"mail-{gid.hex[:8]}", slug=f"mail-{gid.hex[:8]}")
    group.id = gid
    db_session.add(group)
    db_session.commit()
    yield gid
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


@fixture
def sent(monkeypatch):
    """Every SMTP send, as what reached the wire: host, port, login, security, From."""
    out = []

    def send(message, to_address, smtp_config):
        out.append(
            {
                "to": to_address,
                "host": smtp_config.host,
                "port": smtp_config.port,
                "user": smtp_config.username,
                "password": smtp_config.password,
                "tls": smtp_config.tls,
                "ssl": smtp_config.ssl,
                "from_email": message.mail_from_address,
                "from_name": message.mail_from_name,
            }
        )
        return email_senders.SMTPResponse(success=True, message="ok", errors={})

    monkeypatch.setattr(email_senders.Message, "send", send)
    return out


def _admin(db_session, **fields):
    platform_smtp.save(db_session, fields)


def test_without_settings_nothing_is_ready(env, db_session, workspace):
    env()

    assert type(platform_sender()) is DefaultEmailSender
    assert not email_ready()
    assert not email_ready(workspace)
    assert not platform_alerts.smtp_ready()
    assert platform_smtp.effective().source is None


def test_the_environment_alone_sends_platform_mail(env, db_session, sent):
    env(**COMPLETE_ENV)

    assert email_ready() and platform_alerts.smtp_ready() and platform_smtp.effective().source == "env"
    assert EmailService().sender.send("me@example.com", "Backup r2: failed", "<p>x</p>")
    assert sent == [
        {"to": "me@example.com", "host": "env.test", "port": 587, "user": "env-user", "password": "env-pass", "tls": True, "ssl": False,
             "from_email": "env@env.test", "from_name": "Env Marvin"}
    ]  # fmt: skip


def test_an_admin_alone_can_make_mail_ready(env, db_session, sent):
    env()
    _admin(db_session, host="admin.test", port=1025, auth_strategy="NONE", from_email="hi@admin.test", from_name="Admin Marvin")

    config = platform_smtp.effective()
    assert config.ready and config.source == "admin"
    assert EmailService().sender.send("me@example.com", "Hi", "<p>x</p>")
    assert sent[0]["host"] == "admin.test" and sent[0]["port"] == 1025 and not sent[0]["tls"] and sent[0]["user"] is None


def test_each_admin_field_wins_and_the_rest_fall_back_to_the_environment(env, db_session, sent):
    env(**COMPLETE_ENV)
    _admin(db_session, host="admin.test", from_email="ops@admin.test")  # nothing else

    config = platform_smtp.effective()
    assert config.sources == {
        "host": "admin", "port": "env", "username": "env", "auth_strategy": "env",
        "from_name": "env", "from_email": "admin", "password": "env",
    }  # fmt: skip
    assert config.source == "admin" and config.ready
    EmailService().sender.send("me@example.com", "Hi", "<p>x</p>")
    assert sent == [
        {"to": "me@example.com", "host": "admin.test", "port": 587, "user": "env-user", "password": "env-pass", "tls": True, "ssl": False,
             "from_email": "ops@admin.test", "from_name": "Env Marvin"}
    ]  # fmt: skip


def test_the_admin_password_beats_the_environments_only_when_set(env, db_session, sent):
    env(**COMPLETE_ENV)
    platform_smtp.save(db_session, {"host": "admin.test"}, password="admin-pass")
    EmailService().sender.send("a@example.com", "Hi", "<p>x</p>")
    assert (sent[-1]["host"], sent[-1]["password"]) == ("admin.test", "admin-pass")

    platform_smtp.save(db_session, {"host": "admin.test"}, clear_password=True)
    EmailService().sender.send("a@example.com", "Hi", "<p>x</p>")
    assert sent[-1]["password"] == "env-pass"


def test_a_partial_admin_block_over_an_incomplete_environment_says_what_is_missing(env, db_session):
    env(SMTP_PORT="587", SMTP_AUTH_STRATEGY="TLS")
    _admin(db_session, host="admin.test")

    config = platform_smtp.effective()
    assert not config.ready and config.source == "admin"
    assert "SMTP_FROM_EMAIL" in config.problem and not email_ready()


def test_use_environment_settings_clears_every_admin_field(env, db_session, sent):
    env(**COMPLETE_ENV)
    platform_smtp.save(db_session, {"host": "admin.test", "from_email": "ops@admin.test"}, password="admin-pass")
    platform_smtp.reset(db_session)

    config = platform_smtp.effective()
    assert config.source == "env" and set(config.sources.values()) == {"env"}
    EmailService().sender.send("a@example.com", "Hi", "<p>x</p>")
    assert (sent[-1]["host"], sent[-1]["from_email"], sent[-1]["password"]) == ("env.test", "env@env.test", "env-pass")


def test_a_workspace_without_a_profile_falls_back_to_the_platform_sender(env, db_session, workspace, sent):
    env(**COMPLETE_ENV)

    assert email_ready(workspace) and workspace_alerts.smtp_ready(db_session, workspace)
    assert isinstance(EmailService(group_id=str(workspace)).sender, WorkspaceEmailSender)
    assert EmailService(group_id=str(workspace)).sender.send("owner@example.com", "Hi", "<p>x</p>")
    assert sent[0]["host"] == "env.test"


def test_a_workspace_profile_wins_for_its_own_mail_and_is_ready_alone(env, db_session, workspace, profiles, sent):
    env()
    assert not email_ready(workspace)
    profiles(workspace, "own.test")

    assert email_ready(workspace) and not email_ready()  # its own, not the platform's
    assert EmailService(group_id=str(workspace)).sender.send("owner@example.com", "Hi", "<p>x</p>")
    assert sent == [
        {"to": "owner@example.com", "host": "own.test", "port": 1025, "user": None, "password": None, "tls": False, "ssl": False,
             "from_email": "alerts@own.test", "from_name": "Marvin"}
    ]  # fmt: skip


def test_a_profile_without_a_from_uses_the_platforms(env, db_session, workspace, profiles, sent):
    env(**COMPLETE_ENV)
    _admin(db_session, from_email="ops@admin.test")
    profile = profiles(workspace, "own.test")
    profile.from_email = None
    db_session.commit()

    EmailService(group_id=str(workspace)).sender.send("owner@example.com", "Hi", "<p>x</p>")
    assert (sent[0]["host"], sent[0]["from_email"], sent[0]["from_name"]) == ("own.test", "ops@admin.test", "Env Marvin")


def test_no_workspace_is_special(env, db_session, workspace, profiles, sent):
    """The old platform workspace's profile no longer sends platform mail — a profile is only its workspace's."""
    env()
    profiles(workspace, "platform.test")

    assert not email_ready() and not platform_alerts.smtp_ready()
    assert type(platform_sender()) is DefaultEmailSender
