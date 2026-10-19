# Marvin Intake Pipeline Plan

## Purpose

Marvin should not require users to spend all their time inside the admin UI.

The admin UI is for review, editing, approval, and management.

The Intake Pipeline is for quickly capturing raw ideas, files, notes, images, documents, and automation-generated content so Marvin can turn them into structured drafts later.

External systems may create intake items and drafts.

Only Marvin users approve and publish.

## Core Rule

```text
External automations may create intake items and drafts.
Only Marvin users approve or publish.
```

No AI workflow, n8n workflow, CLI command, or external API client should automatically publish content unless a future explicit trusted workflow is designed for that purpose.

## Big Picture Flow

```text
Voice note / image upload / PDF / n8n / Airtable / CLI / SDK
  ↓
Marvin Intake API
  ↓
Intake Item created
  ↓
Assets attached
  ↓
Event emitted
  ↓
Webhook / notification / n8n trigger
  ↓
Human reviews in Marvin
  ↓
Parse / enrich / merge / create Entry
  ↓
Approve / publish
```

## Concepts

### Intake Item

An Intake Item is raw incoming material.

It is not final content.

It is safe to reject, delete, merge, or parse later.

Examples:

- A quick note from n8n
- A voice note transcript
- A set of workshop photos
- A PDF pattern
- A pasted JSON payload
- A browser-captured URL
- An Airtable row
- A batch of ideas collected by automation

Suggested fields:

```text
intake_items
  id
  group_id
  created_by_id
  source
  intent
  title
  raw_text
  payload_json
  suggested_entry_type
  suggested_collections_json
  status
  review_url
  created_at
  update_at
```

Suggested statuses:

```text
received
needs_review
parsed
entry_created
merged
rejected
archived
```

### Asset

An Asset is a file Marvin knows about.

Examples:

- Image
- PDF
- Audio
- Video
- SVG
- Source file
- Pattern file
- Document

Assets may be attached to Intake Items first, and later attached to Entries, Resources, or Collections.

Suggested fields:

```text
assets
  id
  group_id
  filename
  original_filename
  content_type
  size_bytes
  storage_path
  public_url
  alt_text
  metadata_json
  created_at
  update_at
```

### Intake Asset Join Table

```text
intake_assets
  intake_id
  asset_id
  role
  sort_order
  created_at
  update_at
```

Possible roles:

```text
source
hero_candidate
gallery_candidate
reference
pattern
document
audio
```

## API Endpoints

### Create Intake Item from JSON

```http
POST /api/intake
Content-Type: application/json
```

Example request:

```json
{
  "source": "n8n",
  "intent": "bench_note",
  "title": "Pocket shape idea",
  "rawText": "This pocket shape might work for the black denim jacket.",
  "payloadJson": {
    "context": "Captured from mobile note",
    "desiredOutputs": ["website", "instagram"]
  },
  "suggestedEntryType": "bench-note",
  "suggestedCollections": ["on-the-bench"]
}
```

Expected behavior:

- Require authentication or trusted API token.
- Resolve active workspace/group.
- Create Intake Item.
- Set status to `needs_review`.
- Emit `intake.created`.
- Return Intake Item summary and review URL.

### Bulk Intake from JSON

```http
POST /api/intake/bulk
Content-Type: application/json
```

Purpose:

Accept a list of intake items.

Useful for:

- n8n batch jobs
- Airtable syncs
- importing ideas
- migration tools

### File Intake Upload

```http
POST /api/intake/files
Content-Type: multipart/form-data
```

Form fields:

```text
files[] = image1.jpg
files[] = image2.jpg
files[] = pattern.pdf
payload = JSON metadata string
```

Example payload:

```json
{
  "source": "cli",
  "intent": "project",
  "title": "Black Denim Jacket",
  "rawText": "Photos and notes for a black denim jacket project.",
  "suggestedEntryType": "project",
  "suggestedCollections": ["projects", "on-the-bench"]
}
```

Expected behavior:

- Require authentication or trusted API token.
- Resolve active workspace/group.
- Accept multiple files.
- Store files in workspace-scoped storage.
- Create Asset records.
- Create Intake Item.
- Attach uploaded Assets to Intake Item.
- Set Intake Item status to `needs_review`.
- Emit `intake.created`.
- Emit `asset.uploaded` for each uploaded file.
- Return Intake Item summary, Asset summaries, status, and review URL.

Example response:

```json
{
  "intakeId": "...",
  "status": "needs_review",
  "reviewUrl": "https://marvin.example.com/intake/...",
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
  ]
}
```

### List Intake Items

```http
GET /api/intake
```

Filters:

```text
status
source
intent
created_after
created_before
```

### Get Intake Item

```http
GET /api/intake/{id}
```

### Update Intake Item

```http
PATCH /api/intake/{id}
```

### Delete / Archive Intake Item

```http
DELETE /api/intake/{id}
```

Prefer archive if deletion would remove useful audit history.

## Review Actions

These should be admin UI actions backed by API endpoints.

### Parse Draft

```http
POST /api/intake/{id}/parse
```

Purpose:

Run AI or deterministic parsing against the intake item.

Expected behavior:

- Read raw text, payload JSON, and assets.
- Suggest Entry Type.
- Suggest title, slug, summary, description, content markdown.
- Suggest Collections.
- Suggest Resources.
- Suggest Assets roles.
- Do not publish.
- Store parse result for review.
- Emit `intake.parsed`.

### Create Entry from Intake

```http
POST /api/intake/{id}/create-entry
```

Purpose:

Create a real Marvin Entry from reviewed intake.

Expected behavior:

- Create Entry with status `draft`.
- Attach selected Collections.
- Attach selected Assets.
- Optionally create suggested Resources.
- Set Intake Item status to `entry_created`.
- Emit `intake.entry_created`.
- Return Entry ID and Entry URL.

### Merge Into Existing Entry

```http
POST /api/intake/{id}/merge
```

Purpose:

Merge intake material into an existing Entry.

Expected behavior:

- Attach notes/assets/resources to an existing Entry.
- Keep audit reference back to Intake Item.
- Set Intake Item status to `merged`.
- Emit `intake.merged`.

### Reject Intake

```http
POST /api/intake/{id}/reject
```

Purpose:

Mark intake as rejected.

Expected behavior:

- Set status to `rejected`.
- Do not delete assets automatically unless explicitly requested.
- Emit `intake.rejected`.

## Events

Add event types:

```text
intake.created
intake.parsed
intake.entry_created
intake.merged
intake.rejected
asset.uploaded
```

Event payload should include:

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

These events allow:

- n8n workflows
- Slack notifications
- email notifications
- webhook callbacks
- AI processing queues
- review reminders

## Webhook / n8n Flow

Example:

```text
Intake created
  ↓
Marvin emits intake.created
  ↓
Webhook fires to n8n
  ↓
n8n sends notification
  ↓
User clicks review URL
  ↓
User reviews in Marvin
```

Possible n8n actions:

- Send Slack message
- Send email
- Create Airtable row
- Add task to Todoist
- Start AI parse job
- Log intake to Google Sheets

## Storage Strategy

Start simple.

Local storage is acceptable for v1.

Suggested path:

```text
storage/
  workspaces/
    {workspace_slug}/
      intake/
        {intake_id}/
          original/
          processed/
```

Examples:

```text
storage/workspaces/mash-burn/intake/abc123/original/image1.jpg
storage/workspaces/mash-burn/intake/abc123/original/pattern.pdf
```

Design the storage service so local disk works now, but S3, R2, or MinIO can be added later.

## SDK Direction

The broader Marvin SDK should include intake support.

Examples:

```ts
await marvin.intake.create({
  source: "n8n",
  intent: "bench_note",
  title: "Pocket shape idea",
  rawText: "This pocket shape might work for the black denim jacket.",
  suggestedEntryType: "bench-note",
  suggestedCollections: ["on-the-bench"]
});
```

File upload example:

```ts
await marvin.intake.uploadFiles({
  title: "Black Denim Jacket",
  intent: "project",
  files,
  rawText: "Photos and notes from the workshop.",
  suggestedEntryType: "project",
  suggestedCollections: ["projects"]
});
```

## CLI Direction

The CLI should expose intake commands.

Examples:

```bash
marvinctl intake create \
  --title "Pocket shape idea" \
  --intent bench_note \
  --collection on-the-bench \
  --text "This pocket shape might work..."

marvinctl intake upload \
  --title "Black Denim Jacket" \
  --intent project \
  --collection projects \
  --files ./photos/*.jpg

marvinctl intake list --status needs_review
marvinctl intake get <id>
marvinctl intake parse <id>
marvinctl intake create-entry <id>
marvinctl intake reject <id>
```

## Admin UI Direction

Add an Intake area to the admin UI eventually.

Suggested location:

```text
Content
  Inbox
```

The Inbox page should show:

- Intake title
- Source
- Intent
- Status
- Suggested entry type
- Suggested collections
- Asset count
- Created date
- Review actions

Review actions:

- Parse Draft
- Create Entry
- Merge Into Existing Entry
- Reject
- Archive/Delete

## Implementation Order

Do not build everything at once.

Recommended order:

1. Add docs and schema plan.
2. Add Intake Item and Asset models/migrations.
3. Add JSON intake endpoint.
4. Add file upload intake endpoint.
5. Emit intake and asset events.
6. Add list/detail/update/reject endpoints.
7. Add SDK intake methods.
8. Add CLI intake commands.
9. Add basic admin Inbox UI.
10. Add parse/create-entry/merge workflows.
11. Add AI enrichment.
12. Add publishing target suggestions.

## Definition of Done for v1

A minimal v1 is complete when:

- API can create an Intake Item from JSON.
- API can upload multiple files and attach them to an Intake Item.
- Intake Items are scoped to the active workspace/group.
- Assets are stored and recorded.
- No content is published automatically.
- Events are emitted.
- Intake Items can be listed and reviewed.
- SDK and CLI can create/list intake items.

## Non-Goals for v1

Do not implement these in the first pass:

- Auto-publishing
- Full AI parsing
- Social media automation
- Pinterest/Instagram posting
- Advanced asset processing
- S3/R2 storage backend
- Knowledge graph UI

These should be designed for, but implemented later.
