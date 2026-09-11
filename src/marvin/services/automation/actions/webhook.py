"""`webhook` action — fire one of the workspace's configured webhooks (from `webhook_urls`). No AI.

The workflow references a webhook by `webhook_id`; the executor loads that row and sends its
configured url / method / headers (with `{{SLUG}}` secret references resolved), with its
`custom_payload` (interpolated with `$event.*`/`$previous.*`) as the body. This reuses the webhooks
the admin already set up rather than re-entering a URL.

A raw `url` (+ optional `secret_ref`) is still accepted as an advanced escape hatch. The secret is
sent as `Authorization: <auth_scheme> <secret>`; the scheme defaults to `Bearer`, and `Token` covers
APIs like Buttondown that reject Bearer.
"""

from .base import AutomationActionError, register_action

DEFAULT_TIMEOUT = 15.0


DEFAULT_AUTH_SCHEME = "Bearer"


def _auth_header(secret_ref: str | None, group_id, scheme: str | None = None) -> dict:
    ref = (secret_ref or "").strip()
    if ref.startswith("{{") and ref.endswith("}}"):
        ref = ref[2:-2].strip()
    if not ref:
        return {}
    from marvin.services.secrets.resolver import resolve_secret

    token = resolve_secret(ref, group_id)
    scheme = (scheme or DEFAULT_AUTH_SCHEME).strip()
    return {"Authorization": f"{scheme} {token}"} if token else {}


@register_action("webhook")
def run_webhook(session, group_id, action, context, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    import httpx

    from ..authz import ROLE_OWNER, WEBHOOK_MIN_ROLE, require_role
    from ..matcher import interpolate

    require_role(ROLE_OWNER if authorizer_role is None else authorizer_role, WEBHOOK_MIN_ROLE, "webhook action")

    method = str(action.get("method") or "POST")
    headers = {"Content-Type": "application/json"}
    body = interpolate(action.get("body") or {}, context)
    url = interpolate(action.get("url"), context) if action.get("url") else None
    webhook_id = action.get("webhook_id")

    if webhook_id:
        from marvin.db.models.groups.webhooks import GroupWebhooksModel

        wh = session.get(GroupWebhooksModel, webhook_id)
        if not wh or wh.group_id != group_id:
            raise AutomationActionError("webhook not found for this workspace")
        if wh.enabled is False:
            raise AutomationActionError(f"webhook '{wh.name or webhook_id}' is disabled")
        # A stored URL may carry a `${event…}` template; the URL type percent-encodes the braces on
        # save, so restore them before interpolating (e.g. …/subscribers/${event.payload.data.subscriber}).
        url = interpolate(str(wh.url).replace("$%7B", "${").replace("%7D", "}"), context)
        method = getattr(wh.method, "value", wh.method) or "POST"
        if wh.headers_json:
            # Same treatment as event-bus delivery: `{{SLUG}}` in a header value resolves to the
            # workspace secret/variable, so `Authorization: Token {{API_KEY}}` never stores the key.
            from marvin.services.secrets.resolver import resolve_dict

            headers.update(resolve_dict(dict(wh.headers_json), group_id))
        if wh.custom_payload:
            body = interpolate(wh.custom_payload, context)

    if not url:
        raise AutomationActionError("webhook action needs a webhook_id (or a raw url)")

    method = str(method).upper()
    if dry_run:
        # Preview the request WITHOUT sending it. Never resolve the secret value into the preview —
        # just note whether an auth header would be attached.
        return {
            "dry_run": True,
            "kind": "webhook",
            "method": method,
            "url": url,
            "body": None if method == "GET" else body,
            "webhook_id": webhook_id,
            "authorized": bool(action.get("secret_ref")),
            "auth_scheme": (action.get("auth_scheme") or DEFAULT_AUTH_SCHEME) if action.get("secret_ref") else None,
        }

    headers.update(_auth_header(action.get("secret_ref"), group_id, action.get("auth_scheme")))
    try:
        resp = httpx.request(
            method,
            url,
            json=None if method == "GET" else body,
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )
    except Exception as e:
        raise AutomationActionError(f"webhook request failed: {e}") from e
    if not resp.is_success:
        # A rejected call is a failed step, not a success with a status code nobody reads.
        # The response body (trimmed) is the only clue an operator gets — keep it.
        raise AutomationActionError(f"webhook {method} {url} -> {resp.status_code}: {resp.text[:500]}")
    # Hand the response to later steps (`$steps.<id>.output.body.<field>`): parsed JSON when it is
    # JSON, else the trimmed text — a subscribe call's returned id is what a follow-up step records.
    try:
        body_out = resp.json()
    except Exception:
        body_out = (getattr(resp, "text", None) or "")[:2000]
    return {"status_code": resp.status_code, "ok": True, "webhook_id": webhook_id, "body": body_out}
