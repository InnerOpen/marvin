# Social: its own space, not an integration (2026-10-20)

Jared, after phase 3 shipped: Social isn't an integration. A "Social" thing on the Integrations page with no card or
icon looks pre-configured and random, and it shouldn't be front and center (or in the sidebar) when the workspace has no
social network. It's like SMTP or Storage. Rules and inboxes should be per network. "Its technically a collection is it
not?" Rule entries and log entries also flood All entries. Decided: "yes, plan it that way".

## The shape
```
Collections   v
   Featured
   Workshop notes
   Social          v          ← only when an enabled integration offers a social.* capability
      Inbox (4)               ← all networks
      Instagram               ← Inbox · Rules · Replies · Auto-reply: off / rehearsal / on
      Mastodon
```
- **Integrations page:** connection cards only. The Social engagement card is removed.
- **Social** is drawn as a system collection group under Collections in the sidebar, hidden when no connected integration
  offers `social.comments` / `social.post` / another `social.*` capability. One page per connected network, plus the
  all-networks Inbox.
- **Each network's page:**
  - **Inbox:** that network's items (the existing inbox, filtered).
  - **Rules:** that network's rules plus "all networks" rules (marked).
  - **Replies:** what was sent there.
  - **Auto-reply switch:** off | rehearsal | on, per network.
- **The all-networks Inbox:** every item, filterable, as today.

## Data
1. **Rules stay entries** (`social-auto-reply`: drafts, publish to activate, history), but the type is **internal**:
   - hidden from All entries, the status lists (Drafts, Published…), their counts, search, the dashboard and the AI
     content index;
   - edited only through Social › network › Rules (the existing entry editor, reached from there);
   - not publishable (already `publishable: false`).

   Implement "internal" as an entry-type capability flag (e.g. `capabilities_json.listed: false`) honoured everywhere
   entries are listed, counted or indexed. Audit every list, count, search and embedding path.
2. **Rules per network:**
   - The `networks` field holds the integration slug(s); empty means all networks.
   - A rule made from a network's page defaults to that network, with "apply to every network" as an option.
   - Matching precedence: a rule for this post, then a network-specific rule, then an all-networks rule, then the
     oldest first.
3. **The reply log stops being entries.**
   - Replies are recorded on the inbox item: the columns phase 3 added (`reply_mode`, `reply_rehearsal`, `reply_id`,
     `replied_at`, `replied_by`), plus the rule that fired.
   - A reply the engine sends for a comment not yet in the inbox inserts the item first. Every reply now has an item.
   - Dedupe moves from `social-reply-log` entries to inbox items (a live reply on the item means answered), and still
     honours legacy `ig-reply-log` and any existing `social-reply-log` entries.
   - The 30-day prune must not forget a reply too early: keep replied items longer, or keep a small answered-ids record.
     Decide in the build. The engine only answers items under 7 days old anyway, so the risk is small.
   - Replies view = inbox items with a reply, filtered by network and live/rehearsal.
4. **Per-network auto-reply mode:**
   - Stored with the integration (`integrations.state.social.auto_reply`, off | rehearsal | on, default off), replacing
     the task-wide `rehearsal` arg.
   - The `social-engagement` scheduled task becomes plumbing: created and enabled automatically while any network has
     the inbox/announcing or auto-reply on, and not shown as something to set up. The inbox still fills (and the
     new-comment trigger still fires) for every connected network that reads comments, whatever its auto-reply mode.
5. **No setup step:**
   - The rule type and whatever plumbing is needed are created automatically when the first social-capable integration
     is connected, or on first visit to Social.
   - The core "Social" blueprint set and its collections (`social-auto-reply-rules`, `social-replies`) are retired from
     view. The `social-reply-log` type is no longer needed for new data. Keep or hide the existing ones; never delete
     content.
6. **Instagram clean-up:**
   - Convert `ig-auto-reply` rules to `social-auto-reply` rules for that Instagram integration. Preview first, then
     apply on Jared's OK.
   - Mark the `ig-*` types internal like the shared ones (so `IG Reply Log` leaves All entries and Published).
   - Disable the plugin's own auto-reply task once Instagram's mode is set.
   - The plugin stops shipping the "Social —" named collections and `ig-*` types on new installs (a plugin release;
     legacy reading stays in core).

## UI
- Sidebar: the Social group under Collections, with the Inbox badge (count of new) on Social and on Inbox.
- The network page has tabs: Inbox · Rules · Replies, and the auto-reply switch in its header, with a one-line
  explanation of rehearsal.
- Rule editor: keywords, reply, private/public/both, also like, kinds (comment/reply/mention), networks (this one or
  all).
- Phone: compact rows, tap to open (Jared's list preference).
- Remove the Social engagement card and its lib/tests from Integrations. The inbox page moves under the new routes
  (`/workspace/social`, `/workspace/social/<integration>`).

## Tests and docs
- Tests:
  - the internal type hidden from every list, count, search and index path;
  - per-network precedence;
  - dedupe through inbox items (plus legacy logs);
  - the per-network modes;
  - automatic plumbing and Social hidden without social integrations;
  - the Instagram conversion preview and apply.
- Docs: the integrations manual (Social moves out), a Social section, the workflows manual, the authoring guide.

## Phases
1. Core: the internal flag and its audit, per-network modes, reply log on inbox items, precedence, automatic plumbing,
   sidebar/Social pages, Integrations card removed. Ship.
2. Instagram: conversion (preview → apply on OK), legacy types internal, the plugin release dropping its own
   collections/types.

## Decisions for Jared
(none open: the shape, rules-as-internal-entries, the log on inbox items, per-network rules with all-network rules and
precedence, and conversion with a preview were agreed in conversation 2026-10-20)

## Review, phase 1 (2026-10-21)
- **Built:**
  - **Internal types.** `capabilities.listed: false`, with the core slug rule (`services/entry_listing.py`), applied to `social-auto-reply`,
    `social-reply-log`, `ig-auto-reply` and `ig-reply-log`.
  - **Rules per network.** `networks` holds integration slugs, empty means every network, and the precedence is post, then network, then all
    networks, then oldest (`social_rules.specificity`).
  - **Replies on items.** Replies are recorded on `social_inbox_items` (`reply_rule`, `reply_text`, `reply_note` added; migration `ef911a9c1779`).
    The engine inserts an item first when it replies to one it hasn't stored. Dedupe reads items plus the legacy log entries.
  - **Per-network auto-reply.** `integrations.state.social.auto_reply` is off, rehearsal or on, and an old task `rehearsal` setting is mapped once.
  - **Automatic plumbing** (`social_setup.py`):
    - The rule type is created on first need.
    - The engine task is created and enabled while a network reads comments, and disabled when none does.
    - A new hourly `reconcile_social_engagement` system task keeps every workspace in step.
    - The integration create, update and delete routes reconcile at once.
  - **UI.**
    - The sidebar group sits under Collections.
    - Social has its own routes: `/workspace/social` and `/workspace/social/<integration>` with Inbox, Rules and Replies tabs and the auto-reply switch.
    - The Integrations card and its lib are gone.
    - Internal types are left out of the New menu, Quick Create and the New entry type picker.
  - **API and docs:** details below and in the new Social manual page.
- **Internal-flag audit, changed:**
  - Entry lists and counts: `GET /entries`, `/entries/counts` (sidebar), the Trash count (`trashed_ids(listed_only)`), the app badge (`push_actions.inbox_count`).
  - Queries and tools:
    - `entries/query.build`, which covers `/entries/query`, find_entries, MCP `search`'s title fallback, workflow targets and the bulk tools.
    - The assistants' `workspace_overview` and `get_collection_entries`.
  - Collections:
    - `matches_rules` for smart collections (so Inbox, Drafts, Needs review, Approved, Published, Archive and Trash never hold them).
    - Collection pages (`/collections/{id}/entries`).
    - Related entries in the AI context.
  - Dashboard:
    - Pipeline by type.
    - Oldest in a status.
    - Upcoming.
    - Published by week.
    - "Recent for you".
    - Stats counts.
  - Search and AI:
    - Semantic search and the AI index (`REGISTRY['entry']` `content_ok` and `should_index`).
    - A defensive filter in `search_embeddings` and `search_content`.
  - Publishing: `is_publishable_type` is false for an internal type (the publishing API, site rebuilds, tags).
  - Query rule: a spec that names the type (`entry_type`) or the entry (`entries`) still finds internal entries; anything else never does.
- **Left deliberately:**
  - Admin and diagnostic counts (`admin_overview`, `database_report`, `workspace_admin`, maintenance).
  - Emptying the Trash still deletes internal entries.
  - Workflow event triggers (`entry_published` and so on) still fire for internal entries, so a trigger with no type filter sees a published rule.
  - Workflow sample events.
  - Manual collections that a person filled keep their membership (only smart membership is derived and cleaned); the collection page and list endpoints
    hide internal entries from them unless the collection's rules name the type.
  - The Entries page's type filter still offers the type (naming it finds the rules).
  - A trashed rule leaves every status list, including the Trash, so it can't be restored from there.
- **Decisions of mine:**
  - Internal by flag plus a slug rule, with no data migration of entry types. The rule covers existing legacy types and later plugin installs, and the
    flag is on the blueprint payload.
  - The migration cleans derived data: smart-collection memberships, embeddings, and the two retired collections.
  - Retired collections are removed only if pristine and empty (a smart collection's membership is derived, so no entry is touched); otherwise they are
    taken off the sidebar.
  - Prune: the engine's window is clamped to 90 days, and an item with a live reply is kept 180 days.
  - `announce` is gone from the task config: the inbox and the trigger always run. Social is placed alphabetically among the integration groups.
- **API changes** (under `/api/groups/social-inbox`, SDK not touched):
  - New:
    - `GET /replies`
    - `GET /rules`
    - `POST /rules`
    - `PUT /rules/{id}/published`
    - `PUT /integrations/{slug}/auto-reply` (ADMIN)
    - `GET /summary?visit=true`
  - Changed:
    - `/summary` is now `{show, new, integrations[…autoReply, readsComments, canReply, provider, new], can}`; `available` and `engine` are gone.
    - A reply is `{mode, rehearsal, replyId, text, rule, ruleEntryId, note, at, by, byName}`; `logSlug` and `logEntryId` are gone.
    - The reply result has no `logged`.
    - Make a rule uses the integration's slug and no longer answers 409.
  - The scheduled-task type `reconcile_social_engagement` is new.
- **Open:**
  - Phase 2 is untouched: the Instagram conversion preview and apply, and the plugin release.
  - The entry editor's Back link goes to All entries, not to the network's Rules tab.
  - There is no "this network's rules" shortcut on the editor.
  - A person's second reply to an item replaces the first record.
  - An integration recreated with the same slug loses its replied items, because dedupe keys on the integration id (only the 7-day window protects it).
