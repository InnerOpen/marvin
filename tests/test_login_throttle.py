"""Sign-in throttling (services/security/login_throttle.py, POST /api/auth/token) and the password-reset cap.

Repeated failures are refused for a while per account and per client IP — 429 with Retry-After, the same answer
whether or not the account exists — and the refusal grows (15 minutes, then an hour) while the guessing goes on.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from marvin.core import security
from marvin.db.models.platform import AuthThrottleModel
from marvin.services.security import login_throttle as lt

PASSWORD = "correct horse battery staple"


@pytest.fixture
def user(db_session):
    """A MARVIN-auth user with a known password; it, its workspace and every throttle row are cleaned up after."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.users import Users

    gid, uid = uuid.uuid4(), uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"Throttle {marker}", slug=f"throttle-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    db_session.execute(
        sa.insert(Users.__table__).values(
            id=uid,
            group_id=gid,
            full_name="Throttle Test",
            username=f"throttle-{marker}",
            email=f"throttle-{marker}@x.test",
            password=security.hash_password(PASSWORD),
            auth_method="MARVIN",
            is_superuser=False,
            platform_role="NONE",
            admin=False,
        )
    )
    db_session.commit()
    yield {"id": uid, "username": f"throttle-{marker}", "email": f"throttle-{marker}@x.test"}
    db_session.rollback()
    db_session.query(AuthThrottleModel).delete()
    db_session.query(Users).filter_by(id=uid).delete()
    db_session.query(Groups).filter_by(id=gid).delete()
    db_session.commit()


@pytest.fixture
def ip():
    """A client IP of this test's own, as Cloudflare would pass it."""
    return f"203.0.113.{uuid.uuid4().int % 250 + 1}-{uuid.uuid4().hex[:6]}"


@pytest.fixture
def events(monkeypatch):
    sent = []
    from marvin.services.event_bus_service.event_bus_service import EventBusService

    monkeypatch.setattr(EventBusService, "dispatch", lambda self, **kw: sent.append(kw))
    return sent


def _sign_in(client, username, password, ip):
    return client.post("/api/auth/token", data={"username": username, "password": password}, headers={"CF-Connecting-IP": ip})


def _fail(client, username, ip, times):
    return [_sign_in(client, username, "wrong", ip).status_code for _ in range(times)]


def test_five_failures_refuse_the_account_even_with_the_right_password(client, user, ip, events):
    assert _fail(client, user["username"], ip, 5) == [401] * 5
    refused = _sign_in(client, user["username"], PASSWORD, ip)
    assert refused.status_code == 429
    assert "Too many sign-in attempts. Try again in 15 minutes." == refused.json()["detail"]
    assert 14 * 60 < int(refused.headers["Retry-After"]) <= 15 * 60


def test_an_account_that_does_not_exist_gets_the_same_answers(client, user, ip, events):
    ghost = f"nobody-{uuid.uuid4().hex[:8]}"
    assert _fail(client, ghost, ip, 5) == [401] * 5
    assert _sign_in(client, ghost, "wrong", ip).status_code == 429


def test_a_username_and_its_email_share_one_count(client, user, ip, events):
    assert _fail(client, user["username"], ip, 3) + _fail(client, user["email"], ip, 2) == [401] * 5
    assert _sign_in(client, user["email"], PASSWORD, ip).status_code == 429


def test_a_successful_sign_in_clears_the_count(client, user, ip, events):
    _fail(client, user["username"], ip, 4)
    assert _sign_in(client, user["username"], PASSWORD, ip).status_code == 200
    assert _fail(client, user["username"], ip, 4) == [401] * 4  # a fresh count: not refused at the 5th overall


def test_the_refusal_ends_by_itself_and_grows_if_the_guessing_goes_on(client, user, ip, events, db_session):
    _fail(client, user["username"], ip, 5)
    row = db_session.query(AuthThrottleModel).filter_by(scope=lt.ACCOUNT, key=lt.account_key(user["username"], user["id"])).one()
    for _ in range(5):  # each time the refusal ends, one more guess re-locks it; the 10th failure locks for an hour
        db_session.query(AuthThrottleModel).filter_by(id=row.id).update({"locked_until": datetime.now(UTC) - timedelta(seconds=1)})
        db_session.commit()
        assert _sign_in(client, user["username"], "wrong", ip).status_code == 401
    refused = _sign_in(client, user["username"], PASSWORD, ip)
    assert refused.status_code == 429 and 59 * 60 < int(refused.headers["Retry-After"]) <= 60 * 60


def test_one_ip_failing_across_many_names_is_refused_but_another_ip_is_not(client, user, ip, events):
    for _ in range(20):
        assert _sign_in(client, f"spray-{uuid.uuid4().hex[:8]}", "wrong", ip).status_code == 401
    assert _sign_in(client, user["username"], PASSWORD, ip).status_code == 429
    assert _sign_in(client, user["username"], PASSWORD, f"{ip}-elsewhere").status_code == 200


def test_the_refusal_is_announced_once_when_it_starts(client, user, ip, events):
    _fail(client, user["username"], ip, 5)
    _sign_in(client, user["username"], "wrong", ip)  # refused: not a failure, not announced again
    announced = [e for e in events if e["event_type"].name == "login_failed_multiple_times"]
    assert len(announced) == 1
    assert announced[0]["group_id"] is None and announced[0]["document_data"].attempt_count == 5
    assert announced[0]["document_data"].username == user["username"] and announced[0]["document_data"].ip_address == ip


def test_cloudflare_s_client_ip_wins_over_a_forwarded_one():
    class FakeRequest:
        def __init__(self, headers):
            self.headers = headers
            self.client = None

    assert lt.login_client_ip(FakeRequest({"cf-connecting-ip": "198.51.100.9", "x-forwarded-for": "1.2.3.4"})) == "198.51.100.9"
    assert lt.login_client_ip(FakeRequest({"x-forwarded-for": "1.2.3.4, 10.0.0.1"})) == "1.2.3.4"


def test_password_reset_emails_are_capped_per_address_without_saying_so(client, user, ip, monkeypatch):
    sent = []
    from marvin.services.user.password_reset_service import PasswordResetService

    monkeypatch.setattr(PasswordResetService, "send_reset_email", lambda self, email, lang=None: sent.append(email))
    answers = [
        client.post("/api/users/forgot-password", json={"email": user["email"]}, headers={"CF-Connecting-IP": ip}).status_code for _ in range(5)
    ]
    assert answers == [202] * 5  # the same answer every time
    assert sent == [user["email"]] * 3  # but only SECURITY_PASSWORD_RESET_MAX_PER_HOUR emails


def test_an_admin_force_unlock_releases_refused_accounts(client, user, ip, events, db_session):
    _fail(client, user["username"], ip, 5)
    assert lt.LoginThrottle(db_session).release_accounts() == 1
    assert _sign_in(client, user["username"], PASSWORD, ip).status_code == 200
