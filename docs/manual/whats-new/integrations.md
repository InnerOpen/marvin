# Integrations

Connect a workspace to an external service through an installable provider package, then run its actions by hand, from a workflow, on a schedule, or whenever an event fires.

## What it does

An **integration** is a credentialed connection from one workspace to one external service. The code that knows how to talk to that service is a **provider**, and providers are not part of Marvin core: each one is a separate Python package that registers itself through the `marvin.integrations` entry-point group. Core ships no providers. With no provider installed the SDK is absent, `INTEGRATIONS_AVAILABLE` is `False`, and the whole integrations surface stays dormant (the API returns 404 and the Integrations page says so).

On startup `src/marvin/services/integrations/loader.py` reads every entry point in the group, imports it and registers its provider. A package that fails to import is logged and skipped; it never blocks the others or crashes startup. Its load report (distribution, version, error) is what the **Installed plugins** panel shows.

**Plugins and integrations.** A *plugin* is the package the platform operator installs; an *integration* is one workspace's connection to a provider that a plugin registers. Platform super admins see every installed plugin under **Admin → Extensions → Plugins** (`/admin/plugins`): its package, version and kind (the only kind today is **Integration**), whether it loaded and, if not, why, and for each provider it registers the number of actions, blueprints and workspaces that have connected it. The page is read-only: installing a plugin runs its code, so it stays with whoever builds the image or the Helm init container (see [Install a provider](#install-a-provider)).

A provider is a manifest plus handlers, defined against `marvin_integration_sdk` (`src/marvin_integration_sdk/base.py`):

- `slug`, `name`, `description`, `category` (`source`, `destination`, `capability`, `notify`), an optional emoji `icon` and, from SDK 0.6.0, an optional official `logo` (see [Logos](#logos));
- `credentials` (the core stores one credential per integration, in the secret backend, and never reads it back), and a JSON-schema `config_schema` for non-secret settings;
- `actions`, each with a key, label, description, `input_schema` and optional capability, approval and cost metadata; `emits`, the events it can raise. An input can name the read action that lists its valid values (see [Pick a value from the service](#pick-a-value-from-the-service));
- `content`, the [blueprints](blueprints.md) it declares, and `signature_schemes`, presets it adds to [incoming webhook](incoming-webhooks.md#signature-schemes) verification;
- a `check(ctx)` health probe returning `(status, error)`, and `run_action(key, args, ctx)`.

The provider receives only `config`, the resolved `secret`, a logger and an HTTP helper. It never touches the database or the event bus; core owns persistence and dispatch. The HTTP helper offers `get`, `post`, `put`, `patch` and `delete`; it refuses private, loopback, link-local and reserved hosts (re-checked on every redirect), sends a `marvin-cms/integrations` User-Agent, defaults to a 15 s timeout, and refuses a response larger than `INTEGRATION_HTTP_MAX_BYTES` (default 5,000,000 bytes). See the SDK README at `https://github.com/InnerOpen/marvin-integration-sdk`.

Providers published so far, all under `https://github.com/InnerOpen/marvin-integration-*`:

| Package | Slug | Category | Actions |
| --- | --- | --- | --- |
| `marvin-integration-slack` | `slack` | notify | `send_message`; declares an "Announce published entries" event subscription |
| `marvin-integration-apprise` | `apprise` | notify | `notify` (capability `notify`) |
| `marvin-integration-openai-images` | `openai_images` | capability | `generate` (capability `image.generate`) |
| `marvin-integration-instagram` | `instagram` | destination | `list_recent_comments`, `send_private_reply` (DM a comment's author), `auto_reply` (keyword rules, dry-run by default), `refresh_token`; declares its own entry types, collections and scheduled tasks |
| `marvin-integration-square` | `square` | destination | `list_locations`, `create_listing`, `close_listing` (sell one-of-a-kind items through a Square checkout link); declares fields on an item type, an incoming webhook with its own `square` signature scheme, and workflows |
| `marvin-integration-cloudflare-pages` | `cloudflare_pages` | destination | `list_deployments`, `build_log` (the likely failure line from a deployment's build log), `connect_notifications` (sets up Cloudflare's deploy notifications to post to Marvin), `deploy`; contributes a `cloudflare` token signature scheme and declares an incoming webhook plus workflows that turn deploy started / succeeded / failed notifications into site deployment events, with the build-log reason on failure |
| `marvin-integration-buttondown` | `buttondown` | destination | `subscribe`, `lookup_subscriber`, `create_issue_email`, `connect_webhooks` (**Connect Buttondown webhooks**); contributes a `buttondown` signature scheme and declares an incoming webhook plus workflows that run a site's newsletter through Buttondown (see [Newsletter with Buttondown](#newsletter-with-buttondown)) |
| `marvin-integration-template` | `example` | destination | `ping`; the starting point for a new provider |

### Event notifications (Apprise)

Notifications to Slack, Discord, Telegram, email and 100+ other services go through the `apprise` integration. Install `marvin-integration-apprise`, add an **Apprise Notifications** integration under Settings → Integrations with one or more Apprise URLs (`slack://…`, `discord://…`; newline- or comma-separated) as its credential, then connect its `notify` action to an event at `/automation/events/[type]` or call it from a workflow step. The `title` and `body` args take `{{placeholders}}` filled from the event: `{{event_type}}` and any field of its data (for example `{{entry_title}}`).

Marvin core no longer ships its own Apprise notifier: the Automation → Notifications pages, the `/api/group/notifications` routes, the `/api/event/options` catalog and the `APPRISE_ENABLED` / `APPRISE_URL` settings are gone, and migration `b3f7c2e9d1a4` drops their tables. Any notifiers that existed were copied onto `apprise` integrations by migration `e49ab4346b7b`.

## Where

- **Settings → Integrations**: `/workspace/settings/integrations`.
- **Per-event wiring**: `/automation/events/[type]`, "Integrations" section.
- **Workflows**: the **Run integration** step (`kind: "integration"`); see [Workflows](workflows.md).
- **Scheduled runs**: a "Run Integration Action" scheduled task (`run_integration_action`).
- **Install**: the backend image, or an init container in the Helm chart.
- **Installed plugins, platform-wide**: **Admin → Extensions → Plugins** (`/admin/plugins`), super admins only.

## How to use

### Install a provider

Installing a provider is a `pip install` into the backend's Python environment plus a restart; there is no upload or marketplace. Either bake it into a derived image, or install it at pod start into a shared volume that is put on `PYTHONPATH`:

```yaml
initContainers:
  - name: install-integrations
    image: python:3.12-slim
    command: ["sh", "-c"]
    args:
      - pip install --target=/plugins https://github.com/InnerOpen/marvin-integration-sdk/archive/refs/heads/develop.tar.gz https://github.com/InnerOpen/marvin-integration-slack/archive/refs/heads/main.tar.gz
```

The SDK tarball on the same line satisfies each plugin's `marvin-integration-sdk` dependency. The volume, mount and `PYTHONPATH` wiring are in the worked example in [`marvin-chart/README.md`](https://github.com/InnerOpen/marvin/blob/develop/marvin-chart/README.md#integration-plugins). Uninstall a package and its integrations show as **unavailable** rather than pretending to work; you can still rename, disable or delete them.

### Connect one

1. On the Integrations page, find the provider under **Add an integration** and press **Configure**. Each catalog card shows the provider's icon, name and category.
2. In **Configure integration**, give it a name and fill the credential and any config fields from its `config_schema`. For the credential, paste the value or type `{{SECRET_NAME}}` to use an existing workspace secret. Required config keys are checked on save.
3. Press **Add integration**. A pasted credential is stored in the secret backend under `INTEGRATION_<SLUG>`; a `{{SECRET_NAME}}` reference must name an existing secret (`422` otherwise) and is read from there, so rotating that secret rotates the integration. Marvin runs `check()` immediately and the card lands with a real status: `ok`, `unconfigured`, `error` or `unavailable`.

### Edit one

Press ✎ (**Edit integration**) on the card. The panel opens as **Edit <name>** with the current name and config; leave the credential blank to keep it, or enter a new value or `{{SECRET_NAME}}`. **Save changes** re-runs the health check. Deleting an integration removes its own stored credential but never a workspace secret it referenced.

### Read the card

Each connected card has a status badge, an enable toggle, the last error, a **Needs attention** notice while the connection has an open alert (see [Integration alerts](#integration-alerts)), "Credential: workspace secret `{{SLUG}}`" when the credential is a reference, and up to three expandable sections:

- **Content**, split into **Needed to work** (content an action reads or writes; missing items get a warning badge and an **Add N missing items** button) and **Optional — set these up if you want them**. Each row has its own **Add** button and, where the blueprint asks for parameters, dropdowns prefilled with defaults; an applied workflow with a newer version shows **Update**. Both come from the provider's declared [blueprints](blueprints.md). Nothing is applied on install; applying creates only what is missing.
- **What you can do with this**: every action with its description, the arguments it takes, and badges for capability routing (for example `image.generate`), `needs approval` and cost hint, followed by **Events it can raise**.
- **How errors are handled**: the provider's error policy, code by code, with per-connection **Review** / **Alert** adjustments (see [When an integration fails](#when-an-integration-fails)). Shown when the provider declares a policy.

The footer shows the integration's slug (what workflows reference), one button per action, ✎ edit, ↻ **Run health check** and ✕ **Delete integration**. An action with inputs opens **Run action** to collect them; one without fires at once. What the action returns opens in a **Result** panel (**Copy**, **Done**).

### Pick a value from the service

Some inputs only make sense as one of the service's own things: a channel, a list, an n8n workflow. A provider can mark such an input with `x-marvin-options`, naming one of its read actions:

```json
"path": {"type": "string", "x-marvin-options": {"action": "list_workflows", "value": "path", "label": "name"}}
```

**Run action** and the workflow **Run integration** step then show a searchable list for that input, loaded through the connection, with ↻ to reload it. **Type a value…** keeps free text for anything not in the list (a template such as `${event.payload.path}`, or a workflow not active yet). If the list can't load — no API key, the service is down — the message shows under the box and free text still works. In a workflow step, each such input of the chosen action gets its own picker above the arguments, and picking writes that key into the arguments JSON; everything else stays in the JSON.

Only actions a provider names this way can be run to fill a list, with the provider's own fixed arguments, and at most 500 choices are shown.

### Logos

A provider can ship its official logo (`marvin-integration-sdk` 0.6.0, `logo = "logo.svg"`, an SVG or PNG inside its package). Marvin shows it on the integration cards, the **Add an integration** catalog, **Admin → Extensions → Plugins** and the workflow **Run integration** step: 32px tall on a white tile in both light and dark mode, keeping its shape (wordmarks get a wider tile), with the name beside it. Without a logo, or if it fails to load, the provider's emoji shows as before.

Marvin checks every logo when it loads the provider and refuses one that is larger than 64 KB, a PNG that isn't really a PNG, or an SVG that could run a script, load something from elsewhere or link out (a DOCTYPE or entity, `<script>`, `<foreignObject>`, `on…` event attributes, links or `url(…)` that don't point inside the file, `javascript:`). A refused logo is logged at startup and the emoji is used instead.

**Secrets in arguments.** An action that must hand a secret to its provider (for example a webhook's shared token when setting up the other side) can take `{{SECRET_NAME}}` as an argument, in **Run action** or a workflow's **Run integration** step. Only a top-level string argument that is exactly a reference is resolved, from this workspace's secrets, and the value goes to the provider call only. A reference to a secret that does not exist is refused: `422` from **Run action**, a step error in a workflow. Event-subscription args do not resolve secrets.

### Wire an action to an event

On `/automation/events/[type]` choose **+ Connect an integration action**, pick the integration and action, and give it args. String args accept `{{field}}` placeholders, filled from the event's document data plus `event_type`, `entity_id`, `entity_type` and `message`; an unknown placeholder is left as-is. `IntegrationEventListener` runs every enabled subscription for the event, each in its own try block, so one failing action does not stop the others. A subscription created from a blueprint starts **disabled**.

### Run an action from a workflow

A workflow's **Run integration** step calls one action of one integration (by its slug) with templated args and hands the result to later steps as `$steps.<id>.output`. See [Workflows](workflows.md).

### When an integration fails

A provider names its failures with a code (`auth`, `rate_limited`, `invalid`, …) and, from `marvin-integration-sdk` 0.5.0, declares how each code is handled: its **error policy**, set on the provider and per action (the most specific entry wins: action code, provider code, action `*`, provider `*`). Core applies it to any workflow that uses the integration, so a workflow needs no on-failure steps of its own for the common cases. A policy entry combines:

- **Review**: the entry goes to Needs review with the reason "Square · invalid — <message>", and `integration_error.<slug>` (`{provider_name, code, message, action, workflow, at}`) is recorded on it; the entry page and the Review Queue card show it, and it is cleared once the step next succeeds. A **published** entry is never taken off the site: it keeps its status, gets the note and the reason, and the connection's alert fires so a person hears about it. With no entry to review (a manual or webhook run), the alert fires instead.
- **Retry**: the step is retried later with the provider's backoff (a remote `Retry-After` is honoured). A retry re-reads the entry, re-checks the workflow's conditions (an entry that no longer matches is not retried), and resumes the run at the failed step: earlier steps never run again, and their outputs are kept. The provider gets its partial progress back (`ctx.resume`) and the same `ctx.idempotency_seed` across the chain. Once retries run out, the policy's `then` applies. A chain has one budget: retries count whatever code they failed with, the limit is the largest `attempts` among the codes it has hit, and no chain runs past 24 hours; a chain that mixed codes or timed out with no `then` sends the entry to review and alerts admins, and one that keeps failing before it reaches the provider (connection disabled, workflow broken) alerts admins. `succeed` together with `retry` never retries (the run already carried on past the step). Attempts are at least a minute apart. A retry that waits for the connection to recover (`on_recovery`, for credentials a timer won't fix) is parked until the alert resolves. A fresh run that passes the step supersedes a pending retry; a deleted entry doesn't (the retry runs from the facts it kept, so closing a listing still happens), and a disabled workflow's retries wait until it is enabled again. Retries are checked every minute, in the background, about 40 seconds' worth per minute; finished ones are kept 30 days. Credentials and resolved `{{SECRET}}` arguments are replaced with `[redacted]` in any error message that is stored or sent.
- **Alert** (`notify`): the connection is marked **Needs attention** (see [Integration alerts](#integration-alerts)).
- **Succeed**: the failure is ignored and the workflow carries on (for example closing a listing that is already gone).

The run is still `failed` (unless every failure was ignored) and still emits `automation_failed`, now with `handled: true` and `handling` (for example "handled by Square: sent to review"); a retry chain announces its first failure and how it ends (`automation_ran` "succeeded on retry 2", or `automation_failed` once retries run out), with `retry_attempt` on a retry's event, not every retry in between, so the toast is a yellow warning instead of a red error and **Runs** shows the handling under the step, a **handled** tag, and each retry linked to the run it retried ("succeeded on retry 2"). With no policy (an SDK before 0.5.0, or a provider that declares none) a failure behaves exactly as before.

A workflow's own [on-failure steps](workflows.md#when-a-step-fails) run **instead of** the policy, and `integration_errors: "fail"` in a definition opts a workflow out; in both cases only the alert still fires. Event subscriptions, capability calls and **Run Integration Action** tasks get the alert only (nothing to review or retry); a test-fire from the card gets nothing.

**Adjusting a policy.** The card's **How errors are handled** table lists each code the provider declares (plus **Any other error**), what happens, and **Review** and **Alert** checkboxes showing the provider's default; an admin can change them per connection (stored as `error_overrides`), and **Reset to default** undoes it. Retries, backoff and `then` stay as the provider declares them.

### Integration alerts

One alert per connection and error code, counted, never one per item. It opens on the first failure whose policy says notify and emits `integration_attention_needed` (in the bell always), again after each reminder window while it stays open, and resolves on a passing health check, the connection's next successful action, or **Resolve** on the card, emitting `integration_attention_resolved` and re-arming parked retries. The card shows **Needs attention**, the latest message, "N failures since …", **Test** (runs the health check) and **Resolve**.

Where alerts go besides the bell is set under **Settings → Integrations → Integration alerts** (admins): email the workspace's owners and admins (the **Integration Alert** system template), and any Slack (`send_message`) or Apprise (`notify`) connection, plus the reminder window (default 24 hours; 0 never reminds). It writes ordinary event subscriptions for `integration_attention_needed`; turning a route off disables its subscription rather than deleting it. Each alert records the subscriptions it went out through, and its "working again" notice goes back through exactly those, even if the routing changed in between. Delivering an alert never raises another one: a failing Slack connection does not alert about itself through itself.

### Newsletter with Buttondown

The Buttondown provider keeps Marvin as the list of record while [Buttondown](https://buttondown.com) sends the email. A signup on the site becomes a Buttondown subscriber; when the reader confirms, their signup entry is published, and when they unsubscribe it is archived (inbox = pending, published = confirmed, archived = unsubscribed). Publishing a newsletter issue creates its Buttondown email.

- **Connection**: the **API key** (best as a `{{SECRET}}` reference), **Issue delivery** and an optional **Site URL**. Issue delivery is **Off** (publishing an issue does nothing in Buttondown), **Draft** (the default: a draft to review and send in Buttondown) or **Send** (sent to subscribers straight away). Relative links in an issue are made absolute against the Site URL, or, when it is blank, the workspace's **Canonical URL**, which the workflow passes as `${site.url}`.
- **`subscribe`** returns the existing subscriber for an address already on the list. If that subscriber never confirmed, it asks Buttondown to re-send the confirmation email (`confirmation_resent` in the result); if Buttondown refuses, the signup still succeeds. An address that unsubscribed before is refused by Buttondown (`subscriber_suppressed`) and has to be re-added there. Every error carries a code a workflow's on-failure steps read as `${error.code}`: `blocked` (the spam firewall refused the address), `spammy` (it refused the visitor's IP), `suppressed` (unsubscribed before) or `unknown` (anything else).
- **`create_issue_email`** follows Issue delivery, sends the issue's page (`${entry.url}`) as its canonical URL, and runs once per entry: an issue that already has its email is skipped, not sent twice.
- **Connect Buttondown webhooks** (`connect_webhooks`) creates or updates the Buttondown webhook that posts this workspace's subscriber confirmations and unsubscribes to its `buttondown` incoming webhook, signed with `{{BUTTONDOWN_SIGNING_KEY}}`. It is safe to run again, never touches webhooks pointing elsewhere, and can retire one old hook URL you name. With `patch` on the HTTP helper (rc.182) it updates the webhook in place; on an older Marvin it creates a new one and deletes the old.
- **Content**: the `buttondown` incoming webhook, workflows for signup → subscribe, confirmed → publish, unsubscribed → archive and published issue → email, and two optional workflows that keep a confirmed-subscribers collection. Confirm and unsubscribe workflows find the signup entry with an entry step set to skip when nothing matches (`if_none: skip`), so a reader who subscribed through another workspace on the same Buttondown account leaves the run green.
- **A refused signup goes to Needs review.** When `subscribe` fails (a firewall refusal, an earlier unsubscribe, Buttondown unreachable), the signup workflow's run fails as before, and its [on-failure steps](workflows.md#when-a-step-fails) record `buttondown_subscribe_error` (`{code, message, at}`) on the signup entry and send it to review with the error as its reason. It shows in the Review Queue (the card lists the reason) and in the dashboard's Needs attention, instead of waiting in the inbox like a pending signup. Nothing retries it: archive spam, or add a real reader by hand in Buttondown (a `suppressed` one is re-added there, and their confirmation then publishes the entry). A workspace that applied the content before this sees **Update** on the signup workflow's row in the card; click it to get the on-failure steps.

It needs rc.177 for `${site.url}`, rc.179 for `${entry.url}` and `if_none: skip`, and the release after rc.192 for the on-failure steps (an older Marvin ignores them). Setup steps, parameters and known limits are in the package's [README](https://github.com/InnerOpen/marvin-integration-buttondown#readme).

### Capability routing

An action that declares a `capability` (currently `image.generate`, `image.edit`, `image.describe`, `image.search`, `image.upscale`) is discoverable by kind rather than by provider. `integrations_providing(kind, group_id)` returns pre-authorised handlers from every enabled integration in the workspace, highest `priority` first; `src/marvin/services/ai/media/capability.py` consumes it. Each invocation is logged as an `ai_executions` row and an `ai_operation_executed` (or `ai_operation_failed`) event, so paid capability spend shows in the event log.

## API

All routes are workspace-scoped under `/api/groups/integrations` and mounted only when the SDK is installed.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/providers` | Provider catalog (`slug`, `name`, `description`, `category`, `icon`, `has_logo`, `config_schema`, `credentials`, `actions`, `emits`, and from SDK 0.5.0 `error_policy`, also per action) |
| GET | `/providers/{slug}/logo` | The provider's validated logo (SVG or PNG). **Public.** Sent with `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; sandbox`, an `ETag` (`304` on `If-None-Match`) and `Cache-Control: public, max-age=3600`; 404 when the provider has no accepted logo |
| GET | `/plugins` | Load reports per entry point: distribution, version, `ok`, `error` |
| GET / POST | `` | List / create; `credential` is write-only and may be `{{SECRET_NAME}}`. Reads return `has_credential`, `credential_secret` (the referenced secret's slug, if any), `attention` (open alerts) and `error_overrides` |
| PATCH / DELETE | `/{integration_id}` | Rename, enable, change config, replace the credential / delete with its own stored secret |
| POST | `/{integration_id}/check` | Run `check()` and persist `status`, `last_error`, `last_checked_at` |
| POST | `/{integration_id}/actions/{action_key}` | Run an action; body is the args dict, where a top-level `{{SECRET_NAME}}` value is resolved for the call. Returns `{ok, result}`. 409 if disabled or the provider is not installed, 422 for a missing secret, 502 on a provider `ValueError` |
| POST | `/{integration_id}/options` | `{action_key, input}` → `[{value, label}]` (at most 500) for an input with an `x-marvin-options` hint: runs the read action the hint names, with the hint's args, like **Run action**. 404 unknown connection or action, 409 disabled or provider not installed, 422 no or malformed hint, a provider failure (`Couldn't load the options: …`) or a result with no list |
| POST | `/{integration_id}/resolve?alert_id=` | Resolve the connection's open alerts (or one), announce it and re-arm parked retries (admin) |
| PUT | `/{integration_id}/error-overrides` | `{overrides: {code: {review?, notify?}}}` for declared codes or `*`; `{}` resets (admin) |
| GET / PUT | `/alert-routing` | Where alerts go: `email_admins`, `targets` (connections that can carry them, with `enabled`) / `integration_ids`, `reminder_hours` (admin) |
| GET / POST | `/subscriptions?event_type=` | List / create `event_type → action + args` |
| PATCH / DELETE | `/subscriptions/{sub_id}` | Toggle `enabled` or replace `args` / remove |

The platform-wide list is `GET /api/admin/plugins` (super admin): each installed package with `name`, `package`, `version`, `kind`, `ok`, `error` and `providers` (`slug`, `name`, `icon`, `has_logo`, `actions`, `blueprints`, `workspaces`). Blueprints are applied through `/api/groups/blueprints`; see [Blueprints](blueprints.md). Full reference: [API reference](../api/index.md).

## Settings

No setting switches integrations on; presence of an installed provider does. Credentials go through whichever secret backend the instance is configured with.

| Setting | Default | Effect |
| --- | --- | --- |
| `INTEGRATION_HTTP_MAX_BYTES` | `5000000` | Largest response a provider may download through the HTTP helper; a bigger one is refused. Raise it for providers that move files. Must be at least 1. |

## Since

Integrations: 1.0.0-rc.97 (commits 4f8d30e3, 847631de, 3e1603b4, bfad4311, 2c581d2c, 2b71a0c8, 53f896fb, 2026-09-24/25). Workflow integration step and HTTP `put`/`delete`: rc.111. Integration-contributed signature schemes: rc.113. Applying parameterised content from the card, action results and `{{SECRET}}` credentials: rc.114. Editing a connected integration: rc.115. Named User-Agent: rc.119. `INTEGRATION_HTTP_MAX_BYTES`: rc.123. Token-mode signature schemes from integrations: rc.144. `{{SECRET}}` references in action arguments: rc.145. **Admin → Extensions → Plugins** and `GET /api/admin/plugins`: rc.158. HTTP `patch`: rc.182. Integration-owned error handling (error policies, retries, alerts, **How errors are handled**, **Integration alerts**): unreleased, migration `c9e2f4a6b8d1`; providers declare policies from `marvin-integration-sdk` 0.5.0. Option pickers for action inputs (`x-marvin-options`, `POST /{integration_id}/options`) and provider logos (`GET /providers/{slug}/logo`, from `marvin-integration-sdk` 0.6.0): unreleased. The Buttondown provider is a separate package; it relies on `${site.url}` (rc.177), `${entry.url}` and `if_none: skip` (rc.179).

Note: `docs/INTEGRATIONS_DESIGN.md` and the plugin architecture doc predate the implementation and describe polling that nothing calls; the SDK package is the contract.

## Related

- [Blueprints](blueprints.md) — the content a provider declares.
- [Incoming webhooks](incoming-webhooks.md) — where integration signature presets appear.
- [Collections](collections.md) — the smart collections Instagram declares.
- Design: [INTEGRATIONS_PLUGIN_ARCHITECTURE.md](https://github.com/InnerOpen/marvin/blob/develop/docs/INTEGRATIONS_PLUGIN_ARCHITECTURE.md)
- [Glossary](../glossary.md)
