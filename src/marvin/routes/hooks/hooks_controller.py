"""Public receiver for incoming (ingress) webhooks.

`POST /api/hooks/{token}` is the ingress endpoint; `GET` only answers a sender's verification request, where the
webhook's verification scheme says (services/webhooks/incoming_verification.py). It has no login/session — the URL's secret
`token` IS the credential (the same model as a Slack/GitHub incoming webhook URL). The token may
also be presented as `Authorization: Bearer <token>` for callers that prefer not to put secrets in
URLs; either way the webhook is resolved by token.

On a valid, enabled webhook the receiver drops one `incoming_webhook` event onto the event bus
carrying the request body as `payload`, then returns `202 Accepted` immediately — the event bus
runs subscribers (automations, Flavor A reactions, the audit log) in the background. Pass `?wait=1`
to run subscribers inline and get the outcome back (used by the management page's "Send test").
"""

import json
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session

from marvin.core.root_logger import get_logger
from marvin.db.db_setup import generate_session
from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel
from marvin.services.event_bus_service.event_bus_service import EventBusService
from marvin.services.event_bus_service.event_types import EventIncomingWebhookData, EventTypes
from marvin.services.security.client_info import get_client_ip
from marvin.services.webhooks.incoming_signature import spec_for, verify_request

router = APIRouter()
logger = get_logger(__name__)

# Reject bodies larger than this — an ingress endpoint should never buffer arbitrary payloads.
_MAX_BODY_BYTES = 512 * 1024


def _too_large() -> HTTPException:
    return HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Payload too large.")


async def _read_capped(request: Request, limit: int = _MAX_BODY_BYTES) -> bytes:
    """The body, read a chunk at a time and abandoned as soon as it passes ``limit`` (413), so an oversized POST is
    never buffered whole (``request.body()`` reads everything first). A declared Content-Length over the limit is
    refused before reading anything; a missing or false one is caught by the running count."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise _too_large()
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise _too_large()
        chunks.append(chunk)
    return b"".join(chunks)


def _check_signature(webhook: WorkspaceIncomingWebhookModel, raw: bytes, request: Request) -> None:
    """When the webhook names a signing secret, the request must carry a valid HMAC — fail closed:
    an unresolvable secret, a missing header or a mismatch all reject with 401."""
    if not (webhook.signing_secret_ref or "").strip():
        return
    key = _secret_value(webhook.signing_secret_ref, webhook.group_id)
    scheme = webhook.signature_scheme
    spec = spec_for(scheme, webhook.signature_config)
    header = webhook.signature_header or (spec.header if spec else "?")
    presented = request.headers.get(header)
    if not verify_request(spec, raw, request.headers, key, url=webhook.signature_url, header_override=webhook.signature_header):
        # Say what arrived without leaking it: the header's shape is enough to tell a wrong key from a
        # wrong header name or an unexpected encoding (base64 vs hex, missing prefix).
        # A static token IS the secret, so never echo any of it — length only.
        is_token = bool(spec and spec.mode == "token")
        shape = "absent" if presented is None else (f"len={len(presented)}" if is_token else f"len={len(presented)} prefix={presented[:7]!r}")
        logger.warning(
            "incoming webhook %s: signature rejected (scheme %s; header %s %s; key %s; url %s; body %d bytes; signature headers seen: %s)",
            webhook.slug,
            (scheme or "hmac_sha256_hex") if spec else f"{scheme} (unknown or invalid — integration uninstalled?)",
            header,
            shape,
            "resolved" if key else "UNRESOLVED",
            "set" if webhook.signature_url else "unset",
            len(raw),
            [h for h in request.headers if "sign" in h.lower()],
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature.")


def _resolve_token(path_token: str, authorization: str | None) -> str:
    """The token comes from the path, or from an `Authorization: Bearer <token>` header."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return path_token


def _secret_value(ref: str | None, group_id) -> str | None:
    """A workspace secret named by slug (or `{{SLUG}}`); None when unnamed or unresolvable."""
    ref = (ref or "").strip()
    if ref.startswith("{{") and ref.endswith("}}"):
        ref = ref[2:-2].strip()
    if not ref:
        return None
    from marvin.services.secrets.resolver import resolve_secret

    return resolve_secret(ref, group_id)


@router.get("/hooks/{token}", summary="Answer a sender's verification request")
def verify_hook(token: str, request: Request, bg_tasks: BackgroundTasks, session: Session = Depends(generate_session)) -> Response:
    """A sender checking the URL before it delivers: a GET carrying a challenge and the verify token it was given, where
    the webhook's verification scheme says (services/webhooks/incoming_verification.py). When the token matches the
    webhook's secret, the challenge comes back and an `incoming_webhook_verified` event is recorded. Anything else is
    refused. A GET never delivers — deliveries are POSTs — so no `incoming_webhook` workflow starts on one."""
    from marvin.services.webhooks.incoming_verification import answer, is_verification, spec_for

    webhook = session.query(WorkspaceIncomingWebhookModel).filter_by(token=token).first() if token else None
    if not webhook:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook token.")
    spec = spec_for(webhook.verification_scheme, webhook.verification_config)
    params = request.query_params
    if not is_verification(spec, params):
        raise HTTPException(
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED, detail="Send deliveries as POST; a GET only answers a verification request."
        )
    if not webhook.enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This webhook is disabled.")
    challenge = answer(spec, params, _secret_value(webhook.verify_token_ref, webhook.group_id))
    if challenge is None:
        logger.warning("incoming webhook %s: verification request refused (scheme %s)", webhook.slug, webhook.verification_scheme)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verification refused.")
    logger.info("incoming webhook %s: verification request answered (scheme %s)", webhook.slug, webhook.verification_scheme)
    # What the check carried, less the verify token itself (it is the secret) and the challenge (it is noise).
    shown = {k: v for k, v in params.items() if k not in (spec.token_param, spec.challenge_param)}
    EventBusService(bg_tasks=bg_tasks, session=session).dispatch(
        integration_id="incoming_webhook",
        group_id=webhook.group_id,
        event_type=EventTypes.incoming_webhook_verified,
        document_data=EventIncomingWebhookData(
            webhook_id=webhook.id,
            webhook_slug=webhook.slug,
            webhook_name=webhook.name,
            payload=shown,
            source_ip=get_client_ip(request),
            workspace_id=webhook.group_id,
        ),
        message=f"Incoming webhook '{webhook.slug}' verified by its sender",
        entity_id=webhook.id,
        entity_type="incoming_webhook",
        reaction_depth=0,
    )
    if spec.content_type == "application/json":
        return Response(json.dumps(challenge), media_type="application/json")
    return PlainTextResponse(challenge)


@router.post("/hooks/{token}", summary="Receive an incoming webhook", status_code=status.HTTP_202_ACCEPTED)
async def receive_hook(
    token: str,
    request: Request,
    bg_tasks: BackgroundTasks,
    wait: bool = False,
    authorization: str | None = Header(default=None),
    session: Session = Depends(generate_session),
) -> dict:
    secret = _resolve_token(token, authorization)

    webhook = session.query(WorkspaceIncomingWebhookModel).filter_by(token=secret).first() if secret else None
    if not webhook:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook token.")
    if not webhook.enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This webhook is disabled.")

    # Read the body with a hard size cap, then parse JSON leniently (empty / non-JSON → {}).
    raw = await _read_capped(request)
    _check_signature(webhook, raw, request)
    payload: dict = {}
    if raw:
        try:
            parsed = json.loads(raw)
            payload = parsed if isinstance(parsed, dict) else {"_body": parsed}
        except (json.JSONDecodeError, ValueError):
            payload = {}

    source_ip = get_client_ip(request)

    # Log the payload's shape (keys only, never values) so a workflow author can see where a sender
    # puts things — e.g. whether an email is at data.email or data.subscriber.email_address.
    def _shape(obj, depth=0):
        if isinstance(obj, dict):
            return {k: _shape(v, depth + 1) if depth < 2 else type(v).__name__ for k, v in list(obj.items())[:25]}
        if isinstance(obj, list):
            return [_shape(obj[0], depth + 1)] if obj else []
        return type(obj).__name__

    logger.info("incoming webhook %s: payload shape %s", webhook.slug, json.dumps(_shape(payload)))

    # Record the delivery before dispatching so the count reflects receipt even if a subscriber fails.
    webhook.received_count = (webhook.received_count or 0) + 1
    webhook.last_received_at = datetime.now(UTC)
    session.commit()

    # A webhook an integration's blueprint created: that integration may say what the delivery holds for the Social inbox
    # (a DM, a comment, a mention). Best effort — it never fails the delivery, and the workflows below start either way.
    if webhook.source_integration_id and payload:
        from marvin.services.integrations.social_inbox import keep_webhook_items

        keep_webhook_items(session, webhook.source_integration_id, webhook.group_id, payload)

    document_data = EventIncomingWebhookData(
        webhook_id=webhook.id,
        webhook_slug=webhook.slug,
        webhook_name=webhook.name,
        payload=payload,
        source_ip=source_ip,
        workspace_id=webhook.group_id,
    )

    # wait=1 → run subscribers inline (bg_tasks=None) so the caller gets the outcome; default → 202
    # and let the event bus fan out in the background.
    bus = EventBusService(bg_tasks=None if wait else bg_tasks, session=session)
    bus.dispatch(
        integration_id="incoming_webhook",
        group_id=webhook.group_id,
        event_type=EventTypes.incoming_webhook,
        document_data=document_data,
        message=f"Incoming webhook '{webhook.slug}' received",
        entity_id=webhook.id,
        entity_type="incoming_webhook",
        reaction_depth=0,
    )

    return {"status": "processed" if wait else "accepted", "webhook": webhook.slug}
