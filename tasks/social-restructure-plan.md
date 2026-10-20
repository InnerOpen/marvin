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
6. **Instagram clean-up** (changed 2026-10-21, see the phase 2 review: Jared dropped the conversion):
   - ~~Convert `ig-auto-reply` rules to `social-auto-reply` rules, preview then apply.~~ Dropped.
   - ~~Mark the `ig-*` types internal; keep reading them.~~ Dropped.
   - The plugin stops shipping the `ig-*` types, the "Social —" collections and its auto-reply task (a plugin release), and core
     removes the leftovers and its legacy reading.

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
2. Instagram: the plugin release dropping its own collections/types/task, and core dropping its legacy reading plus a
   one-off clean-up migration (no conversion; see the phase 2 review).

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

## Review, phase 2 (2026-10-22)
- **Scope change, Jared 2026-10-21:** "nothing is live or important... [no] need to worry about existing content". The planned
  conversion (preview, apply on OK, the API pair, the network-page notice and dialog) was **dropped before it was built**, and so
  were "never delete" and "keep as history" for the old Instagram data. **Legacy compatibility was removed by Jared's decision**:
  core no longer reads anything of the plugin's own auto-reply, and the leftovers are deleted.
- **Core, removed:**
  - `ig-auto-reply` entries are no longer rules (`social_rules.rule_from_data` has no legacy mode, `SocialRule.legacy` is gone,
    `load_rules` reads `social-auto-reply` only, `social_rule_entries` lists only that type, `GET /rules` has no `legacy` field).
  - Dedupe is **inbox items only**. `ig-reply-log` and, by my choice, `social-reply-log` entries are no longer read (`log_slug`,
    `_legacy_answered` and the `legacy` argument are gone). `social-reply-log` was droppable because the phase 1 migration copied what
    the replies view needs onto the items, and items answered under the old log already carry `replied_at`.
  - The "skip replies while the plugin's own `auto_reply` task is enabled" check is gone (`plugin_task_enabled` no longer exists).
    An enabled leftover task no longer holds the engine back.
  - `INTERNAL_SLUGS` is now `social-auto-reply` and `social-reply-log`. The `ig-*` slugs are dropped (the migration removes those
    entries); `social-reply-log` stays so leftover entries of a workspace that ran the early engine don't reappear in All entries.
    The frontend list (`entryTypeListing.ts`) matches, and the Rules tab no longer marks "Instagram rule" rows.
  - Kept, not Instagram: `social_setup.map_legacy_rehearsal` (the old task-wide `rehearsal` setting) and the `reply_log_slug` column
    (unused now; dropping it is a schema change not worth making here).
- **Core, the clean-up: a data migration** (`b8d4e2f61a73`, after `ef911a9c1779`), not an admin command. It must happen once, for every
  workspace, on the deploy that stops reading these types, and a command would have to be remembered. It uses plain table statements
  (so no model drift, same style as `ef911a9c1779`), is idempotent, and its downgrade does nothing (no schema change, nothing to rebuild).
  It removes only:
  - the entries of the exact types `ig-auto-reply` / `ig-reply-log` with their tag, asset, resource, snapshot and collection links and
    embeddings, then the two types;
  - the collections `social-auto-responses` / `social-sent`, only when each is a smart collection over its own `ig-*` type (the
    sidebar's "Instagram" group is drawn from the collections an integration installed, so it disappears with them);
  - the scheduled task `instagram-auto-reply`, only a `run_integration_action` task whose action is `auto_reply`, with its run log.
    `instagram-token-refresh` and every other task, collection, entry and type are untouched.
  - Tested on PostgreSQL and SQLite (exact removal in two workspaces, a second run changes nothing, lookalikes left alone, a workspace
    without them untouched, upgrade/downgrade/upgrade, single head).
- **What happens to an existing workspace when the plugin stops shipping blueprints.** Blueprints are not stored: the catalogue is read live
  from the installed providers' `content` (`blueprints/catalog.py`), and applying one creates ordinary rows stamped with
  `source_integration_id` / `source_blueprint`. A blueprint that disappears from a provider just stops being offered; nothing checks or
  removes what it made, the `required` flag is only used while listing, and `update_blueprint` / `get_blueprint` for the old slug
  find nothing. So a workspace on the new plugin keeps whatever it had until this migration removes it.
- **Instagram plugin 0.8.0** (own repo, committed, not tagged): ships only the token-refresh blueprint; the `auto_reply`,
  `list_recent_comments` and `send_private_reply` actions and `matching.py` are **removed**, not deprecated, because nothing in core,
  the recipes, the catalogue or the docs used them (the catalogue note and docs that named them are updated); README, guide and tests
  updated.
- **Open:**
  - Core's `pyproject.toml` still pins `marvin-integration-instagram@v0.7.0`. It stays until v0.8.0 is tagged and pushed, then the pin
    and `uv.lock` need bumping.
  - Until that bump the baked-in plugin is 0.7.0, which still offers the old blueprints and actions; core ignores what they make.
  - A deployment that applies the old blueprints again after the migration gets leftovers the migration won't remove a second time (it
    runs once); update the plugin first.
  - The phase 1 open points are unchanged (the editor's Back link, no per-network rules shortcut on the editor, a second reply replaces the
    first record, an integration recreated with the same slug loses its replied items).
