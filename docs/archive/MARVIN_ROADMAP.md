# Marvin Platform Roadmap

This document captures the current direction for Marvin as a multi-workspace content, publishing, automation, and intake platform.

It is intentionally broader than one sprint. Use it as a planning/reference document for Claude, Codex, or any other AI/dev agent working in the repository.

## Core Vision

Marvin is not just a CMS and not just a Mealie fork.

Marvin is a workspace-centered content operating system.

It should let a user capture ideas, files, photos, documents, and notes from anywhere, turn them into structured drafts, review them, and publish them through websites, APIs, automations, or future social/media workflows.

The admin UI is useful, but it should not be the only way to use Marvin.

The long-term goal is:

```text
Capture anywhere
  -> Intake
  -> AI-assisted parsing/enrichment
  -> Human review
  -> Entry / Resource / Asset creation
  -> Publishing / automation
```

## Guiding Rules

- External tools may create intake drafts.
- External tools may create draft entries when explicitly requested.
- AI may suggest, parse, enrich, and draft.
- AI should not auto-publish.
- Human approval is required before anything becomes published content.
- Marvin remains the source of truth.
- Public websites consume Marvin through read-only site clients.
- Admin UI, CLI, SDK, n8n, and AI agents should all use the same APIs/SDK layers.

## Existing / Recent Foundation

Marvin already has or is moving toward:

- Workspaces using existing `groups`.
- SUPER_ADMIN and workspace roles.
- Active workspace context.
- Workspace management endpoints.
- Workspace settings replacing site-level `site.ts` files.
- Entry Types.
- Entries.
- Collections.
- Entry Collections.
- Smart Collections using JSON rules.
- Publishing API concepts.
- Events, webhooks, scheduler, email/notification infrastructure.
- A TypeScript SDK direction.
- A CLI direction using the SDK.

## Content Primitives

The four foundational content primitives are:

```text
Entries
Collections
Assets
Resources
```

### Entries

Entries are things the user creates.

Examples:

- Page
- Project
- Bench Note
- Product
- Guide
- Article
- Runbook
- Procedure
- Pattern

Entries should support:

- Workspace/group scoping.
- Entry type.
- Slug.
- Status.
- Markdown body.
- Summary/description.
- Metadata JSON.
- Future custom fields.
- Future relationships.
- Future revisions.

### Collections

Collections organize entries.

Collection types:

```text
manual
smart
```

Manual collections use the `entry_collections` join table.

Smart collections use JSON rules and are evaluated dynamically.

Smart collection membership should not be written into `entry_collections`.

### Assets

Assets are binary files or media.

Examples:

- Images
- PDFs
- SVGs
- Documents
- Audio files
- Videos
- Pattern scans

Assets should eventually support:

- Original file.
- Processed variants.
- Alt text.
- Focal point.
- Metadata.
- AI analysis.
- Relationships to intake items, entries, resources, and collections.

### Resources

Resources are reusable structured objects.

Resources are not files. Files are assets.

Examples for Mash & Burn Co.:

- Fabric
- Thread
- Buttons
- Zippers
- Tools
- Suppliers
- Books
- Patterns

Examples for InnerOpen:

- Repository
- API
- Cluster
- Service
- Vendor
- Application
- Runbook reference

Resources should eventually support:

- Resource type.
- Metadata JSON.
- Custom fields.
- Related entries.
- Related assets.
- Related resources.
- Publishing if appropriate.

## SDK Architecture

Marvin should have a broader TypeScript SDK, not only a publishing client.

Recommended package direction:

```text
@marvin/sdk/core
@marvin/sdk/publish
@marvin/sdk/admin
```

or a single package with subpath exports:

```text
@marvin/sdk
@marvin/sdk/publish
@marvin/sdk/admin
```

### Publish SDK

This is installed into public/client sites such as Mash & Burn Co. and InnerOpen.

It uses site client tokens.

It is read-only.

It should expose published content only.

Capabilities:

- Site/workspace config.
- Published entries.
- Published collections.
- Published collection entries.
- Published assets.
- Published resources.
- Future published search.

It must not expose:

- Drafts.
- Users.
- Admin settings.
- Workspace management.
- Events/webhooks management.
- Personal API tokens.

### Admin SDK

The Admin SDK is used by:

- Marvin Admin UI.
- `marvinctl` CLI.
- AI agents with trusted access.
- Internal automations.
- Developer scripts.

Capabilities:

- Workspaces.
- Active workspace.
- Workspace settings.
- Entries.
- Entry Types.
- Collections.
- Smart collections.
- Resources.
- Assets.
- Intake.
- Users.
- Memberships/roles.
- Site clients.
- Personal API tokens.
- Events.
- Webhooks.
- Notifications.
- Scheduler hooks if exposed.

### SDK Core

The core layer should handle:

- HTTP requests.
- Auth headers.
- Site client tokens.
- User/admin tokens.
- Workspace context.
- Error normalization.
- Pagination.
- Retries if needed.
- OpenAPI generated types.
- Response mapping.

The SDK should be the only place frontend/admin/CLI code performs raw API calls.

Admin UI should eventually become just another SDK consumer.

## OpenAPI Codegen

Use OpenAPI to keep the SDK updated.

Recommended flow:

```text
FastAPI backend
  -> /openapi.json
  -> generated TypeScript types/client
  -> hand-written Marvin SDK layer
```

Generated code should be treated as a low-level transport layer.

The hand-written SDK should provide the stable Marvin developer experience.

Suggested tooling:

- `openapi-typescript`
- `openapi-fetch`

Possible script direction:

```json
{
  "scripts": {
    "sdk:openapi": "curl http://localhost:8000/openapi.json -o packages/sdk/openapi.json",
    "sdk:generate": "openapi-typescript packages/sdk/openapi.json -o packages/sdk/src/generated/schema.ts",
    "sdk:build": "npm run sdk:openapi && npm run sdk:generate && npm run build -w packages/sdk"
  }
}
```

Important separation:

```text
Generated client = low-level API surface
Marvin SDK = stable conceptual interface
```

Example:

```ts
// generated
client.GET('/api/entries')

// SDK
marvin.entries.list()
marvin.collection('projects').entries()
marvin.workspace.current()
```

## CLI Direction

The CLI should live under:

```text
apps/cli
```

The reusable SDK should live under:

```text
packages/sdk
```

The CLI binary should be:

```text
marvinctl
```

This avoids collision with any existing backend `marvin` command.

CLI should use the SDK only. It should never import backend internals.

Useful commands:

```bash
marvinctl workspace list
marvinctl workspace use mash-burn
marvinctl site
marvinctl entries
marvinctl entries --json
marvinctl collections
marvinctl collections --yaml
marvinctl resources
marvinctl resources --csv
marvinctl assets
marvinctl intake list
marvinctl intake create --file ./note.md
marvinctl intake upload ./photos/*.jpg --title "Pocket shape idea"
```

Output formats should include:

```text
table
json
yaml
csv
```

CLI config should use environment variables or a local config file ignored by Git.

## Intake Pipeline

Intake is the biggest workflow unlock.

Marvin should support collecting raw input from:

- CLI.
- Admin UI.
- n8n.
- Airtable.
- Voice notes.
- Image uploads.
- PDFs.
- Documents.
- Future browser extensions.
- Future mobile app.
- AI agents.

Intake items are not final content.

They are reviewable raw material.

### Intake Item vs Entry

Intake Item:

- Raw incoming idea/blob.
- May include files.
- May include rough JSON.
- May include AI suggestions.
- Safe to delete.
- Not publishable.

Entry:

- Structured Marvin content.
- Has entry type.
- Has slug.
- Has status.
- Can be reviewed/published.

This separation keeps messy automation from polluting real content.

### Intake Statuses

Suggested initial statuses:

```text
received
needs_review
processing
parsed
entry_created
merged
rejected
archived
```

### Intake Actions

Admin UI actions:

```text
Parse Draft
Create Entry
Merge Into Existing Entry
Reject
Delete
Archive
```

### Intake API

Suggested endpoints:

```text
POST /api/intake
POST /api/intake/bulk
POST /api/intake/from-json
GET  /api/intake
GET  /api/intake/{id}
PATCH /api/intake/{id}
POST /api/intake/{id}/parse
POST /api/intake/{id}/create-entry
POST /api/intake/{id}/merge
POST /api/intake/{id}/reject
```

### Intake JSON Example

```json
{
  "source": "n8n",
  "intent": "bench_note",
  "workspace": "mash-burn",
  "title": "Pocket shape idea",
  "rawText": "This pocket shape might work for the black denim jacket...",
  "suggestedEntryType": "bench-note",
  "suggestedCollections": ["on-the-bench"],
  "suggestedPublishingTargets": ["website", "instagram"],
  "metadata": {
    "origin": "mobile voice note"
  }
}
```

Response:

```json
{
  "intakeId": "...",
  "status": "needs_review",
  "reviewUrl": "https://marvin.example.com/intake/..."
}
```

## Intake Uploads / File Intake

Marvin needs a file upload endpoint for intake.

This should support:

- Multiple images.
- PDFs.
- Documents.
- Audio.
- Pattern files.
- Any file that can later become an Asset.

### Endpoint

Use multipart first because it works with admin UI, CLI, curl, n8n, and SDK.

```text
POST /api/intake/files
Content-Type: multipart/form-data
```

Fields:

```text
files[] = image1.jpg
files[] = image2.jpg
files[] = pattern.pdf
payload = JSON metadata
```

Example payload:

```json
{
  "workspaceSlug": "mash-burn",
  "intent": "bench_note",
  "title": "Pocket shape idea",
  "notes": "These photos are for a possible bench note.",
  "suggestedEntryType": "bench-note",
  "suggestedCollections": ["on-the-bench"]
}
```

Response:

```json
{
  "intakeId": "...",
  "status": "needs_review",
  "assets": [
    {
      "id": "...",
      "filename": "image1.jpg",
      "contentType": "image/jpeg"
    },
    {
      "id": "...",
      "filename": "pattern.pdf",
      "contentType": "application/pdf"
    }
  ],
  "reviewUrl": "https://marvin.example.com/intake/..."
}
```

### Storage Direction

Use local storage for v1.

Suggested layout:

```text
storage/
  workspaces/
    {workspace_slug}/
      intake/
        {intake_id}/
          original/
          processed/
```

Design so S3/R2/MinIO can replace local disk later without changing API contracts much.

### Intake Upload Behavior

Endpoint should:

- Require authentication.
- Use active workspace/group context unless workspace slug is explicitly allowed.
- Accept multiple files.
- Store files in workspace-scoped storage.
- Create asset records.
- Create an intake record.
- Associate uploaded assets with intake.
- Set intake status to `needs_review`.
- Emit events.
- Return intake id, asset summaries, status, and review URL.

It should not:

- Publish content.
- Create final entries automatically.
- Auto-approve AI output.

## Events and Webhooks

Intake should integrate with Marvin's existing event/webhook system.

Suggested event types:

```text
intake.created
intake.files_uploaded
intake.parsed
intake.entry_created
intake.needs_review
intake.rejected
asset.uploaded
entry.created
entry.published
```

Example event payload:

```json
{
  "event": "intake.created",
  "workspace": "mash-burn",
  "intakeId": "...",
  "title": "Pocket shape idea",
  "status": "needs_review",
  "reviewUrl": "https://marvin.example.com/intake/...",
  "createdAt": "..."
}
```

Webhook flow:

```text
Intake created
  -> Marvin emits event
  -> Webhook fires to n8n
  -> n8n sends Slack/email/mobile notification
  -> User clicks review link
  -> User parses, rejects, merges, or creates entry
```

n8n can also:

- Create Airtable rows.
- Send notifications.
- Trigger AI parsing.
- Create GitHub issues.
- Queue social draft workflows.

But Marvin remains the authority.

## n8n / External Automation Workflow

Example automation:

```text
User sends quick note or uploads images
  -> n8n receives input
  -> n8n builds JSON payload
  -> n8n calls Marvin Intake API
  -> Marvin creates intake draft
  -> Marvin emits intake.created
  -> n8n receives webhook
  -> n8n notifies user with review URL
```

Airtable or any external system can participate, but external approval should only be allowed if explicitly designed.

Default rule:

```text
External systems create drafts.
Marvin users approve/publish.
```

## AI Parsing / Enrichment

AI should be optional and review-driven.

Possible flow:

```text
Intake Item
  -> click Parse Draft
  -> AI suggests title, slug, entry type, collections, resources, summary, body, tags, publishing ideas
  -> User reviews
  -> User creates Entry
```

AI may suggest:

- Entry type.
- Collection membership.
- Resources.
- Asset roles.
- Alt text.
- Focal point.
- Description.
- Summary.
- Draft Markdown.
- Social captions.
- Publishing targets.

AI should not auto-publish.

## Publishing Targets / Social Ideas

Marvin should eventually support publishing target suggestions.

Examples:

```text
Website
Instagram
Pinterest
Newsletter
RSS
PDF
YouTube
```

AI or automations may suggest:

```json
{
  "suggestedPublishingTargets": ["website", "instagram"],
  "socialIdeas": [
    {
      "target": "instagram",
      "captionDraft": "Working through pocket shape ideas for the black denim jacket...",
      "assetIds": ["..."]
    }
  ]
}
```

These remain drafts/suggestions until approved.

## Admin UI Changes Needed

Eventually add primary/secondary UI sections for:

### Content

- Entries
- Collections
- Assets
- Resources
- Intake Inbox

### Workspace

- Settings
- Members
- Entry Types
- Publishing
- Automation

### Automation

Possibly nested under Workspace:

- Events
- Webhooks
- Notifications
- Scheduler

### Intake Inbox UI

Suggested intake screen:

```text
Inbox / Intake
  - Title
  - Source
  - Intent
  - Status
  - Files count
  - Suggested entry type
  - Suggested collections
  - Created at
  - Actions
```

Intake detail:

```text
Header:
  Title
  Status
  Source
  Actions: Parse Draft, Create Entry, Merge, Reject

Main:
  Raw text / payload
  AI suggestions
  Draft preview

Sidebar:
  Assets
  Suggested metadata
  Suggested collections
  Events/history
```

## Implementation Order

Recommended phased work:

### Phase 1: SDK/OpenAPI foundation

- Generate SDK types from OpenAPI.
- Split SDK into core/publish/admin modules or subpath exports.
- Ensure admin UI can consume SDK gradually.
- Ensure CLI consumes SDK.

### Phase 2: Publish SDK completeness

- Add resources to publish API contract.
- Add site, entries, collections, resources, assets to publish SDK.
- Make Mash & Burn Co. consume publish SDK.

### Phase 3: Admin SDK migration

- Move admin UI API calls into SDK modules.
- Start with Entries/Collections/Resources.
- Then Workspace/Settings/Members.
- Then Events/Webhooks/Notifications.

### Phase 4: CLI reference implementation

- Keep `marvinctl` under `apps/cli`.
- Ensure it supports table/json/yaml/csv.
- Add workspace, entries, collections, resources, assets commands.
- Later add intake commands.

### Phase 5: Intake data model

- Add intake tables.
- Add intake statuses.
- Add intake API.
- Add intake events.

### Phase 6: Intake uploads

- Add multipart upload endpoint.
- Store files locally in workspace-scoped storage.
- Create asset records.
- Associate assets with intake.
- Emit events.

### Phase 7: Intake UI

- Add Intake Inbox.
- Add intake detail/review page.
- Add parse/create/merge/reject actions.

### Phase 8: AI parsing

- Add parse endpoint/service.
- Store suggestions.
- Keep human approval.

### Phase 9: n8n/webhook workflows

- Add event payloads with review URLs.
- Document n8n examples.
- Add webhook templates.

### Phase 10: Social/publishing suggestions

- Store suggested targets.
- Generate captions/drafts.
- Keep approval manual.

## Open Questions

- Should intake items have their own table, or should they be entries with a special status? Current recommendation: separate intake table.
- Should files become assets immediately, or remain temporary intake files until approved? Current recommendation: create asset records immediately but mark them intake-scoped/unpublished.
- Should site client tokens be allowed to read resources? Current recommendation: yes, published resources only.
- Should n8n be allowed to create entries directly? Current recommendation: only drafts, not approved/published.
- Should AI parse automatically after intake? Current recommendation: no by default; maybe optional per workspace automation later.

## Safety / Approval Boundary

The core boundary:

```text
Automation can create drafts.
AI can suggest.
Humans approve.
Marvin publishes.
```

Do not break this boundary without an explicit workspace-level setting and clear audit trail.

