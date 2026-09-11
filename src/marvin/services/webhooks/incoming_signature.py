"""HMAC verification for incoming webhooks.

Senders such as Buttondown, GitHub and Stripe sign the raw request body with a shared key and put
`sha256=<hex HMAC-SHA256>` in a header. Verification is bytes-in: the body must be the exact bytes
received, never re-serialized JSON. Comparison is constant-time.
"""

import hashlib
import hmac

DEFAULT_SIGNATURE_HEADER = "X-Signature-256"
SIGNATURE_PREFIX = "sha256="


def expected_signature(raw_body: bytes, key: str) -> str:
    return hmac.new(key.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def verify_signature(raw_body: bytes, header_value: str | None, key: str | None) -> bool:
    """True when `header_value` is `sha256=<hex>` (prefix optional, case-insensitive hex) matching the
    HMAC-SHA256 of `raw_body` under `key`. A missing header or key never verifies."""
    if not header_value or not key:
        return False
    presented = header_value.strip()
    if presented.lower().startswith(SIGNATURE_PREFIX):
        presented = presented[len(SIGNATURE_PREFIX) :]
    return hmac.compare_digest(presented.lower(), expected_signature(raw_body, key))
