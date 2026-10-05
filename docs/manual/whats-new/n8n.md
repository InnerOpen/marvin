# n8n

Hand work from a Marvin workflow to an [n8n](https://n8n.io) workflow, hear the result back, and let n8n act on Marvin.

## What it does

`marvin-integration-n8n` is an [integration](integrations.md) provider (slug `n8n`, category destination). It works in both directions:

- **Marvin → n8n.** A workflow's **Run integration** step with **Trigger n8n workflow** (`trigger_workflow`) calls an n8n workflow's **Webhook** node. You pick the n8n workflow from a dropdown of n8n's own active workflows. The request is signed with a JWT that expires after 60 seconds, and **Get n8n execution** (`get_execution`) reads a run's status back.
- **n8n → Marvin.** n8n reports results to a Marvin [incoming webhook](incoming-webhooks.md); a workflow records them on the entry and two smart collections show what failed and what is still running. For anything else, n8n calls Marvin's API with a personal token.

n8n's own API cannot start a workflow, so only workflows that begin with a Webhook node can be triggered.

### Actions

| Action | Label | What it does |
|---|---|---|
| `trigger_workflow` | Trigger n8n workflow | `POST` (or `PUT`, `GET`) to the Webhook node's `path` with `{"marvin": {"entry_id", "meta", "idempotency_key", "sent_at"}, "data": {…}}`. Takes `path` (required; the **Workflow** dropdown), `method`, `data`, `entry_id`, `meta`, `auth` (overrides the connection's default) and `secret` (`{{N8N_WEBHOOK_SECRET}}`, required unless auth is `none`). Returns `ok`, `status_code`, `path`, `response` (n8n's reply), and `execution_id` / `execution_url` when the reply names them. Never headers, the token or the secret |
| `list_workflows` | List n8n workflows | Active workflows (or `active: false`) with their Webhook nodes. Needs the API key |
| `list_webhooks` | List n8n webhooks | One item per Webhook path and method, labelled "<workflow> — POST /<path>"; this feeds the **Workflow** dropdown. Needs the API key |
| `get_execution` | Get n8n execution | `execution_id` → `status`, `workflow_id`, `started_at`, `stopped_at`, `retry_of`, `url` and, with `include_error` (default on), `last_node_executed` and an `error_message` cut to 300 characters. Nothing else from the execution is copied into Marvin. Needs the API key |

**Auth.** `jwt` (the default) sends `Authorization: Bearer <HS256 JWT>` with `aud` set to the path, a 60-second `exp`, the idempotency key as `jti` and a `body_sha256` of the bytes sent; n8n's **JWT Auth** credential checks it. `header` sends the secret in `X-Marvin-Hook` (or the connection's **Auth header**) for existing Header Auth setups; `hmac` sends `X-Marvin-Signature: t=<ts>,v1=<hex>`, which you verify in n8n yourself; `none` sends nothing. JWT is the default because n8n keeps webhook request headers in its execution data, where an expired token is useless to anyone who reads it.

**Retries and duplicates.** `X-Marvin-Idempotency-Key` stays the same across every retry of one run for the same path and entry, so the n8n workflow can drop a request it has already handled.

### Errors

Every failure has a code, and the provider's [error policy](integrations.md#when-an-integration-fails) decides what Marvin does with it for `trigger_workflow`:

| Code | When | What happens |
|---|---|---|
| `auth` | n8n answered 401/403 | Alert admins, wait for the connection to recover, retry up to 3×, then send to review |
| `not_found` | 404: no active workflow has that path and method | Alert admins, retry after 5 and 30 minutes, then send to review |
| `rate_limited` | 429 (n8n's `Retry-After` is honoured) | Retry 3× (30 s, 2 min, 10 min), then alert and send to review |
| `unavailable` | Couldn't connect, 502/503/504, or another 5xx that isn't n8n's own | Retry 4× (1 min, 5 min, 30 min, 2 h), then alert and send to review |
| `timeout` | Sent, but no reply in time; n8n may have run it | Send to review. **No retry**, so it can't run twice |
| `workflow_error` | 500 with n8n's `{"message": …}`: the workflow ran and failed | Send to review (n8n's own error workflow already alerts) |
| `rejected` | Another 4xx: a Respond to Webhook node said no | Send to review |
| `blocked` | Marvin refused the host (private or in-cluster address) | Alert admins |
| `invalid` | A bad path, a missing secret, a test webhook that isn't allowed | Alert admins |
| `response_too_large` | n8n's reply was bigger than `INTEGRATION_HTTP_MAX_BYTES`; the request landed | Carry on as a success |
| anything else | | Alert admins and send to review |

The read actions (`list_workflows`, `list_webhooks`, `get_execution`) just fail, since you see the error straight away. To be told about `workflow_error` too, tick its **Alert** box in the card's **How errors are handled** table. A workflow's own on-failure steps still read the code as `${error.code}`.

### Content

Applied from the card's **Content** section; nothing is required and nothing is created on install. The webhook and the workflow arrive switched off.

| Kind | Slug | What it does |
|---|---|---|
| Incoming webhook | `n8n` | Where n8n reports results. Scheme `static_token`, header `X-Marvin-Token`, secret `N8N_CALLBACK_TOKEN` |
| Workflow | `n8n-record-result` | On the `n8n` webhook, when the payload has `marvin.entry_id`: writes `n8n_status` (`success`, `error`, `waiting`), `n8n_execution_id`, `n8n_workflow`, `n8n_finished_at` and `n8n_message` into that entry's metadata |
| Collection (optional) | `n8n-failed` | **n8n: failed**: smart, private, `metadata.n8n_status` is `error` |
| Collection (optional) | `n8n-in-flight` | **n8n: in flight**: smart, private, `metadata.n8n_status` is `sent` or `waiting` |

Both collections are private (**Visible to sites** off), so a result never queues a site rebuild. Nothing writes `sent` on its own: to track sends, follow the trigger step with a `set_metadata` step that sets `n8n_status: sent`.

## Where

- **Settings → Integrations** (`/workspace/settings/integrations`, admins): connect n8n, apply its content, run **Get n8n execution**, adjust **How errors are handled**.
- **Automation → Workflows**: the **Run integration** step, with the **Workflow** dropdown.
- **Automation → Incoming Webhooks**: the `n8n` webhook's URL and token.
- **Settings → General → Environment**: the `N8N_WEBHOOK_SECRET` and `N8N_CALLBACK_TOKEN` secrets.
- **Profile → Manage Tokens**, signed in as the n8n user: its personal token.

## How to use

### Connect n8n

1. Install `marvin-integration-n8n` with the SDK (see [Install a provider](integrations.md#install-a-provider)).
2. In n8n, **Settings → n8n API → Create an API key**, with only `workflow:read` and `execution:read` where your n8n offers scopes. Save it in Marvin as the secret `N8N_API_KEY`.
3. Under **Settings → Integrations**, configure **n8n**: name it (the name becomes the connection's slug: "n8n" is `n8n`), set **n8n URL** to n8n's public address (`https://n8n.example.com`) and the credential to `{{N8N_API_KEY}}`. The health check lists one workflow with the key, or calls `/healthz` without one.

### Marvin → n8n: trigger a workflow

1. In n8n, create a **JWT Auth** credential: Key Type **Passphrase**, Algorithm **HS256**, a long random passphrase (at least 32 random bytes).
2. In Marvin, save the same passphrase as the secret `N8N_WEBHOOK_SECRET`.
3. In the n8n workflow, set the Webhook node's **Authentication** to **JWT Auth** with that credential, set **Respond** to **Using 'Respond to Webhook' Node**, and activate the workflow. Answer straight away with a **Respond to Webhook** node (JSON `{{ { executionId: $execution.id, workflowId: $workflow.id } }}`) and do the slow work after it: the step waits at most the connection's **Timeout** (15 s by default), and the reply gives Marvin the run's `execution_id` and `execution_url`.
4. In a Marvin workflow, add a **Run integration** step: your n8n connection, **Trigger n8n workflow**, the n8n workflow under **Workflow**, and in the arguments `"secret": "{{N8N_WEBHOOK_SECRET}}"`, `"entry_id": "${entry.id}"` (so n8n can report back) and the `data` to send. Pick the matching **method** too: the dropdown fills only the path, and a Webhook node registered for `POST` answers 404 to a `GET`. The stored step keeps the `{{…}}` reference; a dry run shows the reference, never the value.

The n8n workflow reads the data at `{{ $('Webhook').item.json.body.data }}` and the entry at `{{ $('Webhook').item.json.body.marvin.entry_id }}`. To drop a retried request that already ran, add a **Remove Duplicates** node (*Remove Items Processed in Previous Executions*) on `{{ $json.headers['x-marvin-idempotency-key'] }}`.

### Check a run

On the n8n card, press **Get n8n execution** and give it an `execution_id` from a trigger step's output (**Runs** shows it). Or add a later step to the same workflow with `"execution_id": "$steps.<trigger step id>.output.execution_id"`. The result is the run's status and timing, a link to it in n8n (the connection's **Editor URL**, else the n8n URL), and, if it failed, the last node and a short error message.

### n8n → Marvin: report results

1. On the n8n card, apply the `n8n` incoming webhook and `n8n-record-result` (and the collections if you want them). Save a random value as the secret `N8N_CALLBACK_TOKEN`. Under **Incoming Webhooks**, press **Create token** on the `n8n` webhook, then switch the webhook and `n8n-record-result` on.
2. In n8n, create a **Header Auth** credential: Name `X-Marvin-Token`, Value the same random value.
3. End the n8n workflow with an **HTTP Request** node: `POST` to the webhook's URL (`https://<marvin>/api/hooks/<token>`), that credential, and a JSON body:

    ```json
    {
      "marvin": {"entry_id": "{{ $('Webhook').item.json.body.marvin.entry_id }}"},
      "status": "success",
      "execution_id": "{{ $execution.id }}",
      "workflow": "{{ $workflow.name }}",
      "finished_at": "{{ $now.toISO() }}",
      "message": ""
    }
    ```

4. For failures, set the risky node's **On Error** to *Continue (using error output)* and send its error branch to a second HTTP Request node with `"status": "error"` and `"message": "{{ $json.error.message }}"`. Before a Wait node, report `"status": "waiting"`.

The entry then shows in **n8n: failed** or **n8n: in flight** on its own. Any other Marvin workflow can also use the `n8n` webhook as its trigger to react to a result.

### n8n → Marvin: call Marvin's API

Create **one Marvin user per workspace** for n8n (for example `n8n`) and a [personal token](../auth-and-tokens.md#personal-api-tokens-marvin_tk_) for it. A personal token acts as its user, in that user's **active** workspace (the one it last switched to in the admin), and has no workspace selector, which is why each workspace needs its own n8n user. Give the user the lowest [role](../auth-and-tokens.md#roles) that does the job, usually EDITOR: an AUTHOR can only create entries that aren't approved or published and change its own, while an EDITOR also publishes, edits any entry and has the AI write tools. In n8n, put the token in a **Header Auth** credential (Name `Authorization`, Value `Bearer marvin_tk_…`) and use HTTP Request nodes against:

- `POST /api/platform/entries`: create an entry.
- `POST /api/ai/operations/{slug}/execute`: run an AI operation.
- `POST /api/ai/agents/{slug}/run`: run an agent.

To start a Marvin workflow with data, POST to one of its incoming webhooks instead: `POST /api/automations/{id}/run` needs a workspace admin and takes no input. The personal token replaces logging in on every run and reusing the 48-hour session JWT.

### Worked example: ping-pong

A manual Marvin workflow pings n8n, n8n answers on the `n8n` incoming webhook, and a second Marvin workflow reads the n8n run back. It assumes an n8n connection with the slug `n8n` and an API key, the secrets `N8N_WEBHOOK_SECRET` and `N8N_CALLBACK_TOKEN`, and the `n8n` incoming webhook switched on with a token (steps above).

**1. Marvin: `n8n-ping`.** Create it under **Automation → Workflows** (**Edit as JSON**), or with `POST /api/automations`:

```json
{
  "name": "n8n ping",
  "slug": "n8n-ping",
  "enabled": true,
  "definition": {
    "trigger": {"type": "manual"},
    "actions": [
      {
        "kind": "integration",
        "id": "ping",
        "integration": "n8n",
        "action": "trigger_workflow",
        "args": {
          "path": "marvin/ping",
          "method": "POST",
          "secret": "{{N8N_WEBHOOK_SECRET}}",
          "data": {"message": "ping"}
        }
      }
    ]
  }
}
```

`integration` is your connection's slug, not the provider's. In the step editor, `path` is the **Workflow** dropdown; pick the n8n workflow once it is active.

**2. n8n: "ping → pong".** Three nodes:

1. **Webhook**: HTTP Method `POST`, Path `marvin/ping`, Authentication **JWT Auth** (the credential holding the `N8N_WEBHOOK_SECRET` passphrase), Respond **Using 'Respond to Webhook' Node**.
2. **Respond to Webhook**: Respond With **JSON**, body `{{ { executionId: $execution.id, workflowId: $workflow.id } }}`.
3. **HTTP Request**: Method `POST`, URL `https://<marvin>/api/hooks/<n8n webhook token>`, Authentication the `X-Marvin-Token` Header Auth credential, Send Body **JSON**:

    ```json
    {
      "pong": "{{ $('Webhook').item.json.body.data.message }}",
      "execution_id": "{{ $execution.id }}",
      "workflow": "{{ $workflow.name }}"
    }
    ```

Activate it.

**3. Marvin: `n8n-pong-received`.**

```json
{
  "name": "n8n pong received",
  "slug": "n8n-pong-received",
  "enabled": true,
  "definition": {
    "trigger": {"type": "incoming_webhook", "webhook": "n8n"},
    "conditions": [{"field": "event.payload.pong", "op": "eq", "value": "ping"}],
    "actions": [
      {
        "kind": "integration",
        "id": "check",
        "integration": "n8n",
        "action": "get_execution",
        "args": {"execution_id": "${event.payload.execution_id}"}
      }
    ]
  }
}
```

**4. Run it.** Press **Run** on `n8n-ping`. Its **Runs** entry shows the trigger step's output: `status_code` 200, the `response` from Respond to Webhook, and the `execution_id` and `execution_url`. A moment later `n8n-pong-received` runs; its `check` step's output is that execution's `status` (`running` or `success`, depending on whether n8n has finished when Marvin asks) and its link in n8n. `n8n-record-result` ignores the pong, since it carries no `marvin.entry_id`.

To try the error handling, deactivate "ping → pong" and run `n8n-ping` again: the step fails with `not_found`, the n8n card shows **Needs attention**, and Marvin retries after 5 and 30 minutes. A manual run has no entry to send to review, so the alert is what tells you. Reactivate the workflow and press **Resolve** (or let the next retry succeed).

## Settings

The connection's fields (**Configure integration** on the card):

| Field | Default | Effect |
|---|---|---|
| **n8n URL** (`base_url`) | required | Where Marvin reaches n8n, for webhooks and the API. Must be public: private, loopback and in-cluster addresses are refused |
| **n8n API key** (credential) | none | Enables the workflow picker, `list_workflows`, `list_webhooks` and `get_execution`. Best as `{{N8N_API_KEY}}` |
| **Editor URL** (`editor_url`) | the n8n URL | The address people open n8n at, for execution links |
| **Webhook prefix** (`webhook_prefix`) | `webhook` | n8n's production webhook path (`N8N_ENDPOINT_WEBHOOK`) |
| **Default auth** (`default_auth`) | `jwt` | `jwt`, `header`, `hmac` or `none`; a step's `auth` overrides it |
| **Auth header** (`auth_header`) | `X-Marvin-Hook` | The header that carries the secret in `header` mode |
| **Timeout** (`timeout_seconds`) | `15` | How long a trigger waits for n8n's reply, at most 30 |
| **Allow test webhooks** (`allow_test_webhooks`) | off | Lets a step with `test: true` call `/webhook-test/<path>`, which answers only while the n8n editor is listening |

Running an integration step stays an ADMIN action: a workflow's steps run with its author's role.

## Since

The n8n provider is a separate package, `marvin-integration-n8n` 0.1.0 (2026-10-04), built on `marvin-integration-sdk` 0.5. The **Workflow** dropdown, its error policy, **Needs attention** and the per-connection **Review** / **Alert** boxes need Marvin rc.197; on an older Marvin the path is free text and failures only reach a workflow's on-failure steps as `${error.code}`.

## Related

- [Integrations](integrations.md): installing providers, error policies, alerts and the option picker.
- [Workflows](workflows.md): the **Run integration** step, templates and on-failure steps.
- [Incoming webhooks](incoming-webhooks.md): tokens and the `static_token` scheme.
- [Auth and tokens](../auth-and-tokens.md): personal tokens and roles.
- Package [README](https://github.com/InnerOpen/marvin-integration-n8n#readme): every action, code and policy entry.
