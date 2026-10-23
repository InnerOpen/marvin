# Social Inbox: every kind of item, as it happens (webhooks into the inbox)

Status: **built and shipped** (2026-10-23) — integration SDK 0.18.0, Instagram 0.11.0, migration e2c7f4a9b815

## Why

The Social Inbox is written only by the 5-minute engagement poll (`social_engagement.py` → `persist_items`), and holds three
kinds: comment, reply, mention. Meta's webhooks (live since today: Instagram webhooks, verified, signed) carry more —
DMs, story replies and mentions, reactions, live comments — and carry them as they happen. A workflow on the webhook sees
them; the inbox never does. Jared: "Kind should probably include Messages, or whatever else it can."

Rule (Brain, Marvin CMS): **capability in core, the "how" in the integration.** Core never reads Meta's payload.

## Kinds (core vocabulary — generic social concepts, not Meta's names)

| Kind | What it is | Instagram source (the plugin maps it) |
|---|---|---|
| `comment` | someone commented on your post | `comments` (no parent) — and the poll, as now |
| `reply` | a reply in a comment thread | `comments` with `parent_id` — and the poll |
| `mention` | someone @-mentioned you (caption or comment) | `mentions` — webhook only; polling can't |
| `message` | a direct message to the account (text, a shared post or reel, a picture) | `messages` |
| `story_reply` | someone replied to your story (arrives as a DM) | `messages` with `reply_to.story` |
| `story_mention` | someone mentioned you in their story | `messages` attachment `story_mention` |
| `reaction` | someone reacted to your message | `message_reactions` |
| `live_comment` | a comment on your live video | `live_comments` |

Not inbox items: `message_echoes` (the account's own messages), `messaging_seen` (read receipts), `messaging_postbacks`,
`story_insights` — the plugin returns nothing for them (the workflow still gets the delivery).

A message's extras ride on the item as `attachments` (each `{type, url, title}`; e.g. a shared post: its picture link and
its caption as `title`), so the inbox can show "shared a post: <caption>" with the picture.

## What changes

### 1. Integration SDK (0.18.0)
- Optional provider method `inbox_items_from_webhook(ctx, payload, headers) -> list[dict]`: a delivery to the integration's
  own webhook, turned into inbox items in the same normalised shape `comments` returns (`id`, `kind`, `author_*`, `text`,
  `post_id`, `url`, `posted_at`, plus `attachments`). Default: none (nothing changes for any other plugin).
- The kind list documented, so plugins use core's names.

### 2. Core (Marvin)
- `ITEM_KINDS` gains `message`, `story_reply`, `story_mention`, `reaction`, `live_comment`. Unknown kinds still fold to
  `comment` (as now). New nullable `attachments` (JSON) on `social_inbox_items` — one migration.
- Incoming-webhook receiver: when the webhook was created by an integration's blueprint (`source_integration_id`) and that
  provider implements the hook, after the signature passes it hands the payload over and stores the items through the same
  `persist_items` (deduplicated with the poll on integration + item id; the account's own items skipped as now). Best effort:
  a parsing failure is logged and never fails the delivery; workflows on the webhook start exactly as today.
- The auto-reply engine is unchanged for the new kinds: a rule answers only the kinds in its `kinds` field (which defaults to
  comment kinds), so DMs are never auto-answered unless a rule says so. (Answering a message would use the network's
  message action — out of scope here; listed below.)

### 3. Instagram plugin (0.11.0)
- Implements `inbox_items_from_webhook` for the table above (a delivery can hold several entries/events → several items).
- Tests against the real payload shapes received today (DM text, shared `ig_post` with caption, Meta's sample comment).

### 4. Inbox page (frontend)
- Kind filter and labels for the new kinds; a message row shows its attachments (picture thumbnail, a shared post's
  caption, a link to open it).
- Replying to a `message` from the inbox: uses the plugin's existing send-message action (the inbox already has
  "message the author" for comments) — the reply recorded on the row as for comments.

### Facebook later
The same SDK hook in the Facebook plugin (Page comments, Messenger) is a follow-up; nothing here is Instagram-only in core.

## Verification
- Core tests: a blueprint webhook with a provider implementing the hook stores items; a plain webhook stores none; a bad
  signature stores none; a parser exception doesn't fail the delivery; dedupe against a poll-stored item; new kinds filter.
- Plugin tests from today's real payloads. SDK test for the default.
- Live: DM a post → it appears under Social → Instagram → Inbox as a Message with the caption and picture; the ideas
  workflow still runs.

## Out of scope (ask later)
- Auto-reply to DMs (rules with `kinds: [message]` answering via message).
- Reactions/likes on your posts (Instagram sends no webhook for post likes).
