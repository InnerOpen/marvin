"""HMAC verification for incoming webhooks (Buttondown-style `X-…-Signature: sha256=<hex>`)."""

import base64
import hashlib
import hmac
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from marvin.services.webhooks.incoming_signature import verify_for_scheme, verify_signature

BODY = b'{"event_type":"subscriber.unsubscribed","data":{"email_address":"a@b.c"}}'
KEY = "wh-signing-key"
SIG = hmac.new(KEY.encode(), BODY, hashlib.sha256).hexdigest()


class TestVerifySignature:
    def test_valid_signature_with_prefix_verifies(self):
        assert verify_signature(BODY, f"sha256={SIG}", KEY)

    def test_valid_signature_without_prefix_verifies(self):
        assert verify_signature(BODY, SIG, KEY)

    def test_uppercase_hex_verifies(self):
        assert verify_signature(BODY, "sha256=" + SIG.upper(), KEY)

    def test_wrong_key_does_not_verify(self):
        assert not verify_signature(BODY, f"sha256={SIG}", "other-key")

    def test_tampered_body_does_not_verify(self):
        assert not verify_signature(BODY + b" ", f"sha256={SIG}", KEY)

    def test_missing_header_or_key_never_verifies(self):
        assert not verify_signature(BODY, None, KEY)
        assert not verify_signature(BODY, f"sha256={SIG}", None)


class TestReceiverSignatureGate:
    def _request(self, headers: dict):
        return SimpleNamespace(headers=headers)

    def test_no_signing_ref_skips_verification(self):
        from marvin.routes.hooks.hooks_controller import _check_signature

        wh = SimpleNamespace(slug="hook", signing_secret_ref=None, signature_header=None, group_id="G", signature_scheme=None, signature_url=None)
        _check_signature(wh, BODY, self._request({}))  # no raise

    def test_valid_signature_passes(self, monkeypatch):
        import marvin.services.secrets.resolver as resolver
        from marvin.routes.hooks.hooks_controller import _check_signature

        monkeypatch.setattr(resolver, "resolve_secret", lambda ref, gid: KEY if ref == "BUTTONDOWN_SIGNING_KEY" else None)
        wh = SimpleNamespace(
            slug="hook",
            signing_secret_ref="{{BUTTONDOWN_SIGNING_KEY}}",
            signature_header="X-Buttondown-Signature",
            group_id="G",
            signature_scheme=None,
            signature_url=None,
        )
        _check_signature(wh, BODY, self._request({"X-Buttondown-Signature": f"sha256={SIG}"}))

    def test_missing_or_bad_signature_is_401(self, monkeypatch):
        import marvin.services.secrets.resolver as resolver
        from marvin.routes.hooks.hooks_controller import _check_signature

        monkeypatch.setattr(resolver, "resolve_secret", lambda ref, gid: KEY)
        wh = SimpleNamespace(
            slug="hook",
            signing_secret_ref="BUTTONDOWN_SIGNING_KEY",
            signature_header="X-Buttondown-Signature",
            group_id="G",
            signature_scheme=None,
            signature_url=None,
        )
        with pytest.raises(HTTPException) as e:
            _check_signature(wh, BODY, self._request({}))
        assert e.value.status_code == 401
        with pytest.raises(HTTPException):
            _check_signature(wh, BODY, self._request({"X-Buttondown-Signature": "sha256=deadbeef"}))

    def test_unresolvable_secret_fails_closed(self, monkeypatch):
        import marvin.services.secrets.resolver as resolver
        from marvin.routes.hooks.hooks_controller import _check_signature

        monkeypatch.setattr(resolver, "resolve_secret", lambda ref, gid: None)
        wh = SimpleNamespace(
            slug="hook", signing_secret_ref="MISSING", signature_header=None, group_id="G", signature_scheme=None, signature_url=None
        )
        with pytest.raises(HTTPException):
            _check_signature(wh, BODY, self._request({"X-Signature-256": f"sha256={SIG}"}))


SQUARE_URL = "https://api.iwobble.com/api/hooks/tok123"
SQUARE_BODY = b'{"type":"payment.updated","data":{"object":{"payment":{"status":"COMPLETED","order_id":"o1"}}}}'
SQUARE_SIG = base64.b64encode(hmac.new(KEY.encode(), SQUARE_URL.encode() + SQUARE_BODY, hashlib.sha256).digest()).decode()


class TestSquareScheme:
    def test_square_signature_over_url_and_body_verifies(self):
        assert verify_for_scheme("square", SQUARE_BODY, SQUARE_SIG, KEY, SQUARE_URL)

    def test_square_signature_for_another_url_does_not_verify(self):
        assert not verify_for_scheme("square", SQUARE_BODY, SQUARE_SIG, KEY, SQUARE_URL + "x")

    def test_square_signature_tampered_body_does_not_verify(self):
        assert not verify_for_scheme("square", SQUARE_BODY + b" ", SQUARE_SIG, KEY, SQUARE_URL)

    def test_square_without_configured_url_never_verifies(self):
        assert not verify_for_scheme("square", SQUARE_BODY, SQUARE_SIG, KEY, None)

    def test_hex_body_signature_is_not_accepted_as_square(self):
        hex_sig = hmac.new(KEY.encode(), SQUARE_BODY, hashlib.sha256).hexdigest()
        assert not verify_for_scheme("square", SQUARE_BODY, hex_sig, KEY, SQUARE_URL)

    def test_unknown_scheme_fails_closed(self):
        assert not verify_for_scheme("made-up", BODY, f"sha256={SIG}", KEY)

    def test_no_scheme_is_the_original_hex_check(self):
        assert verify_for_scheme(None, BODY, f"sha256={SIG}", KEY)


class TestReceiverSquareGate:
    def _webhook(self, url=SQUARE_URL):
        return SimpleNamespace(
            slug="square",
            signing_secret_ref="SQUARE_SIGNATURE_KEY",
            signature_header=None,
            group_id="G",
            signature_scheme="square",
            signature_url=url,
        )

    def test_square_scheme_reads_square_header_by_default(self, monkeypatch):
        import marvin.services.secrets.resolver as resolver
        from marvin.routes.hooks.hooks_controller import _check_signature

        monkeypatch.setattr(resolver, "resolve_secret", lambda ref, gid: KEY)
        request = SimpleNamespace(headers={"x-square-hmacsha256-signature": SQUARE_SIG})
        _check_signature(self._webhook(), SQUARE_BODY, request)  # no raise

    def test_square_scheme_without_url_is_401(self, monkeypatch):
        import marvin.services.secrets.resolver as resolver
        from marvin.routes.hooks.hooks_controller import _check_signature

        monkeypatch.setattr(resolver, "resolve_secret", lambda ref, gid: KEY)
        request = SimpleNamespace(headers={"x-square-hmacsha256-signature": SQUARE_SIG})
        with pytest.raises(HTTPException) as e:
            _check_signature(self._webhook(url=None), SQUARE_BODY, request)
        assert e.value.status_code == 401
