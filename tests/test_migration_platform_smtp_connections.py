"""The 3442416ae2bd data migration: the platform workspace's active SMTP profile and alert integrations become
platform settings, so retiring that workspace changes nothing about how mail and alerts go out.

Run on PostgreSQL (the test database) and on a scratch SQLite, inside a transaction that is rolled back: seed an
`is_platform` workspace with a profile, its password secret, two integrations and the alert routes that use them; run
the migration's own `upgrade()`/`downgrade()` through an Alembic Operations context; check what was copied, that the
merged platform SMTP is exactly what the profile used to be, and that the workspace's rows are untouched.
"""

import importlib.util
import logging
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from marvin.core.config import get_app_settings
from marvin.db.models import SqlAlchemyBase
from marvin.db.models.groups import Groups
from marvin.db.models.groups.integrations import IntegrationModel
from marvin.db.models.groups.secrets import WorkspaceSecret
from marvin.db.models.groups.smtp_profiles import WorkspaceSMTPProfileModel
from marvin.db.models.platform.platform_settings import PlatformSettingsModel
from marvin.services import platform_smtp

_PATH = next((Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions").glob("*_3442416ae2bd_*.py"))
_spec = importlib.util.spec_from_file_location("platform_smtp_and_alert_connections", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)

ENV_KEYS = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_AUTH_STRATEGY", "SMTP_FROM_NAME", "SMTP_FROM_EMAIL")
COMPLETE_ENV = {
    "SMTP_HOST": "env.test",
    "SMTP_PORT": "587",
    "SMTP_USER": "env-user",
    "SMTP_PASSWORD": "env-pass",
    "SMTP_AUTH_STRATEGY": "TLS",
    "SMTP_FROM_NAME": "Env Marvin",
    "SMTP_FROM_EMAIL": "env@env.test",
}


@pytest.fixture(scope="module")
def sqlite_engine():
    engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SqlAlchemyBase.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(params=["postgres", "sqlite"])
def conn(request):
    """A connection in a transaction that is always rolled back."""
    if request.param == "postgres":
        from marvin.db.db_setup import engine
    else:
        engine = request.getfixturevalue("sqlite_engine")
    connection = engine.connect()
    outer = connection.begin()
    yield connection
    outer.rollback()
    connection.close()


@pytest.fixture
def env(monkeypatch):
    def set_env(**values):
        """Unset except what's given, over the real defaults (port 587, TLS, From name Marvin)."""
        values = {"SMTP_PORT": "587", "SMTP_AUTH_STRATEGY": "TLS", "SMTP_FROM_NAME": "Marvin", **values}
        settings = get_app_settings()
        for key in ENV_KEYS:
            monkeypatch.setattr(settings, key, values.get(key))

    return set_env


def _run(conn, fn):
    with Operations.context(MigrationContext.configure(conn)):
        fn()


def _setting(session, key):
    session.expire_all()
    row = session.query(PlatformSettingsModel).filter(PlatformSettingsModel.key == key).first()
    return row.value_json if row else None


def _platform_secrets(session):
    session.expire_all()
    return {s.slug: s.encrypted_value for s in session.query(WorkspaceSecret).filter(WorkspaceSecret.group_id.is_(None)).all()}


class World:
    """An is_platform workspace with an active SMTP profile and two alert integrations, routed."""

    def __init__(self, conn):
        self.conn = conn
        self.session = Session(bind=conn)
        s = self.session
        # Whatever the database already holds of ours must not leak into the check.
        s.query(WorkspaceSecret).filter(WorkspaceSecret.group_id.is_(None)).delete()
        s.query(PlatformSettingsModel).filter(PlatformSettingsModel.key.in_(["smtp", "platform_connections", "platform_alerts"])).delete()
        s.execute(sa.update(Groups.__table__).values(is_platform=False))
        marker = uuid.uuid4().hex[:8]
        self.group = Groups(session=s, name=f"Admin {marker}", slug=f"admin-{marker}", is_platform=True)
        s.add(self.group)
        s.flush()
        self.gid = self.group.id

    def profile(self, **fields):
        values = {
            "name": "Primary",
            "host": "smtp.profile.test",
            "port": 2525,
            "username": "profile-user",
            "from_name": "Profile Marvin",
            "from_email": "hi@profile.test",
            "auth_strategy": "TLS",
            "is_active": True,
            "secret_ref": "SMTP_ABCDEF",
        }
        values.update(fields)
        profile = WorkspaceSMTPProfileModel(session=self.session, group_id=self.gid, **values)
        self.session.add(profile)
        self.session.flush()
        return profile

    def workspace_secret(self, slug, plain):
        from marvin.services.secrets.backends.database import _get_fernet

        cipher = _get_fernet().encrypt(plain.encode()).decode()
        self.session.add(WorkspaceSecret(session=self.session, group_id=self.gid, name=slug, slug=slug, encrypted_value=cipher))
        self.session.flush()
        return cipher

    def integration(self, provider, name, secret_ref=None, enabled=True, config=None):
        row = IntegrationModel(
            session=self.session, group_id=self.gid, provider=provider, name=name, slug=name.lower(), enabled=enabled, config=config or {},
            secret_ref=secret_ref, status="ok",
        )  # fmt: skip
        self.session.add(row)
        self.session.flush()
        return row

    def routes(self, *routes):
        self.session.add(PlatformSettingsModel(session=self.session, key="platform_alerts", value_json={"routes": list(routes)}))
        self.session.flush()


@pytest.fixture
def world(conn):
    w = World(conn)
    yield w
    w.session.close()


def _seed_everything(w: World):
    password = w.workspace_secret("SMTP_ABCDEF", "profile-password")
    w.profile()
    w.workspace_secret("INTEGRATION_PHONE", "slack://token/a/b")
    w.workspace_secret("OPS_CHANNEL", "#ops")
    phone = w.integration("apprise", "Phone", secret_ref="INTEGRATION_PHONE")
    chat = w.integration("slack", "Ops chat", secret_ref=None, enabled=False, config={"workspace": "acme"})
    w.integration("slack", "Unused", secret_ref=None)  # no route points at it: not copied
    w.routes(
        {"id": "r1", "integration_id": str(phone.id), "action": "notify", "args": {}, "enabled": True},
        {"id": "r2", "integration_id": str(chat.id), "action": "send_message", "args": {"channel": "{{OPS_CHANNEL}}"}, "enabled": True},
    )
    return password, phone, chat


def test_the_profile_becomes_the_admin_block_and_alert_integrations_become_platform_connections(conn, world, env):
    env(SMTP_HOST="env.test")  # incomplete: no from address, no login
    password, phone, chat = _seed_everything(world)

    _run(conn, mig.upgrade)
    s = world.session

    assert _setting(s, "smtp") == {
        "host": "smtp.profile.test",
        "port": 2525,
        "username": "profile-user",
        "from_name": "Profile Marvin",
        "from_email": "hi@profile.test",
        "password_ref": "PLATFORM_SMTP_PASSWORD",
    }  # auth_strategy TLS equals the environment's default (and port 2525 differs from 587): left to the merge
    secrets = _platform_secrets(s)
    assert secrets["PLATFORM_SMTP_PASSWORD"] == password  # ciphertext verbatim
    assert _setting(s, "platform_connections") == {
        "connections": [
            {"id": str(phone.id), "provider": "apprise", "name": "Phone", "config": {}, "secret_ref": "INTEGRATION_PHONE", "enabled": True},
            {"id": str(chat.id), "provider": "slack", "name": "Ops chat", "config": {"workspace": "acme"}, "secret_ref": None, "enabled": False},
        ]
    }
    assert set(secrets) == {"PLATFORM_SMTP_PASSWORD", "INTEGRATION_PHONE", "OPS_CHANNEL"}  # the credential and the route-argument secret
    # the routes (and their statuses) keep working untouched: same ids
    assert [r["integration_id"] for r in _setting(s, "platform_alerts")["routes"]] == [str(phone.id), str(chat.id)]


def test_behaviour_is_unchanged_the_merge_is_exactly_the_profile_the_platform_workspace_used(conn, world, env):
    """Before: an incomplete environment sent platform mail through the platform workspace's profile alone. After:
    the merged platform SMTP must name the same server, login, security and From."""
    env(SMTP_HOST="env.test")
    _seed_everything(world)
    profile = world.session.query(WorkspaceSMTPProfileModel).one()
    _run(conn, mig.upgrade)

    from marvin.services.secrets.backends.database import _get_fernet

    block = _setting(world.session, "smtp")
    password = _get_fernet().decrypt(_platform_secrets(world.session)["PLATFORM_SMTP_PASSWORD"].encode()).decode()
    merged = platform_smtp.merge(block, password)
    assert (merged.host, merged.port, merged.username, merged.password, merged.auth_strategy, merged.from_name, merged.from_email) == (
        profile.host,
        profile.port,
        profile.username,
        "profile-password",
        profile.auth_strategy,
        profile.from_name,
        profile.from_email,
    )
    assert merged.ready


def test_fields_equal_to_the_environment_are_not_pinned_but_the_merge_is_the_same(conn, world, env):
    env(SMTP_HOST="smtp.profile.test", SMTP_PORT="2525", SMTP_FROM_NAME="Profile Marvin", SMTP_AUTH_STRATEGY="tls")  # incomplete: no from/login
    world.workspace_secret("SMTP_ABCDEF", "pw")
    world.profile()
    _run(conn, mig.upgrade)

    block = _setting(world.session, "smtp")
    assert set(block) == {"username", "from_email", "password_ref"}
    merged = platform_smtp.merge(block, "pw")
    assert (merged.host, merged.port, merged.auth_strategy, merged.from_name) == ("smtp.profile.test", 2525, "TLS", "Profile Marvin")


def test_with_a_complete_environment_the_profile_is_not_copied_because_the_environment_won_before(conn, world, env):
    env(**COMPLETE_ENV)
    _seed_everything(world)
    _run(conn, mig.upgrade)

    assert _setting(world.session, "smtp") is None
    assert "PLATFORM_SMTP_PASSWORD" not in _platform_secrets(world.session)
    assert platform_smtp.merge({}, None).source == "env"
    assert len(_setting(world.session, "platform_connections")["connections"]) == 2  # alerts never depended on the environment


def test_a_profile_without_auth_copies_no_password(conn, world, env):
    env(SMTP_HOST="env.test")
    world.profile(secret_ref=None, username=None, auth_strategy="NONE", port=1025, from_name=None)
    _run(conn, mig.upgrade)

    block = _setting(world.session, "smtp")
    assert block == {"host": "smtp.profile.test", "port": 1025, "auth_strategy": "NONE", "from_email": "hi@profile.test"}
    assert platform_smtp.merge(block, None).ready


def test_another_secret_backend_logs_instead_of_copying(conn, world, env, monkeypatch, caplog):
    env(SMTP_HOST="env.test")
    monkeypatch.setattr(get_app_settings(), "SECRET_BACKEND", "disk")
    _seed_everything(world)
    with caplog.at_level(logging.WARNING):
        _run(conn, mig.upgrade)

    block = _setting(world.session, "smtp")
    assert "password_ref" not in block and block["host"] == "smtp.profile.test"
    assert _platform_secrets(world.session) == {}
    assert platform_smtp.merge(block, None).password_missing is False  # no ref, so "missing" is for Admin to word: password unset
    assert any("SECRET_BACKEND=disk" in r.getMessage() for r in caplog.records)
    assert len(_setting(world.session, "platform_connections")["connections"]) == 2  # the connections still copy; their credentials are re-entered


def test_nothing_to_copy_without_a_platform_workspace_or_routes(conn, world, env):
    env(SMTP_HOST="env.test")
    world.session.execute(sa.update(Groups.__table__).values(is_platform=False))
    world.profile()
    _run(conn, mig.upgrade)
    assert _setting(world.session, "smtp") is None and _setting(world.session, "platform_connections") is None

    world.session.execute(sa.update(Groups.__table__).where(Groups.__table__.c.id == world.gid).values(is_platform=True))
    _run(conn, mig.upgrade)  # a profile but no routes: SMTP only
    assert _setting(world.session, "smtp")["host"] == "smtp.profile.test" and _setting(world.session, "platform_connections") is None


def test_rerunning_changes_nothing_and_downgrade_removes_only_the_copies(conn, world, env):
    env(SMTP_HOST="env.test")
    _seed_everything(world)
    _run(conn, mig.upgrade)
    first = (_setting(world.session, "smtp"), _setting(world.session, "platform_connections"), _platform_secrets(world.session))
    _run(conn, mig.upgrade)
    assert (_setting(world.session, "smtp"), _setting(world.session, "platform_connections"), _platform_secrets(world.session)) == first

    _run(conn, mig.downgrade)
    s = world.session
    assert _setting(s, "smtp") is None and _setting(s, "platform_connections") is None and _platform_secrets(s) == {}
    # the platform workspace's own rows are exactly as they were: old code works again
    assert (
        s.query(WorkspaceSMTPProfileModel).filter(WorkspaceSMTPProfileModel.group_id == world.gid, WorkspaceSMTPProfileModel.is_active).count() == 1
    )
    assert s.query(IntegrationModel).filter(IntegrationModel.group_id == world.gid).count() == 3
    assert {x.slug for x in s.query(WorkspaceSecret).filter(WorkspaceSecret.group_id == world.gid)} == {
        "SMTP_ABCDEF",
        "INTEGRATION_PHONE",
        "OPS_CHANNEL",
    }
    assert len(_setting(s, "platform_alerts")["routes"]) == 2
