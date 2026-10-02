"""HMAC verification for incoming webhooks.

Two schemes:
- `hmac_sha256_hex` (default): senders such as Buttondown and GitHub sign the raw request body with a
  shared key and put `sha256=<hex HMAC-SHA256>` in a header.
- `square`: Square signs the notification URL it was given followed by the raw body, base64-encoded,
  in `x-square-hmacsha256-signature`.

Verification is bytes-in: the body must be the exact bytes received, never re-serialized JSON.
Comparison is constant-time.
"""

import base64
import hashlib
import hmac

DEFAULT_SIGNATURE_HEADER = "X-Signature-256"
SIGNATURE_PREFIX = "sha256="

SCHEME_HEX = "hmac_sha256_hex"
SCHEME_SQUARE = "square"
DEFAULT_HEADERS = {SCHEME_HEX: DEFAULT_SIGNATURE_HEADER, SCHEME_SQUARE: "x-square-hmacsha256-signature"}


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


def expected_square_signature(raw_body: bytes, key: str, notification_url: str) -> str:
    digest = hmac.new(key.encode("utf-8"), notification_url.encode("utf-8") + raw_body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def verify_square_signature(raw_body: bytes, header_value: str | None, key: str | None, notification_url: str | None) -> bool:
    """True when `header_value` is Square's base64 HMAC-SHA256 of `notification_url + raw_body`.
    Without the URL the sender signed, nothing verifies."""
    if not header_value or not key or not notification_url:
        return False
    return hmac.compare_digest(header_value.strip(), expected_square_signature(raw_body, key, notification_url))


def verify_for_scheme(
    scheme: str | None, raw_body: bytes, header_value: str | None, key: str | None, notification_url: str | None = None
) -> bool:
    """Dispatch on the webhook's configured scheme; an unknown scheme never verifies (fail closed)."""
    if not scheme or scheme == SCHEME_HEX:
        return verify_signature(raw_body, header_value, key)
    if scheme == SCHEME_SQUARE:
        return verify_square_signature(raw_body, header_value, key, notification_url)
    return False
