"""HMAC verification for incoming webhooks (Buttondown-style `X-…-Signature: sha256=<hex>`)."""

import hashlib
import hmac
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from marvin.services.webhooks.incoming_signature import verify_signature

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

        wh = SimpleNamespace(signing_secret_ref=None, signature_header=None, group_id="G")
        _check_signature(wh, BODY, self._request({}))  # no raise

    def test_valid_signature_passes(self, monkeypatch):
        import marvin.services.secrets.resolver as resolver
        from marvin.routes.hooks.hooks_controller import _check_signature

        monkeypatch.setattr(resolver, "resolve_secret", lambda ref, gid: KEY if ref == "BUTTONDOWN_SIGNING_KEY" else None)
        wh = SimpleNamespace(signing_secret_ref="{{BUTTONDOWN_SIGNING_KEY}}", signature_header="X-Buttondown-Signature", group_id="G")
        _check_signature(wh, BODY, self._request({"X-Buttondown-Signature": f"sha256={SIG}"}))

    def test_missing_or_bad_signature_is_401(self, monkeypatch):
        import marvin.services.secrets.resolver as resolver
        from marvin.routes.hooks.hooks_controller import _check_signature

        monkeypatch.setattr(resolver, "resolve_secret", lambda ref, gid: KEY)
        wh = SimpleNamespace(signing_secret_ref="BUTTONDOWN_SIGNING_KEY", signature_header="X-Buttondown-Signature", group_id="G")
        with pytest.raises(HTTPException) as e:
            _check_signature(wh, BODY, self._request({}))
        assert e.value.status_code == 401
        with pytest.raises(HTTPException):
            _check_signature(wh, BODY, self._request({"X-Buttondown-Signature": "sha256=deadbeef"}))

    def test_unresolvable_secret_fails_closed(self, monkeypatch):
        import marvin.services.secrets.resolver as resolver
        from marvin.routes.hooks.hooks_controller import _check_signature

        monkeypatch.setattr(resolver, "resolve_secret", lambda ref, gid: None)
        wh = SimpleNamespace(signing_secret_ref="MISSING", signature_header=None, group_id="G")
        with pytest.raises(HTTPException):
            _check_signature(wh, BODY, self._request({"X-Signature-256": f"sha256={SIG}"}))
