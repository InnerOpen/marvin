"""Platform mail without platform SMTP settings: the platform workspace's active SMTP profile sends it.

Password resets, platform alerts and the admin test email have no workspace of their own. They go through the
platform SMTP settings when those are complete, else through the platform workspace's active SMTP profile; a
workspace without a profile of its own falls back the same way.
"""

import uuid

from pytest import fixture

from marvin.core.config import get_app_settings
from marvin.db.models.groups import Groups
from marvin.db.models.groups.smtp_profiles import WorkspaceSMTPProfileModel
from marvin.services import platform_alerts, workspace_alerts
from marvin.services.email import email_senders
from marvin.services.email.email_senders import DefaultEmailSender, WorkspaceEmailSender, email_ready, platform_sender
from marvin.services.email.email_service import EmailService
from marvin.services.group.platform_workspace import PlatformWorkspaceMissing, platform_workspace


def _smtp_settings(monkeypatch, on: bool):
    monkeypatch.setattr(type(get_app_settings()), "SMTP_ENABLED", property(lambda self: on))


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
    db_session.query(WorkspaceSMTPProfileModel).filter(WorkspaceSMTPProfileModel.id.in_(ids)).delete()  # a deleted workspace took its own
    db_session.commit()


@fixture
def platform(db_session):
    """The marked platform workspace's id; one is made for the test when the database has none."""
    created = None
    try:
        gid = platform_workspace(db_session).id
    except PlatformWorkspaceMissing:
        name = f"platform-{uuid.uuid4().hex[:6]}"
        created = Groups(session=db_session, name=name, slug=name, is_platform=True)
        db_session.add(created)
        db_session.commit()
        gid = created.id
    yield gid
    if created is not None:
        db_session.delete(created)
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
    hosts = []

    def send(message, to_address, smtp_config):
        hosts.append((to_address, smtp_config.host, message.mail_from_address))
        return email_senders.SMTPResponse(success=True, message="ok", errors={})

    monkeypatch.setattr(email_senders.Message, "send", send)
    return hosts


def test_without_settings_or_a_platform_profile_nothing_is_ready(monkeypatch, db_session, platform, workspace):
    _smtp_settings(monkeypatch, False)

    assert type(platform_sender()) is DefaultEmailSender
    assert not email_ready()
    assert not email_ready(workspace)
    assert not platform_alerts.smtp_ready()


def test_the_platform_workspace_profile_sends_platform_mail(monkeypatch, db_session, platform, profiles, sent):
    _smtp_settings(monkeypatch, False)
    profiles(platform, "platform.test")
    profiles(platform, "inactive.test", active=False)

    sender = platform_sender()
    assert isinstance(sender, WorkspaceEmailSender) and sender.group_id == platform
    assert email_ready() and platform_alerts.smtp_ready()

    assert EmailService().sender.send("me@example.com", "Backup r2: failed", "<p>x</p>")
    assert sent == [("me@example.com", "platform.test", "alerts@platform.test")]


def test_a_workspace_without_a_profile_falls_back_to_the_platform_profile(monkeypatch, db_session, platform, profiles, workspace, sent):
    _smtp_settings(monkeypatch, False)
    profiles(platform, "platform.test")

    assert email_ready(workspace) and workspace_alerts.smtp_ready(db_session, workspace)
    assert EmailService(group_id=str(workspace)).sender.send("owner@example.com", "Hi", "<p>x</p>")
    assert sent == [("owner@example.com", "platform.test", "alerts@platform.test")]


def test_a_workspace_profile_wins_for_its_own_mail(monkeypatch, db_session, platform, profiles, workspace, sent):
    _smtp_settings(monkeypatch, False)
    profiles(platform, "platform.test")
    profiles(workspace, "own.test")

    assert EmailService(group_id=str(workspace)).sender.send("owner@example.com", "Hi", "<p>x</p>")
    assert sent == [("owner@example.com", "own.test", "alerts@own.test")]


def test_complete_smtp_settings_still_come_first(monkeypatch, db_session, platform, profiles):
    _smtp_settings(monkeypatch, True)
    profiles(platform, "platform.test")

    assert type(platform_sender()) is DefaultEmailSender
    assert email_ready()
