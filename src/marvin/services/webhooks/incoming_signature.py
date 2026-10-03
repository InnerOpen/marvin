"""HMAC verification for incoming webhooks — one engine, many senders.

Most webhook senders sign the same way with different details: an HMAC (SHA-1/256/512) of a
*message* built from the request, encoded as hex or base64, carried in a header, sometimes with a
prefix (`sha256=`, `v0=`, `v1,`) and sometimes with a timestamp to stop replays. A
:class:`SignatureSpec` names those details. Core presets cover well-known senders that are useful
without any integration; an installed integration may contribute its own (`signature_schemes` on the
provider — Square's lives in the Square integration); and `custom` lets a workspace describe any other.

The message is a template over the raw request: `{body}` (the exact bytes received, never
re-serialized JSON), `{url}` (the public URL the sender was given — behind a tunnel the backend
sees another one), `{header:Name}`, and `{t}` (the timestamp parsed from a Stripe-style header).

Some senders don't sign at all but send a fixed shared token in a header (Cloudflare notifications,
GitLab): `mode="token"` compares that header with the secret instead of computing an HMAC.

Comparison is constant-time. Anything missing — key, header, a URL the template needs, a parseable
timestamp — fails closed.
"""

import base64
import hashlib
import hmac
import time
from collections.abc import Mapping
from dataclasses import dataclass, field

DEFAULT_SIGNATURE_HEADER = "X-Signature-256"
SIGNATURE_PREFIX = "sha256="

ALGORITHMS = {"sha1": hashlib.sha1, "sha256": hashlib.sha256, "sha512": hashlib.sha512}


@dataclass(frozen=True)
class SignatureSpec:
    """How one sender signs. Every field has a sensible default, so a preset only states what differs."""

    mode: str = "hmac"
    """hmac (an HMAC of a message built from the request) | token (the header carries the secret itself)."""

    algorithm: str = "sha256"
    """sha1 | sha256 | sha512."""

    encoding: str = "hex"
    """hex | base64 — how the digest is written in the header."""

    message: str = "{body}"
    """What is signed: `{body}`, `{url}`, `{header:Name}`, `{t}` and literal text, e.g. `v0:{header:X-Slack-Request-Timestamp}:{body}`."""

    header: str = DEFAULT_SIGNATURE_HEADER
    """Where the signature arrives (overridable per webhook)."""

    prefix: str = ""
    """Stripped from each presented signature when present: `sha256=`, `v0=`, `v1,`."""

    multiple: bool = False
    """The header may carry several space-separated signatures (key rotation); any one matching verifies."""

    header_format: str = "plain"
    """plain | stripe (`t=<ts>,v1=<sig>[,v1=<sig>]` — the timestamp `{t}` comes from the same header)."""

    key_format: str = "raw"
    """raw (the secret's UTF-8 bytes) | base64 (decode it first, dropping a `whsec_` prefix — Standard Webhooks)."""

    timestamp_header: str | None = None
    """Header carrying the send time (seconds); with `tolerance_seconds` it rejects replays."""

    tolerance_seconds: int | None = None
    """How old (or far in the future) a signed request may be. None = no check."""

    notes: str = field(default="", compare=False)


PRESETS: dict[str, SignatureSpec] = {
    # GitHub, Buttondown and most others: `sha256=<hex HMAC of the raw body>`. Marvin's original scheme.
    "hmac_sha256_hex": SignatureSpec(prefix=SIGNATURE_PREFIX, notes="sha256=<hex> of the body (GitHub, Buttondown, …)"),
    "shopify": SignatureSpec(encoding="base64", header="X-Shopify-Hmac-Sha256", notes="Shopify: base64 of the body"),
    "slack": SignatureSpec(
        message="v0:{header:X-Slack-Request-Timestamp}:{body}",
        header="X-Slack-Signature",
        prefix="v0=",
        timestamp_header="X-Slack-Request-Timestamp",
        tolerance_seconds=300,
        notes="Slack: v0=<hex> of v0:{timestamp}:{body}",
    ),
    "stripe": SignatureSpec(
        message="{t}.{body}",
        header="Stripe-Signature",
        header_format="stripe",
        tolerance_seconds=300,
        notes="Stripe: t=…,v1=<hex> of {t}.{body}",
    ),
    "standard_webhooks": SignatureSpec(
        encoding="base64",
        message="{header:webhook-id}.{header:webhook-timestamp}.{body}",
        header="webhook-signature",
        prefix="v1,",
        multiple=True,
        key_format="base64",
        timestamp_header="webhook-timestamp",
        tolerance_seconds=300,
        notes="Standard Webhooks (Svix, Resend, Clerk, …): v1,<base64> of {id}.{timestamp}.{body}",
    ),
    # Not a signature: the sender puts the shared secret itself in a header. Set the header per webhook
    # (e.g. cf-webhook-auth for Cloudflare notifications, X-Gitlab-Token for GitLab).
    "static_token": SignatureSpec(
        mode="token",
        header="X-Webhook-Token",
        notes="A fixed shared token in a header (Cloudflare: cf-webhook-auth, GitLab: X-Gitlab-Token) — set the header",
    ),
}

DEFAULT_SCHEME = "hmac_sha256_hex"
CUSTOM_SCHEME = "custom"

SPEC_FIELDS = (
    "mode",
    "algorithm",
    "encoding",
    "message",
    "header",
    "prefix",
    "multiple",
    "header_format",
    "key_format",
    "timestamp_header",
    "tolerance_seconds",
)


def _build(config: dict | None) -> SignatureSpec | None:
    try:
        spec = SignatureSpec(**{k: v for k, v in (config or {}).items() if k in (*SPEC_FIELDS, "notes")})
    except TypeError:
        return None
    return spec if spec_problems(spec) == [] else None


def provider_presets() -> dict[str, tuple[SignatureSpec, str]]:
    """Presets contributed by installed integrations: name → (spec, provider slug). A malformed
    declaration is skipped with a warning; a name core already uses is ignored (core wins)."""
    from marvin.services.integrations import INTEGRATIONS_AVAILABLE

    if not INTEGRATIONS_AVAILABLE:
        return {}
    from marvin.core.root_logger import get_logger
    from marvin.services.integrations import list_providers

    found: dict[str, tuple[SignatureSpec, str]] = {}
    for provider in list_providers():
        for name, config in (getattr(provider, "signature_schemes", None) or {}).items():
            if name in PRESETS or name == CUSTOM_SCHEME or name in found:
                continue
            spec = _build(config if isinstance(config, dict) else None)
            if spec is None:
                get_logger(__name__).warning("integration %s declared an unusable signature scheme %r", getattr(provider, "slug", "?"), name)
                continue
            found[name] = (spec, provider.slug)
    return found


def available_schemes() -> list[dict]:
    """Every scheme a webhook can pick: core presets, integration presets, then `custom`."""
    rows = [{"name": name, "notes": spec.notes, "source": "core"} for name, spec in PRESETS.items()]
    rows += [{"name": name, "notes": spec.notes, "source": slug} for name, (spec, slug) in provider_presets().items()]
    rows.append({"name": CUSTOM_SCHEME, "notes": "Describe the sender's construction yourself", "source": "core"})
    return rows


def spec_for(scheme: str | None, config: dict | None = None) -> SignatureSpec | None:
    """The spec a webhook verifies with: a core preset, an installed integration's preset, or
    `custom` built from its config. None for an unknown scheme or an invalid custom config — and for
    an integration preset whose integration was uninstalled — so the caller fails closed."""
    if not scheme:
        return PRESETS[DEFAULT_SCHEME]
    if scheme == CUSTOM_SCHEME:
        return _build(config)
    if scheme in PRESETS:
        return PRESETS[scheme]
    contributed = provider_presets().get(scheme)
    return contributed[0] if contributed else None


def spec_problems(spec: SignatureSpec) -> list[str]:
    """Why a custom spec can't be used — empty when it can."""
    problems = []
    if spec.mode not in ("hmac", "token"):
        problems.append("mode must be hmac or token")
    if spec.mode == "token":
        return problems + ([] if spec.header else ["header is required"])
    if spec.algorithm not in ALGORITHMS:
        problems.append(f"algorithm must be one of {', '.join(ALGORITHMS)}")
    if spec.encoding not in ("hex", "base64"):
        problems.append("encoding must be hex or base64")
    if spec.header_format not in ("plain", "stripe"):
        problems.append("header_format must be plain or stripe")
    if spec.key_format not in ("raw", "base64"):
        problems.append("key_format must be raw or base64")
    if "{body}" not in spec.message:
        problems.append("message must include {body}")
    if not spec.header:
        problems.append("header is required")
    if spec.tolerance_seconds is not None and spec.header_format != "stripe" and not spec.timestamp_header:
        problems.append("tolerance_seconds needs a timestamp_header")
    return problems


def _header(headers: Mapping, name: str) -> str | None:
    """Case-insensitive lookup — Starlette's Headers already are; a plain dict (tests, adapters) may not be."""
    value = headers.get(name)
    if value is None:
        lowered = name.lower()
        value = next((v for k, v in headers.items() if k.lower() == lowered), None)
    return value


def _key_bytes(key: str, key_format: str) -> bytes | None:
    if key_format == "base64":
        raw = key.split("_", 1)[1] if key.startswith("whsec_") else key
        try:
            return base64.b64decode(raw, validate=True)
        except (ValueError, TypeError):
            return None
    return key.encode("utf-8")


def _message(spec: SignatureSpec, raw_body: bytes, headers: Mapping, url: str | None, t: str | None) -> bytes | None:
    """Render the template. A placeholder whose value is missing makes the whole message None (fail closed)."""
    out = bytearray()
    rest = spec.message
    while rest:
        start = rest.find("{")
        if start < 0:
            out += rest.encode()
            break
        end = rest.find("}", start)
        if end < 0:
            return None
        out += rest[:start].encode()
        token = rest[start + 1 : end]
        if token == "body":
            value: bytes | None = raw_body
        elif token == "url":
            value = url.encode() if url else None
        elif token == "t":
            value = t.encode() if t else None
        elif token.startswith("header:"):
            found = _header(headers, token[len("header:") :])
            value = found.encode() if found is not None else None
        else:
            value = None
        if value is None:
            return None
        out += value
        rest = rest[end + 1 :]
    return bytes(out)


def _presented(spec: SignatureSpec, header_value: str) -> tuple[list[str], str | None]:
    """The candidate signatures in the header, and a timestamp carried alongside them (Stripe)."""
    if spec.header_format == "stripe":
        parts = [p.split("=", 1) for p in header_value.split(",") if "=" in p]
        t = next((v.strip() for k, v in parts if k.strip() == "t"), None)
        return [v.strip() for k, v in parts if k.strip() == "v1"], t
    candidates = header_value.split() if spec.multiple else [header_value.strip()]
    stripped = []
    for candidate in candidates:
        if spec.prefix and candidate.lower().startswith(spec.prefix.lower()):
            candidate = candidate[len(spec.prefix) :]
        stripped.append(candidate.strip())
    return stripped, None


def _fresh(spec: SignatureSpec, headers: Mapping, t: str | None, now: float) -> bool:
    if spec.tolerance_seconds is None:
        return True
    stamp = t if spec.header_format == "stripe" else (_header(headers, spec.timestamp_header) if spec.timestamp_header else None)
    try:
        return abs(now - int(str(stamp).strip())) <= spec.tolerance_seconds
    except (TypeError, ValueError):
        return False


def verify_request(
    spec: SignatureSpec | None,
    raw_body: bytes,
    headers: Mapping,
    key: str | None,
    *,
    url: str | None = None,
    header_override: str | None = None,
    now: float | None = None,
) -> bool:
    """True when the request carries a valid signature for `spec` under `key`."""
    if spec is None or not key:
        return False
    header_value = _header(headers, header_override or spec.header)
    if not header_value:
        return False
    if spec.mode == "token":
        presented = header_value.strip()
        if spec.prefix and presented.lower().startswith(spec.prefix.lower()):
            presented = presented[len(spec.prefix) :].strip()
        return hmac.compare_digest(presented.encode("utf-8"), key.encode("utf-8"))
    candidates, t = _presented(spec, header_value)
    if not candidates or not _fresh(spec, headers, t, time.time() if now is None else now):
        return False
    key_bytes = _key_bytes(key, spec.key_format)
    message = _message(spec, raw_body, headers, url, t)
    if key_bytes is None or message is None:
        return False
    digest = hmac.new(key_bytes, message, ALGORITHMS[spec.algorithm]).digest()
    if spec.encoding == "hex":
        expected = digest.hex()
        return any(hmac.compare_digest(c.lower(), expected) for c in candidates)
    expected = base64.b64encode(digest).decode("ascii")
    return any(hmac.compare_digest(c, expected) for c in candidates)


def expected_signature(raw_body: bytes, key: str) -> str:
    return hmac.new(key.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def verify_signature(raw_body: bytes, header_value: str | None, key: str | None) -> bool:
    """The original scheme on its own: `sha256=<hex>` (prefix optional, case-insensitive hex) of the raw body."""
    return verify_request(PRESETS[DEFAULT_SCHEME], raw_body, {DEFAULT_SIGNATURE_HEADER: header_value or ""}, key)
