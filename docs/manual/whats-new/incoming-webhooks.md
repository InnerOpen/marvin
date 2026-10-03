# Incoming webhooks

An incoming webhook is a tokened URL that any external system can POST to; Marvin turns the request into an `incoming_webhook` event that your workflows react to.

## What it does

- Each webhook has a `slug`, an `enabled` flag and a secret `token` minted by an admin. Requests are accepted only when the webhook is enabled **and** a token exists (deny by default). Rotating the token invalidates the old URL; revoking it rejects everything.
- A valid request fires one `incoming_webhook` event carrying `webhook_id`, `webhook_slug`, `webhook_name`, `payload` (the JSON body), `source_ip` and `workspace_id`. Subscribers run in the background and the receiver answers `202` at once.
- The body is parsed leniently: a JSON object is the payload as-is, any other JSON value is wrapped as `{"_body": …}`, and an empty or non-JSON body becomes `{}`. Bodies over 512 KB are rejected with `413`.
- `received_count` and `last_received_at` are updated before dispatch, so the card reflects receipt even if a subscriber fails.
- Optional **signature verification**: when `signing_secret_ref` names a workspace secret, every request must carry a valid HMAC signature made with that secret, built the way the webhook's **signature scheme** says, or, for a token scheme, the secret itself in a header. Comparison is constant-time and verification fails closed: a missing header, a mismatch, an unresolvable secret, a stale timestamp or a scheme that no longer exists all return `401`. See [Signature schemes](#signature-schemes).
- Logging never records payload values. On receipt the log holds the payload's key structure only (nested two levels, at most 25 keys per object) so you can see where a sender puts a field. A rejected signature logs the scheme, the header's length and prefix and whether the key resolved, never the value; a rejected static token logs its length only, since the token is the secret.

## Where

`/automation/incoming-webhooks` (**Incoming Webhooks**). **New webhook** opens the create form. Each card shows the URL with **Copy**, **Send test**, **Rotate** and **Revoke** (or **Create token** while none exists), an enable switch, **Delete**, the signing setup (**Set up signing** / **Change**: secret slug, header (blank uses the scheme's own), scheme picker, signed URL, **Save**, **Generate key**, and a hint that describes what the picked scheme expects from the sender) and a **verified** pill when verification is on.

## How to use

1. Press **New webhook**, give it a name (the slug is derived) and **Create**, then **Create token**. Copy the URL `https://<host>/api/hooks/<token>`.
2. Optional: press **Set up signing**, pick the scheme the sender uses, and give the key. Either type the slug of a workspace secret that already holds the sender's key, or press **Generate key**: Marvin creates a workspace secret (slug from the secret field, or `<WEBHOOK_SLUG>_SIGNING_KEY`), sets `signing_secret_ref` and shows the key **once** so you can paste it into the sender. Press **Save** to store the scheme (and the signed URL, if the scheme needs one).
3. Enable the webhook and paste the URL into the sender.
4. **Send test** POSTs your own JSON to the URL with `?wait=1`, so subscribers run inline and the outcome comes back. The test request is unsigned, so it gets `401` while signing is on.
5. Build a workflow with trigger `incoming_webhook` (see [Workflows](workflows.md)) and read the body through `$event.payload.*`.

```json
{
  "trigger": {"type": "incoming_webhook", "webhook": "newsletter"},
  "conditions": [{"field": "event.payload.event_type", "op": "eq", "value": "subscriber.confirmed"}],
  "actions": [
    {"kind": "entry", "op": "set_metadata",
     "entity_query": {"metadata": {"subscriber_id": "$event.payload.data.subscriber"}},
     "metadata": {"confirmed_at": "${event.payload.timestamp}"}}
  ]
}
```

!!! note
    An incoming-webhook trigger has no entry in its context. A condition on `entry.*` never matches, and an `entry` or `operation` step needs `entity_slug`, `entity_query` or a `target` selector; the validator warns about both.

Signing a request from the sender side with the default `hmac_sha256_hex` scheme:

```bash
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$KEY" | sed 's/^.* //')
curl -X POST "https://<host>/api/hooks/<token>" \
  -H "Content-Type: application/json" -H "X-Signature-256: sha256=$SIG" -d "$BODY"
```

### Signature schemes

Senders sign the same way with different details: the HMAC algorithm, what is signed, how the digest is encoded, which header carries it, and sometimes a timestamp against replays. A webhook's `signature_scheme` names that construction; unset means `hmac_sha256_hex`. The picker lists, in order:

| Scheme | Source | Signature |
|---|---|---|
| `hmac_sha256_hex` (default) | core | `sha256=<hex HMAC-SHA256 of the raw body>` in `X-Signature-256`; the prefix is optional, hex is case-insensitive (GitHub, Buttondown and most others) |
| `shopify` | core | base64 HMAC-SHA256 of the body in `X-Shopify-Hmac-Sha256` |
| `slack` | core | `v0=<hex>` of `v0:{timestamp}:{body}` in `X-Slack-Signature`; timestamp from `X-Slack-Request-Timestamp`, 300 s tolerance |
| `stripe` | core | `Stripe-Signature: t=<ts>,v1=<hex>` of `{t}.{body}`; 300 s tolerance |
| `standard_webhooks` | core | `webhook-signature: v1,<base64>` of `{webhook-id}.{webhook-timestamp}.{body}`, base64 key (a `whsec_` prefix is dropped), several space-separated signatures allowed, 300 s tolerance (Svix, Resend, Clerk, …) |
| *integration presets* | an installed integration | Shown as `<name> (from <provider>)`. An integration declares them as `signature_schemes`, HMAC or token; a name core already uses is ignored. If the integration is uninstalled, verification fails closed. |
| `static_token` | core | Not a signature: the sender puts the shared secret itself in a header, compared in constant time. Default header `X-Webhook-Token`; set the webhook's header to what the sender uses (for example `cf-webhook-auth` for Cloudflare notifications, `X-Gitlab-Token` for GitLab) |
| `custom` | core | You describe the construction in `signature_config` (JSON). |

A `custom` config takes `mode` (`hmac`, the default, or `token`, which needs only `header` and an optional `prefix` to strip), and for HMAC `algorithm` (`sha1`, `sha256`, `sha512`), `encoding` (`hex`, `base64`), `message`, `header`, and optionally `prefix`, `multiple`, `header_format` (`plain`, or `stripe` for `t=…,v1=…`), `key_format` (`raw`, `base64`), `timestamp_header` and `tolerance_seconds`. `message` is a template over the raw request and must include `{body}`: `{body}` (the exact bytes received), `{url}`, `{header:Name}` and `{t}` (the timestamp from a `stripe`-format header). Saving an unknown scheme or an invalid custom config returns `422`.

```json
{"algorithm": "sha256", "encoding": "base64", "message": "{url}{body}", "header": "X-Signature"}
```

A scheme that signs `{url}` needs `signature_url`: the exact public URL you gave the sender. Behind a proxy or tunnel the backend sees a different URL, so it is not derived from the request. A non-empty `signature_header` overrides the scheme's header.

## API

Receiver (no session; the token is the credential):

| Method and path | Result |
|---|---|
| `POST /api/hooks/{token}` | `202 {"status": "accepted", "webhook": "<slug>"}`. The token may instead be sent as `Authorization: Bearer <token>`, in which case the path segment is ignored. |
| `POST /api/hooks/{token}?wait=1` | Runs subscribers inline; `202 {"status": "processed", …}`. |
| Errors | `401` unknown token or bad signature · `403` webhook disabled · `413` body over 512 KB |

Management (workspace ADMIN or OWNER):

| Method and path | Purpose |
|---|---|
| `GET` / `POST /api/incoming-webhooks` | List; create (`name`, `slug?`, `description?`, `enabled`, `signingSecretRef?`, `signatureHeader?`, `signatureScheme?`, `signatureUrl?`, `signatureConfig?`). `409` on a duplicate slug, `422` on an unusable scheme. |
| `GET /api/incoming-webhooks/signature-schemes` | Every scheme a webhook can pick: `name`, `notes`, `source` (`core` or the providing integration). |
| `GET` / `PATCH` / `DELETE /api/incoming-webhooks/{id}` | Read, update, delete. |
| `POST /api/incoming-webhooks/{id}/token` | Mint or rotate the token. |
| `DELETE /api/incoming-webhooks/{id}/token` | Revoke the token. |

`IncomingWebhookRead` includes `token` (admin-only surface), `receivedCount` and `lastReceivedAt`. See [API reference](../api/index.md).

## Settings

| Field | Default | Notes |
|---|---|---|
| `enabled` | `false` (API); the create form's switch starts on | Requests are refused with `403` while off. |
| `token` | none | Null until minted; unique per platform. |
| `signing_secret_ref` | none | Slug of a workspace secret (with or without `{{ }}`). Blank turns verification off. |
| `signature_scheme` | `hmac_sha256_hex` | Core preset, integration preset, or `custom`. |
| `signature_header` | the scheme's header | Overrides where the signature arrives. |
| `signature_url` | none | Only for schemes whose message includes `{url}`. |
| `signature_config` | none | The construction, for `custom` only. |

## Since

Incoming webhooks with HMAC verification: v1.0.0-rc.55 (`a2754652`). Generated signing keys and card editing: rc.56 (`d5bbc5d7`, `ccbf5caa`). Signature-rejection logging: rc.57 (`41f9f98a`). Payload key-structure logging: rc.58 (`4223e107`). Signature schemes (core presets, integration presets, `custom`): rc.111 and rc.113. `static_token` and token-mode schemes: rc.144.

## Related

- [Workflows](workflows.md) — the `incoming_webhook` trigger and `$event.payload.*`.
- [Outgoing webhooks](outgoing-webhooks.md) — the other direction.
- [Blueprints](blueprints.md) — an integration can declare an incoming webhook; applying it creates the webhook switched off and without a token.
- [Glossary](../glossary.md)
