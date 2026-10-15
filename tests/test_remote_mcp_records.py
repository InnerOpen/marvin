"""Remote MCP, slice 1: the OAuth tables (db/models/platform/oauth.py) and the daily purge of what is spent."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from marvin.db.models.platform.oauth import OAuthAuthorizationRequestModel, OAuthClientModel, OAuthGrantModel, OAuthTokenModel
from tests import test_content_role_gates as gates

workspace = gates.workspace  # fixture: a workspace with a user

NOW = datetime.now(UTC).replace(tzinfo=None)


def _client(db_session, *, used: datetime | None = None, name: str = "Claude") -> OAuthClientModel:
    row = OAuthClientModel(
        session=db_session,
        client_id=f"marvin_oc_{uuid.uuid4().hex[:22]}",
        token_endpoint_auth_method="client_secret_basic",
        redirect_uris=["https://claude.ai/api/mcp/auth_callback"],
        grant_types=["authorization_code", "refresh_token"],
        client_name=name,
    )
    db_session.add(row)
    db_session.flush()
    row.created_at = used or NOW
    row.last_used_at = used
    return row


def _grant(db_session, ws, client, *, used: datetime | None = None, revoked: datetime | None = None) -> OAuthGrantModel:
    row = OAuthGrantModel(
        session=db_session,
        user_id=ws.uid,
        group_id=ws.gid,
        client_fk=client.id,
        scope="marvin:read",
        resource="https://api.example.com/mcp",
        client_name_snapshot=client.client_name,
        redirect_host="claude.ai",
    )
    db_session.add(row)
    db_session.flush()
    row.created_at = used or NOW
    row.last_used_at = used
    row.revoked_at = revoked
    return row


def _token(db_session, grant, *, expires: datetime, kind: str = "refresh") -> OAuthTokenModel:
    row = OAuthTokenModel(session=db_session, grant_id=grant.id, kind=kind, token_lookup=uuid.uuid4().hex + uuid.uuid4().hex, expires_at=expires)
    db_session.add(row)
    return row


def _request(db_session, client, *, expires: datetime, code_expires: datetime | None = None) -> OAuthAuthorizationRequestModel:
    row = OAuthAuthorizationRequestModel(
        session=db_session,
        ref_lookup=uuid.uuid4().hex + uuid.uuid4().hex,
        client_fk=client.id,
        redirect_uri="https://claude.ai/api/mcp/auth_callback",
        code_challenge="x" * 43,
        requested_scope="marvin:read",
        resource="https://api.example.com/mcp",
        consent_nonce_hash="n" * 64,
        expires_at=expires,
        code_expires_at=code_expires,
    )
    db_session.add(row)
    return row


@pytest.fixture
def clean(db_session):
    yield
    db_session.rollback()
    for model in (OAuthTokenModel, OAuthAuthorizationRequestModel, OAuthGrantModel, OAuthClientModel):
        db_session.query(model).delete()
    db_session.commit()


def test_every_column_holds_its_longest_value(db_session, workspace, clean):
    """Postgres enforces String(N): a value at each declared length must store."""
    client = _client(db_session)
    client.client_name = "c" * 200
    client.client_uri = client.logo_uri = "u" * 500
    client.software_id = client.software_version = "s" * 100
    client.registered_ip = "i" * 64
    client.client_secret_hash = "h" * 64
    grant = _grant(db_session, workspace, client)
    grant.scope = "s" * 200
    grant.resource = "r" * 500
    grant.redirect_host = grant.client_name_snapshot = "h" * 200
    grant.last_user_agent = "a" * 300
    grant.revoked_reason = "membership_lost"
    req = _request(db_session, client, expires=NOW)
    req.redirect_uri = req.state = "r" * 1000
    req.code_challenge = "c" * 128
    req.status = "approved"
    req.code_lookup = "k" * 64
    req.grant_id = grant.id
    _token(db_session, grant, expires=NOW, kind="refresh")
    db_session.commit()
    assert db_session.get(OAuthAuthorizationRequestModel, req.id).status == "approved"


def test_lookups_are_unique(db_session, workspace, clean):
    from sqlalchemy.exc import IntegrityError

    grant = _grant(db_session, workspace, _client(db_session))
    a = _token(db_session, grant, expires=NOW)
    db_session.flush()
    _token(db_session, grant, expires=NOW).token_lookup = a.token_lookup
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_deleting_a_grant_takes_its_tokens_and_leaves_its_request(db_session, workspace, clean):
    client = _client(db_session)
    grant = _grant(db_session, workspace, client)
    _token(db_session, grant, expires=NOW + timedelta(days=1))
    req = _request(db_session, client, expires=NOW + timedelta(minutes=30))
    req.grant_id = grant.id
    db_session.commit()
    db_session.query(OAuthGrantModel).filter_by(id=grant.id).delete()
    db_session.commit()
    db_session.expire_all()
    assert db_session.query(OAuthTokenModel).count() == 0
    assert db_session.get(OAuthAuthorizationRequestModel, req.id).grant_id is None


def test_the_purge_deletes_only_what_can_never_be_used_again(db_session, workspace, clean):
    from marvin.services.scheduled_tasks.handlers.oauth import purge_oauth_records

    old, recent = NOW - timedelta(days=120), NOW - timedelta(days=2)
    live_client = _client(db_session, used=recent, name="live")
    live = _grant(db_session, workspace, live_client, used=old)  # old, but a refresh token still works
    _token(db_session, live, expires=NOW + timedelta(days=5))
    expired_token = _token(db_session, live, expires=NOW - timedelta(minutes=1), kind="access")
    revoked = _grant(db_session, workspace, live_client, revoked=old)
    revoked_recently = _grant(db_session, workspace, live_client, revoked=recent)
    dead = _grant(db_session, workspace, live_client, used=old)  # no token left
    unused_client = _client(db_session, used=NOW - timedelta(days=8), name="gone")
    new_client = _client(db_session, used=NOW - timedelta(days=1), name="new")
    spent = _request(db_session, live_client, expires=NOW - timedelta(minutes=1))
    pending = _request(db_session, live_client, expires=NOW + timedelta(minutes=10))
    db_session.commit()
    rows = {
        "live": live,
        "expired_token": expired_token,
        "revoked": revoked,
        "revoked_recently": revoked_recently,
        "dead": dead,
        "unused_client": unused_client,
        "new_client": new_client,
        "spent": spent,
        "pending": pending,
    }
    ids = {name: (type(row), row.id) for name, row in rows.items()}

    counts = purge_oauth_records(datetime.now(UTC))

    assert counts == {"expired token(s)": 1, "expired sign-in request(s)": 1, "connection(s)": 2, "unused client(s)": 1}
    db_session.expire_all()
    gone = {name for name, (model, id_) in ids.items() if db_session.get(model, id_) is None}
    assert gone == {"expired_token", "revoked", "dead", "unused_client", "spent"}


def test_the_purge_is_a_daily_system_task():
    from marvin.services.database_report import TABLES
    from marvin.services.scheduled_tasks.handlers import TaskHandlerRegistry
    from marvin.services.scheduled_tasks.system_tasks import SYSTEM_SCHEDULED_TASKS

    task = next(d for d in SYSTEM_SCHEDULED_TASKS if d.slug == "purge_oauth_records")
    assert TaskHandlerRegistry.is_registered(task.task_type)
    assert task.schedule_config == {"interval_seconds": 24 * 60 * 60}
    for table in ("oauth_clients", "oauth_authorization_requests", "oauth_grants", "oauth_tokens"):
        assert TABLES[table][1].task == "purge_oauth_records"
