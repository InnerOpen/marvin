"""API tokens and site-client tokens are found by a SHA-256 lookup, not by bcrypt-checking every stored token
(core/security/hasher.py: token_lookup, find_token) — a wrong token costs one query, not one bcrypt per token.
Tokens stored before the lookup existed are still found the old way, and get their lookup on first use."""

import uuid
from types import SimpleNamespace

import pytest

from marvin.core.security import hasher
from marvin.repos.platform.api_clients import APIClientsRepository
from marvin.repos.users.long_live_tokens import LongLiveTokensRepository


@pytest.fixture
def owner(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform.api_clients import APIClients
    from marvin.db.models.users.users import LongLiveToken, Users

    gid, uid = uuid.uuid4(), uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"tl-{marker}", slug=f"tl-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=gid,
            username=f"tl-{marker}",
            email=f"tl-{marker}@t.test",
            full_name="TL",
            password="x",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
        )
    )
    db_session.commit()
    yield SimpleNamespace(gid=gid, uid=uid)
    db_session.rollback()
    db_session.query(LongLiveToken).filter_by(user_id=uid).delete()
    db_session.query(APIClients).filter_by(group_id=gid).delete()
    db_session.query(Users).filter_by(id=uid).delete()
    db_session.query(Groups).filter_by(id=gid).delete()
    db_session.commit()


@pytest.fixture
def verifications(monkeypatch):
    """How many bcrypt checks a lookup makes."""
    real = hasher.get_hasher()
    count = SimpleNamespace(n=0)

    class Counting:
        def hash(self, value):
            return real.hash(value)

        def verify(self, value, hashed):
            count.n += 1
            return real.verify(value, hashed)

    monkeypatch.setattr(hasher, "get_hasher", lambda: Counting())
    return count


def _tokens(db_session):
    from marvin.db.models.users.users import LongLiveToken
    from marvin.schemas.user.user import LongLiveTokenRead

    return LongLiveTokensRepository(db_session, "id", LongLiveToken, LongLiveTokenRead)


def test_a_personal_token_is_found_by_its_lookup_with_one_check(db_session, owner, verifications):
    repo = _tokens(db_session)
    made = [repo.create({"name": f"t{i}", "user_id": owner.uid}) for i in range(4)]
    verifications.n = 0
    found = repo.validate_token(made[2].token)
    assert found is not None and found.name == "t2" and verifications.n == 1


def test_a_wrong_token_checks_nothing_once_every_token_has_a_lookup(db_session, owner, verifications):
    repo = _tokens(db_session)
    for i in range(4):
        repo.create({"name": f"t{i}", "user_id": owner.uid})
    verifications.n = 0
    assert repo.validate_token("marvin_tk_" + "x" * 43) is None
    assert verifications.n == 0


def test_an_older_token_without_a_lookup_is_still_found_and_gets_one(db_session, owner):
    from marvin.db.models.users.users import LongLiveToken

    repo = _tokens(db_session)
    made = repo.create({"name": "old", "user_id": owner.uid})
    db_session.query(LongLiveToken).filter_by(id=made.id).update({"token_lookup": None})
    db_session.commit()
    assert repo.validate_token(made.token) is not None
    row = db_session.query(LongLiveToken).filter_by(id=made.id).one()
    assert row.token_lookup == hasher.token_lookup(made.token)


def test_rotating_a_token_moves_its_lookup(db_session, owner):
    repo = _tokens(db_session)
    made = repo.create({"name": "r", "user_id": owner.uid})
    rotated = repo.rotate_token(made.id)
    assert repo.validate_token(rotated.token) is not None and repo.validate_token(made.token) is None


def test_a_site_client_token_is_found_by_its_lookup_and_rotation_moves_it(db_session, owner, verifications):
    repo = APIClientsRepository(db_session, owner.gid)
    clients = [repo.create({"name": f"site {i}", "created_by": owner.uid}) for i in range(3)]
    verifications.n = 0
    assert repo.validate_token(clients[1].token).id == clients[1].id and verifications.n == 1
    verifications.n = 0
    assert repo.validate_token("marvin_sk_" + "y" * 43) is None and verifications.n == 0
    rotated = repo.rotate_token(clients[0].id)
    assert repo.validate_token(rotated.token) is not None and repo.validate_token(clients[0].token) is None
