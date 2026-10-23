"""An incoming webhook answers a sender's verification request — a GET carrying a challenge and the verify token it was
given, where the webhook's verification scheme says — only when the token matches its secret. Then the challenge comes
back and an `incoming_webhook_verified` event is recorded; never a delivery. Core knows no sender: integrations declare
schemes (`verification_schemes`), and `custom` describes any other."""

import uuid
from types import SimpleNamespace

import pytest

from marvin.db.models.groups import Groups
from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel
from marvin.services.webhooks import incoming_verification as verification

PHRASE = "a-phrase-the-sender-was-given"
HUB = {"challenge_param": "hub.challenge", "token_param": "hub.verify_token", "mode_param": "hub.mode", "mode_values": ["subscribe"]}


@pytest.fixture
def hook(db_session, monkeypatch):
    """An enabled incoming webhook answering a `custom` hub-style check with the workspace secret HOOK_VERIFY (= PHRASE)."""
    gid = uuid.uuid4()
    group = Groups(session=db_session, name=f"ver-{gid.hex[:8]}", slug=f"ver-{gid.hex[:8]}")
    group.id = gid
    db_session.add(group)
    row = WorkspaceIncomingWebhookModel(
        session=db_session, group_id=gid, name="Inbox", slug="inbox", enabled=True, token=f"tok-{gid.hex}",
        verification_scheme="custom", verification_config=HUB, verify_token_ref="HOOK_VERIFY",
    )  # fmt: skip
    db_session.add(row)
    db_session.commit()
    secrets = {("HOOK_VERIFY", str(gid)): PHRASE}
    monkeypatch.setattr("marvin.services.secrets.resolver.resolve_secret", lambda slug, group_id=None: secrets.get((slug, str(group_id))))
    sent = []
    from marvin.services.event_bus_service.event_bus_service import EventBusService

    monkeypatch.setattr(EventBusService, "dispatch", lambda self, **kw: sent.append(kw))
    yield row, sent
    db_session.query(WorkspaceIncomingWebhookModel).filter_by(group_id=gid).delete()
    db_session.query(Groups).filter_by(id=gid).delete()
    db_session.commit()


def _check(client, token, **params):
    query = {"hub.mode": "subscribe", "hub.challenge": "1158201444", "hub.verify_token": PHRASE} | params
    return client.get(f"/api/hooks/{token}", params={k: v for k, v in query.items() if v is not None})


def test_a_matching_request_gets_its_challenge_back_and_is_recorded_as_verified(client, hook):
    row, sent = hook

    response = _check(client, row.token)

    assert (response.status_code, response.text) == (200, "1158201444")
    assert response.headers["content-type"].startswith("text/plain")
    (event,) = sent
    assert event["event_type"].name == "incoming_webhook_verified"  # never the delivery event
    assert event["document_data"].payload == {"hub.mode": "subscribe"}  # the verify token is the secret: never recorded


def test_a_wrong_or_missing_token_or_mode_is_refused(client, hook):
    row, sent = hook

    assert _check(client, row.token, **{"hub.verify_token": "guess"}).status_code == 403
    assert _check(client, row.token, **{"hub.verify_token": None}).status_code == 403
    assert _check(client, row.token, **{"hub.mode": "unsubscribe"}).status_code == 403
    assert sent == []


def test_a_webhook_without_its_secret_answers_nothing(client, hook, db_session):
    row, _ = hook
    row.verify_token_ref = None
    db_session.commit()

    assert _check(client, row.token).status_code == 403


def test_a_webhook_without_a_scheme_takes_no_get(client, hook, db_session):
    row, _ = hook
    row.verification_scheme = None
    db_session.commit()

    assert _check(client, row.token).status_code == 405


def test_a_disabled_webhook_or_an_unknown_token_answers_nothing(client, hook, db_session):
    row, _ = hook
    assert _check(client, "not-a-token").status_code == 401
    row.enabled = False
    db_session.commit()

    assert _check(client, row.token).status_code == 403


def test_a_plain_get_such_as_a_link_preview_is_not_a_delivery(client, hook):
    row, sent = hook

    response = client.get(f"/api/hooks/{row.token}")

    assert response.status_code == 405 and sent == []


def test_a_scheme_can_answer_in_json(client, hook, db_session):
    row, _ = hook
    row.verification_config = {**HUB, "content_type": "application/json"}
    db_session.commit()

    response = _check(client, row.token)

    assert response.json() == "1158201444"


def test_an_integration_contributes_a_scheme_and_custom_is_core_only(monkeypatch):
    monkeypatch.setattr("marvin.services.integrations.INTEGRATIONS_AVAILABLE", True)
    providers = [
        SimpleNamespace(slug="instagram", verification_schemes={"meta": {**HUB, "notes": "Meta"}}),
        SimpleNamespace(slug="facebook", verification_schemes={"meta": {"challenge_param": "x"}}),  # the name is taken
        SimpleNamespace(slug="broken", verification_schemes={"half": {"challenge_param": "only"}}),  # unusable: skipped
    ]
    monkeypatch.setattr("marvin.services.integrations.list_providers", lambda: providers)

    assert [(r["name"], r["source"]) for r in verification.available_schemes()] == [("meta", "instagram"), ("custom", "core")]
    assert verification.spec_for("meta", None).token_param == "hub.verify_token"
    assert verification.usable("nope", None) and verification.usable("custom", {"challenge_param": "c"})
    assert verification.usable("meta", None) is None and verification.usable(None, None) is None
