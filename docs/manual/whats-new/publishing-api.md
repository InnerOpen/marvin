# Publishing API

The public read API serves a workspace's published content to sites and tools that authenticate with an API client token.

## What it does

`/api/publish/{workspace_slug}` is the read-only surface a site builds from. Every request carries an **API client token** (prefix `marvin_sk_`) in `Authorization: Bearer`, created under **Settings → Publishing → Site Clients**. The token identifies one workspace and a `permissions` dict of keys such as `read:published_entries`; each route checks the keys it needs and returns 403 with the missing key named.

Only entries with status `published` are served, and only from entry types whose capabilities allow it. Collections are served only when `is_public` is true (**Visible to sites** on the collection's form, see [Collections](collections.md)); the five system workflow collections are never public. A private collection can't be read through the entries `collection` filter either: it returns an empty list, as for a slug that doesn't exist.

What is new in this release:

- **`expand=full` on the list endpoints.** `/collections/{slug}`, `/entries` and `/resources/{slug}/entries` return each entry in the single-read shape, so a site gets asset roles and resources for a whole collection in one request instead of one per entry. See [Full entries in one request](#full-entries-in-one-request-expandfull).
- **List items carry `data` and `description`** (fadb3f52). `PublishedEntryListItem` now includes the entry's schema fields (`data`, never null) and its `description`, so a whole collection or entries page renders from one request. `marvin-astro` skips its per-entry hydrate fetch when `data` is present, which removes an N+1 on large collections.
- **Entries of non-publishable types are never served** (0e676a23). An entry of a submittable type (a contact message, a newsletter signup) with status `published` used to be returned with its data to any site token. Types whose capabilities say `publishable: false` are now excluded from the entries list, entry detail, collection entries and resource entries, whatever the status. Absent capabilities count as publishable.

## Where

- Base URL: `/api/publish/{workspace_slug}`.
- Tokens: **Settings → Publishing → Site Clients** (`/publishing/clients`). The plaintext token is shown once, in a dialog, when you create the client or rotate its token (see [Auth and tokens → API clients](../auth-and-tokens.md#api-clients-marvin_sk_)).
- Consumers: `@inneropen/marvin-sdk` ([SDK docs](https://inneropen.github.io/marvin/sdk/)), `marvin-astro`, and the Marvin CLI ([CLI docs](https://inneropen.github.io/marvin/cli/)), whose `marvin publish` command group (site, entries, collections, resources, assets, renderers — shown once you `marvin login --site-token …`) calls this API directly.

## How to use

```bash
export MARVIN_SITE_TOKEN=...   # the API client token
curl -H "Authorization: Bearer $MARVIN_SITE_TOKEN" \
  "https://marvin.example/api/publish/my-site/entries?entry_type=post&limit=20"
```

Paginate with `limit` (default `PUBLISHING_DEFAULT_PAGE_SIZE` = 20, capped at `PUBLISHING_MAX_PAGE_SIZE` = 100) and `offset`. Entries list newest-published first; assets and resources list by name.

Sample `GET /entries` response (fields abbreviated):

```json
{
  "data": [
    {
      "slug": "hello-world",
      "title": "Hello world",
      "entryType": "post",
      "entryTypeInfo": {"slug": "post", "renderer": null, "publishable": true, "submittable": false, "routable": true},
      "url": "https://example.com/blog/hello-world",
      "summary": "First post.",
      "description": "Longer blurb for cards and meta tags.",
      "data": {"body": "…", "hero": "…"},
      "publishedAt": "2026-09-11T10:00:00Z",
      "status": "published",
      "collections": [{"role": null, "position": 0, "collection": {"slug": "featured", "name": "Featured", "sortOrder": 1}}],
      "assetSlugs": ["hero-1"],
      "resourceSlugs": [],
      "tags": ["launch"],
      "featuredAsset": {"slug": "hero-1", "publicUrl": "…", "mimeType": "image/jpeg"},
      "order": null
    }
  ],
  "meta": {"total": 1, "page": 1, "limit": 20, "offset": 0}
}
```

Field names are camelCase on the wire; the `PublishedEntriesResponse` schema is the reference.

### Full entries in one request: `expand=full`

A list item has asset and resource *slugs* only. A site that needs asset roles (the hero image), resources or every collection membership used to read each item again through `/entries/{slug}`, one request per entry. Add `expand=full` to `/collections/{slug}`, `/entries` or `/resources/{slug}/entries` and each entry comes back in the single-read shape (`PublishedEntryRead`: `assets[]` and `resources[]` placements, full `collections`, `data`, `embeds`), the same JSON `/entries/{slug}` returns for it. A collection's entries also keep their `order`.

- Filters and pagination are unchanged. `/entries` keeps its `limit` cap (`PUBLISHING_MAX_PAGE_SIZE`, 100). The two unpaginated endpoints expand up to `PUBLISHING_MAX_EXPANDED_ENTRIES` entries (default 500); past that they return plain list items, as a server without `expand` does, and a client falls back to per-entry reads.
- Expanding never shows more than the single read: published entries only (a `read:all_entries` token's drafts drop out of an expanded collection), and the token needs `read:published_entries` or `read:all_entries` on top of the endpoint's own key, else 403.
- The cost is a fixed number of queries per response, however many entries it holds. Any other value of `expand` is a 422; without it the response is exactly as before.
- Detect a server that ignores the parameter by the items: a list item has `assetSlugs`, an expanded one has `assets[]`. `marvin-astro` does this and falls back to per-entry reads.

## API

| Method | Path | Query | Permission |
| --- | --- | --- | --- |
| GET | `/` | — | `read:published_entries` or `read:all_entries` |
| GET | `/site` | — | same; returns site configuration (SEO, verification tags, `embeds`: media privacy mode, consent text, player origins) |
| GET | `/entry-types` | — | same; ordered by `sort_order`, name |
| GET | `/entries` | `entry_type`, `collection`, `tag` (comma, any), `slug` (comma), `updated_since` (ISO), `limit`, `offset`, `expand` | same |
| GET | `/entries/{slug}` | — | same; full `PublishedEntryRead` with collections, resources, assets and media `embeds` (list items carry `embeds` too; see [Media embeds](media-embeds.md)) |
| GET | `/collections` | `limit`, `offset` | `read:collections`; public collections only |
| GET | `/collections/{slug}` | `expand` | `read:collections`; entries ordered by junction `sort_order` then `published_at` desc. With `read:all_entries` the token also sees non-published members (not with `expand=full`) |
| GET | `/assets` | `type` (MIME prefix: image, video, audio, application), `limit`, `offset` | `read:assets` |
| GET | `/assets/{slug}` | — | `read:assets` |
| GET | `/assets/{slug}/file` | — | `read:assets`; streams the file |
| GET | `/resources` | `resource_type`, `limit`, `offset` | `read:resources` |
| GET | `/resources/{slug}` | — | `read:resources` |
| GET | `/resources/{slug}/entries` | `expand` | `read:resources`; published entries linked to the resource |
| GET | `/forms/{slug}` | — | `read:published_entries`; form definition, success message, honeypot field name when enabled |
| POST | `/forms/{slug}/submit` | body: submission dict | `write:public_entries` or `write:form_submissions` |

Form submission runs the security gauntlet in order: rate limit by IP (opt-in via `rate_limit_max`), honeypot (a filled field is silently dropped), then CAPTCHA (`captchaToken`, hCaptcha by default). A submittable entry type creates an inbox entry and raises `form_submission_received`; notification failure never fails the visitor's request.

### Permission keys

Defined in `src/marvin/core/permissions.py`:

| Key | Enforced by publishing routes | Notes |
| --- | --- | --- |
| `read:published_entries` | yes | default on a new client |
| `read:all_entries` | yes | substitutes for `read:published_entries` and widens `/collections/{slug}` |
| `read:collections` | yes | default on a new client |
| `read:assets` | yes | default on a new client |
| `read:resources` | yes | |
| `write:public_entries` | yes | form submit, entry-type path |
| `write:form_submissions` | yes | form submit, legacy key existing site tokens hold |
| `read:draft_entries` | no | defined, but no publishing route checks it; the client form stopped offering it in rc.181 (`read:all_entries` is what grants drafts) |
| `read:forms`, `write:forms`, `read:form_submissions` | no | defined; no route references them |

The create and edit forms (`/publishing/clients/new`, `/publishing/clients/{id}/edit`) offer exactly the keys the routes check, in two groups: **Content** (Read Published Entries, Read All Entries, Read Collections, Read Assets, Read Resources) and **Forms** (**Submit Forms** for `write:form_submissions`, **Submit Public Entries** for `write:public_entries`). A key a client holds that the form doesn't list appears under **Other**, so it can be removed. Full reference: [`../api/`](../api/index.md).

## Entry page URLs

Marvin does not know your site's routes, so by default it cannot say where an entry is shown. Two optional settings tell it:

- **Canonical URL** — the site's address, under **Settings → General → Site Configuration** or **Publishing → Site Configuration** (`site_canonical_url` in the workspace preferences), e.g. `https://example.com`.
- **Page URL pattern** — on each entry type that has its own page, on the entry type's edit screen (`pageUrlPattern` on the entry-types API), e.g. `/blog/{slug}`. Placeholders: `{slug}`, `{id}` and `{entry_type}` (the type's slug); the pattern must use `{slug}` or `{id}`. A path is joined to the Canonical URL; a full `https://…` pattern is used as-is, for a type that lives on another host. Leave it blank for types without a page (navigation items, form submissions). A type whose capabilities say `routable: false` never gets a URL.

With a pattern set, each entry of that type gets a URL:

- the publishing API adds `url` to entries in lists and in entry detail (absolute when the Canonical URL is set, otherwise the site path) and `pageUrlPattern` to `GET /entry-types`. Both are null when not configured, and nothing else in the payload changes;
- Entry Details in the admin shows a **View on site** button (absolute URLs only, so the Canonical URL must be set), enabled once the entry is published; before that it is greyed out and says "Available once published";
- agents get the `url` from their entry tools (see [Agents and Ask → Linking to entries](agents-and-ask.md)).

The URL is built whatever the entry's status, because a draft's link is where it will live; the publishing API serves only published entries anyway. Entry types shared by every workspace (system types with no workspace) can't hold a pattern; the copies a workspace starts with can. The pattern travels with workspace exports and imports.

**Placeholder links block publishing.** Moving an entry to `published` fails with 422, like a missing required field, when a markdown or richtext field, the summary or the description contains a link with no real target: `[text](#)`, `[text]()`, `<a href="#">` or `<a href="">`. The error names each affected link text, e.g. `'Body' has placeholder link(s) with no real URL: 'Blue Heron', 'Gone'.` In-page anchors such as `[prices](#prices)` are real links and pass. Scheduled publishing skips such an entry and keeps its schedule, as with any other unmet requirement.

## Site rebuilds

A static site that builds from this API is usually rebuilt by an outgoing webhook (its host's deploy hook) subscribed to `webhook_triggered`. The `request_site_rebuild` handler, from a workflow step or a scheduled task, queues a rebuild for the workspace instead of sending one each time. The scheduler sends one `webhook_triggered` per workspace once requests stop arriving for `SITE_REBUILD_QUIET_SECONDS` (default 60), or at most `SITE_REBUILD_MAX_WAIT_SECONDS` (default 600) after the first request, so a bulk edit triggers one build. A single change therefore starts building a minute or two later; read fast-changing values live if the site cannot wait. See [Operations → Site rebuilds](../operations.md#site-rebuilds).

**Automatic rebuilds.** Published content changes queue a rebuild on their own, with no workflow needed. **Settings → General → Site Configuration → Rebuild the site automatically** (`site_auto_rebuild` in the workspace preferences, on by default) controls it. What counts:

- an entry published, unpublished, archived or deleted;
- on a published entry, or one leaving `published`: an edit, a collection added or removed, a tag, resource or image attached or detached;
- a collection updated or deleted, an asset or resource updated or deleted, and workspace site settings changed (`workspace_settings_changed`).

A draft saved or moved between workflow collections queues nothing, and neither does anything done to an entry of a non-publishable type (a newsletter signup confirmed and filed) or to a collection with **Visible to sites** off (its members, edits, order or deletion), except turning **Visible to sites** on or off. The requests go into the same per-workspace queue as `request_site_rebuild`, so a burst of edits is one build, and the rebuild still goes out as `webhook_triggered` to the workspace's deploy hook. Without an outgoing webhook on **Site Rebuild Sent** (`webhook_triggered`) nothing is built.

**Queued rebuilds.** The request that opens a new batch emits `site_rebuild_queued` once (never per request), with the reason, the first change, the quiet and maximum waits and `expected_send_at`. The admin shows it as "Site rebuild queued — building in about 60 s" with "More changes join this build (sent at the latest 10 min after the first)" (the times come from `SITE_REBUILD_QUIET_SECONDS` and `SITE_REBUILD_MAX_WAIT_SECONDS`), and that toast turns into the **Site rebuild** toast in place when the rebuild is sent. Later requests join the batch without a toast of their own.

**What a rebuild covers.** Each queued rebuild keeps a list of the content changes it covers, worded like the event log ("Entry 'Summer menu' published"). Repeat edits of one thing collapse to its newest line and the list keeps the newest 50; the request count still counts every request. The `webhook_triggered` event carries them in its data as `requestCount` and `changes` (each with `label`, `event`, `entityType`, `entityId`, newest last), and the event catalog lists `request_count` and `changes` as its variables; a deploy hook ignores the body. In the admin, the **Site rebuild** activity toast gets an "N changes ▾" button that opens the list, newest first, with entry changes linked to the entry; when repeats were collapsed or the list was cut, it ends "and K more (repeat or earlier edits)". While the list is open, or the pointer or focus is on the toast, it does not fade. `GET /api/platform/events/feed` returns the newest 20 changes and the `requestCount` on that event.

**Build and deploy status.** A host that can post build or deploy notifications can report back as Marvin events. Point the host at an [incoming webhook](incoming-webhooks.md) (a host that sends a fixed shared secret instead of signing fits the `static_token` scheme), then add workflows on that webhook whose **Emit event** step emits `site_deployment_*` (`started`, `completed`, `failed`; the old names `site_build_*` emit the same events) with a templated message, failure reason and site URL (see [Workflows → Step kinds](workflows.md#step-kinds)). The events land in the event log and show as activity toasts: started, completed (green) and failed (red, with the reason, staying until dismissed). The mapping is workspace configuration, so any host fits; the Cloudflare Pages integration package declares the webhook and workflows for Cloudflare (see [Integrations](integrations.md)).

**Rebuild on request.** `POST /api/platform/site/rebuild` asks for a rebuild without a workflow, for a script, the CLI (`marvin site rebuild`) or n8n. It needs **EDITOR** or above in the workspace, the role that publishes (a VIEWER or AUTHOR gets 403). The body is optional: `{"reason": "…"}` (at most 200 characters; default "Rebuild requested by <your name>"). The request joins the same per-workspace queue as `request_site_rebuild` and automatic rebuilds, so calling it again before the rebuild goes out adds to the same build; the workspace shows as one line in the rebuild's change list however often it asks. It answers 202 with `requested: true`, `queuedAt` (when the pending rebuild was first requested, the same for every request that joins it), `lastRequestedAt`, `expectedSendAt` (quiet period after the last request, capped at the maximum wait after the first), `requestCount`, `reason`, and what will build the site: `targets` lists each enabled outgoing webhook on **Site Rebuild Sent** (`kind: "webhook"`) and each enabled integration with an action subscribed to it (`kind: "integration"`, with `provider` and `action`, e.g. Cloudflare Pages → `deploy`); `target` is that one when there is exactly one and `null` when there are several. With none, nothing would build, so the request is refused with **409** and nothing is queued.

`GET /api/platform/site/rebuild` (also EDITOR) shows where it stands: `configured` (false when a POST would get 409), `target`/`targets`, `quietSeconds` and `maxWaitSeconds`, `pending` (the queued rebuild not sent yet: `queuedAt`, `lastRequestedAt`, `expectedSendAt`, `requestCount`, the latest `reason` and its `changes`; `null` when nothing waits), `lastSent` (the newest `webhook_triggered` in the event log: `eventId`, `sentAt`, `message`, `requestCount`), and `lastBuild`, the newest `site_deployment_*` event (or, from before they became old names, `site_build_*`) (`eventType`, `stage` `build`/`deployment`, `status` `started`/`completed`/`failed`, `occurredAt`, `message`, and the host's `detail`, `deploymentId` and `siteUrl` when it sent them). `lastBuild` is `null` until a host reports builds back (see **Build and deploy status** above); the event log's retention (`EVENT_LOG_RETENTION_DAYS`) bounds how far back `lastSent` and `lastBuild` reach.

## Settings

| Setting | Default | Purpose |
| --- | --- | --- |
| `PUBLISHING_DEFAULT_PAGE_SIZE` | 20 | `limit` when omitted |
| `PUBLISHING_MAX_PAGE_SIZE` | 100 | upper bound on `limit` |
| `PUBLISHING_DEFAULT_STATUS` | `published` | the only entry status served |
| `PUBLISHING_UNKNOWN_ENTRY_TYPE` | `unknown` | `entry_type` value for entries without a type |
| `MEDIA_EMBEDS_FETCH_ENABLED` | `true` | look up media links' titles and player ids through the providers' oEmbed (never on a publishing read); see [Media embeds](media-embeds.md#settings) |

## Since

Endpoints predate rc.40. `data`/`description` on list items: rc.48 (`fadb3f52`). Non-publishable types never served: rc.62 (`0e676a23`). Site-rebuild coalescing: rc.121; its two settings: rc.122. Automatic rebuilds on published content changes: rc.143. Build and deploy status events: rc.144. The changes a rebuild covers, on `webhook_triggered` and in the **Site rebuild** toast: rc.154; its event-catalog entry: rc.155. The **Site rebuild queued** toast (`site_rebuild_queued`): rc.165. Entry page URLs (`url`, `pageUrlPattern`, **View on site**) and placeholder links blocking publishing: rc.172. **View on site** disabled until the entry is published: rc.194. The client form's **Forms** permissions and an edit page: rc.181. Private collections ignored by the entries `collection` filter: rc.186. No rebuild for changes no site can see: rc.191.

## Related

- [Collections](collections.md) — public and smart collections as served here.
- [Media embeds](media-embeds.md) — `embeds` and `site.embeds`.
- Design: [publishing-api.md](https://github.com/InnerOpen/marvin/blob/develop/docs/publishing-api.md), [site-clients-and-publishing.md](https://github.com/InnerOpen/marvin/blob/develop/docs/site-clients-and-publishing.md)
- [Glossary](../glossary.md)
