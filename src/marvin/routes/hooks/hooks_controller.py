"""Public receiver for incoming (ingress) webhooks.

`POST /api/hooks/{token}` is the ingress endpoint. It has no login/session — the URL's secret
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
from sqlalchemy.orm import Session

from marvin.core.root_logger import get_logger
from marvin.db.db_setup import generate_session
from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel
from marvin.services.event_bus_service.event_bus_service import EventBusService
from marvin.services.event_bus_service.event_types import EventIncomingWebhookData, EventTypes
from marvin.services.security.client_info import get_client_ip
from marvin.services.webhooks.incoming_signature import DEFAULT_SIGNATURE_HEADER, verify_signature

router = APIRouter()
logger = get_logger(__name__)

# Reject bodies larger than this — an ingress endpoint should never buffer arbitrary payloads.
_MAX_BODY_BYTES = 512 * 1024


def _check_signature(webhook: WorkspaceIncomingWebhookModel, raw: bytes, request: Request) -> None:
    """When the webhook names a signing secret, the request must carry a valid HMAC — fail closed:
    an unresolvable secret, a missing header or a mismatch all reject with 401."""
    ref = (webhook.signing_secret_ref or "").strip()
    if not ref:
        return
    if ref.startswith("{{") and ref.endswith("}}"):
        ref = ref[2:-2].strip()
    from marvin.services.secrets.resolver import resolve_secret

    key = resolve_secret(ref, webhook.group_id)
    header = webhook.signature_header or DEFAULT_SIGNATURE_HEADER
    presented = request.headers.get(header)
    if not verify_signature(raw, presented, key):
        # Say what arrived without leaking it: the header's shape is enough to tell a wrong key from a
        # wrong header name or an unexpected encoding (base64 vs hex, missing prefix).
        shape = "absent" if presented is None else f"len={len(presented)} prefix={presented[:7]!r}"
        logger.warning(
            "incoming webhook %s: signature rejected (header %s %s; key %s; body %d bytes; signature headers seen: %s)",
            webhook.slug,
            header,
            shape,
            "resolved" if key else "UNRESOLVED",
            len(raw),
            [h for h in request.headers if "sign" in h.lower()],
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature.")


def _resolve_token(path_token: str, authorization: str | None) -> str:
    """The token comes from the path, or from an `Authorization: Bearer <token>` header."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return path_token


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
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Payload too large.")
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
