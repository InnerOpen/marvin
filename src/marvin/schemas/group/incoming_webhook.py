"""Pydantic schemas for workspace incoming (ingress) webhooks.

An incoming webhook is a tokened endpoint: an external POST to its URL emits an `incoming_webhook`
event onto the bus. These schemas cover admin management (CRUD) and token minting. The secret
`token` is only returned to ADMINs (who manage the webhook) — the receiver itself is public and
authenticates purely by the token value.
"""

from datetime import datetime

from pydantic import UUID4, ConfigDict

from marvin.schemas._marvin import _MarvinModel

# How the sender signs — a core preset, an installed integration's preset, or `custom` with
# `signature_config`. Names are validated by the controller (integration presets are dynamic).
SignatureScheme = str


class IncomingWebhookCreate(_MarvinModel):
    name: str
    slug: str | None = None  # generated from name when omitted
    description: str | None = None
    enabled: bool = False
    # HMAC verification (optional): workspace secret slug holding the sender's signing key, and the
    # header that carries `sha256=<hex>` (defaults to X-Signature-256 when unset).
    signing_secret_ref: str | None = None
    signature_header: str | None = None
    signature_scheme: SignatureScheme | None = None
    signature_url: str | None = None
    signature_config: dict | None = None
    # Answering a sender's verification request (a GET): an integration's scheme or `custom` (+ verification_config), and
    # the workspace secret the sender's verify token must match.
    verification_scheme: str | None = None
    verification_config: dict | None = None
    verify_token_ref: str | None = None

    model_config = ConfigDict(from_attributes=True)


class IncomingWebhookUpdate(_MarvinModel):
    name: str | None = None
    description: str | None = None
    enabled: bool | None = None
    signing_secret_ref: str | None = None
    signature_header: str | None = None
    signature_scheme: SignatureScheme | None = None
    signature_url: str | None = None
    signature_config: dict | None = None
    # Answering a sender's verification request (a GET): an integration's scheme or `custom` (+ verification_config), and
    # the workspace secret the sender's verify token must match.
    verification_scheme: str | None = None
    verification_config: dict | None = None
    verify_token_ref: str | None = None

    model_config = ConfigDict(from_attributes=True)


class IncomingWebhookRead(_MarvinModel):
    id: UUID4
    group_id: UUID4
    name: str
    slug: str
    description: str | None = None
    enabled: bool
    token: str | None = None  # the secret; ADMIN-only surface. Null = no token minted yet.
    signing_secret_ref: str | None = None
    signature_header: str | None = None
    signature_scheme: SignatureScheme | None = None
    signature_url: str | None = None
    signature_config: dict | None = None
    verification_scheme: str | None = None
    """How the sender's verification request (a GET) carries its challenge and token: an integration's scheme or `custom`."""
    verification_config: dict | None = None
    verify_token_ref: str | None = None
    """The workspace secret the sender's verify token must match; with no scheme or secret, a GET is refused."""
    received_count: int = 0
    last_received_at: datetime | None = None
    refused_count: int = 0
    """Deliveries the hook turned away (a bad signature, a refused verification, switched off), its token matching."""
    last_refused_at: datetime | None = None
    last_refused_reason: str | None = None
    source_integration_id: UUID4 | None = None
    """Read-only "installed by": the integration whose blueprint created this (null: made by a person)."""
    source_blueprint: str | None = None
    """Read-only: the slug of the blueprint that created this, if one did."""

    model_config = ConfigDict(from_attributes=True)
