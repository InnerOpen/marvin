# Outgoing webhooks

An outgoing webhook is a saved HTTP call — URL, method, headers and payload — that Marvin sends on a schedule, when a subscribed event occurs, or when a workflow step calls it.

## What it does

The `webhook_type` (mode) decides when it fires and what it sends:

| Mode | Fires | Payload |
|---|---|---|
| `generic` | On `scheduled_time` | Your custom payload as-is. |
| `user` | On `scheduled_time` | Workspace member statistics plus your custom payload. |
| `entries` | On `scheduled_time` | Content entry statistics (totals, published, draft, new since last run) plus your custom payload. |
| `event_driven` | Immediately when one of `subscribed_events` occurs | The serialized event; connect events from the Events page after creating. |
| `workflow` | Never on its own; only a workflow's "Call webhook" step sends it | URL, method, headers and payload live on the webhook; `${event…}` and `{{SECRET}}` templates resolve at send time. |

- `generic`, `user` and `entries` require a `scheduled_time` (`422` otherwise); `event_driven` and `workflow` do not.
- The event bus delivers only to webhooks that are enabled, of type `event_driven`, and whose `subscribed_events` contains the event name. A `workflow` webhook is never selected by the bus.
- **Headers**: any value may reference a workspace secret as `{{SLUG}}`; it is resolved at send time so the key is never stored on the webhook.
- **Custom payload**: every string value may use `{{trigger}}`, `{{timestamp}}`, `{{workspace_name}}`, `{{workspace_slug}}` and workspace Variables. Secrets are not substituted here. For event-driven sends the custom payload is attached as `meta` beside the serialized event (`eventType` is the event name); scheduled sends post `timestamp`, `workspaceId`, `workspaceName`, `workspaceSlug`, `webhookType`, optional `documentData` (statistics) and `meta`.
- **Delivery and retries** (event bus and scheduled sends): 15 s timeout, up to 3 attempts with exponential backoff (2^attempt seconds, capped at 60). Each attempt writes a `webhook_execution_logs` row with status `success`, `retrying` or `failed`, the HTTP status, `retry_attempt`, the request payload (POST/PUT) and the response body on failure.
- **Workflow-step deliveries** go through the workflow's `webhook` action: one request, 15 s timeout, no retries; a non-2xx response fails the step. The step logs a `success` or `failed` row with the request payload and the response body trimmed to 2000 characters, so the delivery log answers "did it fire?" for workflow calls too. The response body is also handed to later steps as `$steps.<id>.output.body`.

## Where

| Surface | Path |
|---|---|
| Webhook list | `/automation/webhooks` |
| Create / edit (mode picker, custom payload, custom headers) | `/automation/webhooks/new`, `/automation/webhooks/{id}` |
| Delivery log, filter by All / Success / Failed / Retrying | `/automation/webhooks/log` |
| Subscribe an event-driven webhook to events | `/automation/events` |

The log table shows executed-at, webhook, method, status, HTTP code and attempt number, with an expandable row for the error, the payload sent and the response body.

## How to use

1. Create a webhook: name, URL, method (`GET` or `POST`), mode. Add headers such as `Authorization: Bearer {{NEWSLETTER_API_KEY}}` after saving the key as a [workspace secret](../auth-and-tokens.md#secrets-and-variables).
2. For `event_driven`, open the Events page and connect the events it should receive. For scheduled modes, set `scheduled_time`.
3. For `workflow`, add a "Call webhook" step in a workflow and pick this webhook (see [Workflows](workflows.md)). The stored URL may include a template, e.g. `https://api.example.com/subscribers/${event.payload.data.subscriber}`.
4. Use **Test** to send a test request in the background, then check the delivery log.

```json
{
  "name": "Newsletter subscribe",
  "url": "https://api.newsletter.example/v1/subscribers",
  "method": "POST",
  "webhookType": "workflow",
  "headers": {"Authorization": "Bearer {{NEWSLETTER_API_KEY}}"},
  "customPayload": {"email": "${event.submission_data.email}"}
}
```

## API

Routes are scoped to the caller's workspace. See [API reference](../api/index.md).

| Method and path | Purpose |
|---|---|
| `GET /api/groups/webhooks` | Paginated list. |
| `POST /api/groups/webhooks` | Create (`name`, `url`, `method`, `webhookType`, `scheduledTime?`, `headers?`, `subscribedEvents?`, `customPayload?`, `enabled`). |
| `GET /api/groups/webhooks/types` | Modes with descriptions. |
| `GET` / `PUT` / `DELETE /api/groups/webhooks/{id}` | Read, replace, delete. |
| `GET /api/groups/webhooks/{id}/test` | `202`; sends a test in the background. `400` when the webhook is disabled. |
| `GET /api/groups/webhooks/{id}/logs?limit=50` | Delivery log for one webhook. |
| `GET /api/groups/webhooks/log?limit=100` | Delivery log for the workspace. |
| `GET /api/groups/webhooks/rerun` | Re-run today's scheduled webhooks. |

Log rows (`WebhookExecutionLogRead`): `webhookId`, `executedAt`, `status`, `httpStatusCode`, `errorMessage`, `retryAttempt`, `requestPayload`, `responseBody`.

## Settings

| Field | Default | Notes |
|---|---|---|
| `enabled` | `true` on create | A disabled webhook is skipped by the bus and fails a workflow step that calls it. |
| `method` | `POST` | `GET` sends no body. |
| `webhookType` | `generic` | See the mode table. |
| `scheduledTime` | none | Required unless the mode is `event_driven` or `workflow`. |
| `headers` | none | `{{SLUG}}` secret refs allowed. |
| `customPayload` | none | JSON object; `{{var}}` substitution for variables and per-fire context, `${event…}` when called from a workflow. |

## Since

The `workflow` mode and delivery-log rows for workflow steps: v1.0.0-rc.63 (`680997a7`).

## Related

- [Workflows](workflows.md) — the `webhook` step.
- [Incoming webhooks](incoming-webhooks.md) — receiving instead of sending.
- [Forms and submission protection](forms-and-submission-protection.md) — a common source event.
- [Glossary](../glossary.md)
