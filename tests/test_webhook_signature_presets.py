"""One signature engine, many senders: core presets, integration-contributed presets, and custom.

Each preset is checked against the sender's documented construction; Standard Webhooks against the
spec's published example.
"""

import base64
import hashlib
import hmac
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from marvin.services.webhooks.incoming_signature import PRESETS, available_schemes, spec_for, verify_request

KEY = "signing-key"
BODY = b'{"id":"evt_1","type":"thing.happened"}'
NOW = 1_700_000_000


def _hex(message: bytes, key: str = KEY) -> str:
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()


def _b64(message: bytes, key: str = KEY) -> str:
    return base64.b64encode(hmac.new(key.encode(), message, hashlib.sha256).digest()).decode()


def test_github_style_hex_body_with_prefix():
    assert verify_request(
        PRESETS["hmac_sha256_hex"], BODY, {"X-Hub-Signature-256": f"sha256={_hex(BODY)}"}, KEY, header_override="X-Hub-Signature-256"
    )


def test_shopify_base64_of_body():
    assert verify_request(PRESETS["shopify"], BODY, {"X-Shopify-Hmac-Sha256": _b64(BODY)}, KEY)


def test_slack_signs_version_timestamp_and_body():
    ts = str(NOW)
    headers = {"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": "v0=" + _hex(b"v0:" + ts.encode() + b":" + BODY)}
    assert verify_request(PRESETS["slack"], BODY, headers, KEY, now=NOW)


def test_slack_rejects_a_replayed_request():
    ts = str(NOW - 3600)
    headers = {"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": "v0=" + _hex(b"v0:" + ts.encode() + b":" + BODY)}
    assert not verify_request(PRESETS["slack"], BODY, headers, KEY, now=NOW)


def test_stripe_parses_t_and_v1_and_accepts_any_matching_v1():
    sig = _hex(f"{NOW}.".encode() + BODY)
    header = f"t={NOW},v1=deadbeef,v1={sig}"
    assert verify_request(PRESETS["stripe"], BODY, {"Stripe-Signature": header}, KEY, now=NOW)


def test_stripe_outside_tolerance_is_rejected():
    sig = _hex(f"{NOW}.".encode() + BODY)
    assert not verify_request(PRESETS["stripe"], BODY, {"Stripe-Signature": f"t={NOW},v1={sig}"}, KEY, now=NOW + 301)


def test_standard_webhooks_published_example():
    # The example from the Standard Webhooks / Svix documentation — a public example key, not a secret.
    headers = {
        "webhook-id": "msg_p5jXN8AQM9LWM0D4loKWxJek",
        "webhook-timestamp": "1614265330",
        "webhook-signature": "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE=",
    }
    secret = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"  # gitleaks:allow — the spec's published example key
    assert verify_request(PRESETS["standard_webhooks"], b'{"test": 2432232314}', headers, secret, now=1614265330)


def test_standard_webhooks_any_of_several_signatures_verifies():
    secret_bytes = b"0123456789abcdef"
    secret = "whsec_" + base64.b64encode(secret_bytes).decode()
    msg = b"msg_1." + str(NOW).encode() + b"." + BODY
    good = base64.b64encode(hmac.new(secret_bytes, msg, hashlib.sha256).digest()).decode()
    headers = {"webhook-id": "msg_1", "webhook-timestamp": str(NOW), "webhook-signature": f"v1,AAAA v1,{good}"}
    assert verify_request(PRESETS["standard_webhooks"], BODY, headers, secret, now=NOW)


def test_header_lookup_is_case_insensitive():
    assert verify_request(PRESETS["shopify"], BODY, {"x-shopify-hmac-sha256": _b64(BODY)}, KEY)


# --- custom ---------------------------------------------------------------------------------------


def test_custom_sha1_base64_of_url_and_body():
    url = "https://example.test/hook"
    config = {"algorithm": "sha1", "encoding": "base64", "message": "{url}{body}", "header": "X-Sig"}
    sig = base64.b64encode(hmac.new(KEY.encode(), url.encode() + BODY, hashlib.sha1).digest()).decode()
    assert verify_request(spec_for("custom", config), BODY, {"X-Sig": sig}, KEY, url=url)


@pytest.mark.parametrize(
    "config",
    [
        {"algorithm": "md5"},
        {"encoding": "rot13"},
        {"message": "{url}"},  # never signs the body — refused
        {"tolerance_seconds": 300},  # a tolerance with nothing to read the time from
    ],
)
def test_custom_config_that_cannot_work_has_no_spec(config):
    assert spec_for("custom", config) is None


# --- integration-contributed presets --------------------------------------------------------------


def test_integration_preset_resolves_and_is_listed(monkeypatch):
    pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")
    from marvin_integration_sdk import INTEGRATION_REGISTRY, IntegrationProvider

    class _Shop(IntegrationProvider):
        slug = "shop"
        name = "Shop"
        signature_schemes = {
            "shop": {"encoding": "base64", "message": "{url}{body}", "header": "x-shop-sig", "notes": "Shop: URL + body", "sender_issues_key": True},
            "hmac_sha256_hex": {"header": "x-hijack"},  # a core name: ignored, core wins
            "broken": {"algorithm": "md5"},  # unusable: skipped
        }

    monkeypatch.setitem(INTEGRATION_REGISTRY, "shop", _Shop())

    url = "https://example.test/hook"
    assert verify_request(spec_for("shop"), BODY, {"x-shop-sig": _b64(url.encode() + BODY)}, KEY, url=url)
    assert spec_for("hmac_sha256_hex").header == "X-Signature-256"
    assert spec_for("broken") is None
    listed = {(row["name"], row["source"]) for row in available_schemes()}
    assert ("shop", "shop") in listed and ("custom", "core") in listed
    issued = {row["name"]: row["sender_issues_key"] for row in available_schemes()}
    assert issued["shop"] is True  # an integration says so for its sender


def test_schemes_say_whether_the_sender_issues_the_key():
    """Stripe, Slack, Shopify and Standard Webhooks show you their key (nothing to generate); for a GitHub-style
    HMAC or a static token you choose the key, so the editor offers Generate key."""
    issued = {row["name"]: row["sender_issues_key"] for row in available_schemes()}
    assert all(issued[n] for n in ("stripe", "slack", "shopify", "standard_webhooks"))
    assert not any(issued[n] for n in ("hmac_sha256_hex", "static_token", "custom"))


def test_a_preset_from_an_uninstalled_integration_fails_closed():
    assert spec_for("no-such-integration-scheme") is None


# --- saving a webhook ----------------------------------------------------------------------------


def test_saving_an_unknown_scheme_is_refused():
    from marvin.routes.hooks.incoming_webhooks_controller import _require_usable_scheme

    with pytest.raises(HTTPException) as exc:
        _require_usable_scheme("made-up", None)
    assert exc.value.status_code == 422 and "unknown" in exc.value.detail


def test_saving_an_invalid_custom_config_says_why():
    from marvin.routes.hooks.incoming_webhooks_controller import _require_usable_scheme

    with pytest.raises(HTTPException) as exc:
        _require_usable_scheme("custom", {"message": "{url}"})
    assert "{body}" in exc.value.detail


def test_saving_a_preset_or_no_scheme_is_fine():
    from marvin.routes.hooks.incoming_webhooks_controller import _require_usable_scheme

    for scheme in (None, "stripe", "slack"):
        _require_usable_scheme(scheme, None)


def test_receiver_with_a_stripe_webhook(monkeypatch):
    import time

    import marvin.services.secrets.resolver as resolver
    from marvin.routes.hooks.hooks_controller import _check_signature

    monkeypatch.setattr(resolver, "resolve_secret", lambda ref, gid: KEY)
    now = int(time.time())
    header = f"t={now},v1={_hex(f'{now}.'.encode() + BODY)}"
    webhook = SimpleNamespace(
        slug="stripe",
        signing_secret_ref="STRIPE_KEY",
        signature_header=None,
        group_id="G",
        signature_scheme="stripe",
        signature_url=None,
        signature_config=None,
    )
    _check_signature(webhook, BODY, SimpleNamespace(headers={"Stripe-Signature": header}))  # no raise


# --- static tokens (Cloudflare notifications, GitLab): the header carries the secret itself -------


def test_static_token_matches_the_secret_in_a_chosen_header():
    spec = PRESETS["static_token"]
    assert verify_request(spec, BODY, {"cf-webhook-auth": KEY}, KEY, header_override="cf-webhook-auth")


def test_static_token_rejects_a_wrong_or_missing_token():
    spec = PRESETS["static_token"]
    assert not verify_request(spec, BODY, {"cf-webhook-auth": "nope"}, KEY, header_override="cf-webhook-auth")
    assert not verify_request(spec, BODY, {}, KEY, header_override="cf-webhook-auth")


def test_a_custom_token_scheme_needs_only_a_header():
    assert spec_for("custom", {"mode": "token", "header": "X-Gitlab-Token"}) is not None
    assert spec_for("custom", {"mode": "token", "header": ""}) is None


def test_a_rejected_static_token_is_never_echoed_in_the_log(monkeypatch, caplog):
    import marvin.services.secrets.resolver as resolver
    from marvin.routes.hooks.hooks_controller import _check_signature

    monkeypatch.setattr(resolver, "resolve_secret", lambda ref, gid: "the-real-token")
    webhook = SimpleNamespace(
        slug="cf",
        signing_secret_ref="CF_TOKEN",
        signature_header="cf-webhook-auth",
        group_id="G",
        signature_scheme="static_token",
        signature_url=None,
        signature_config=None,
    )
    with pytest.raises(HTTPException):
        _check_signature(webhook, BODY, SimpleNamespace(headers={"cf-webhook-auth": "the-wrong-token"}))
    assert "the-wr" not in caplog.text
