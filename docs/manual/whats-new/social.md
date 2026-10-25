# Social

Social is where a workspace reads and answers the comments on its social networks: one **Inbox** across every network, and one page per network with its **Rules**, its **Replies** and an **auto-reply** switch. It is not an integration. A network's plugin (Instagram, a Facebook Page, Mastodon, Bluesky) declares `social.*` capabilities, and Marvin draws Social only while the workspace has something that uses it: an enabled integration that offers any `social.*` capability. With none, Social isn't in the sidebar and its pages say so and link to Integrations. The Integrations page holds connection cards only.

There is nothing to set up. The rule type and the engine's task are made by Marvin when they are first needed (see [What Marvin makes](#what-marvin-makes)).

## Where it is {#where}

In the sidebar, under **Audience** (after Content; Collections hold only entries and content), a **Social** group with a count of the items still new. The Audience heading is drawn only while a connected network works with Social. Social folds open to:

- **Inbox**: every network's items (`/workspace/social`), with the new count;
- **one entry per connected network**, with its logo and name (`/workspace/social/<integration slug>`), and its own new count.

**Settings › Social** (`/workspace/settings/social`, also only while a network is connected) lists every network with its auto-reply switch and says how long Social keeps comments. It's the overview beside the network pages.

A network's page has the **auto-reply switch** in its header and three tabs: **Inbox** (that network's items), **Rules** and **Replies** (`?tab=rules`, `?tab=replies`). Editors and above can open Social; admins change the switch.

On a phone every list is compact rows, one per item, and tapping a row opens it (the whole text and its actions, a rule with Edit and Publish, a reply with what was sent). Nothing is stacked into cards.

## Auto-reply, per network {#auto-reply}

Each network has its own switch, stored on the integration (`integrations.state.social.auto_reply`): **off** (the default), **rehearsal** or **on**.

- **Off.** Nothing is answered. The network is still read, so its inbox fills and workflows can start on `social_comment_received`.
- **Rehearsal.** Published rules run as a dry run: the plugin is asked what it would send (`dry_run: true`, nothing is sent) and the reply is recorded on the item as a rehearsal. A rehearsal never counts as "answered", so switching to **on** still answers what is inside the window.
- **On.** Published rules reply on their own, as written, once per comment.

An admin changes it with the switch on the network's page (or `PUT /api/groups/social-inbox/integrations/{slug}/auto-reply`). A network whose plugin can't reply stays off. Instagram has no auto-reply of its own any more: its old plugin task, `ig-auto-reply` rules and `ig-reply-log` entries are gone (see [Moving from the Instagram plugin's own auto-reply](#moving-from-the-instagram-plugins-own-auto-reply)), so set the mode here and write the rules under Rules.

The task used to carry one `rehearsal` setting for every network. A task that still has it is mapped once onto each network that has no mode yet (`rehearsal: false` becomes **on**, anything else **rehearsal**) and the setting is removed, so a network connected later starts **off**.

## Rules {#rules}

A rule is an entry of the type `social-auto-reply` (unlisted by default, see [Internal entry types](#internal-entry-types)) with:

- `keywords`: comma-separated words or phrases (the data may also be a list). A keyword matches as a whole word in any case: "price" matches "What's the PRICE?" but not "priceless"; a phrase such as "how much" works. A rule needs at least one keyword and a reply.
- `reply`: the text, sent exactly as written. **Publishing the rule is the approval of that text**; drafts never fire.
- `networks`: integration slugs, comma-separated (network names such as `instagram` also match). **Empty means every network.**
- `post`: empty means any post, else a post id or URL.
- `reply_as`: `private` (the default), `public` or `both` (if the network refuses one half, the other still goes out).
- `also_like`: also like the comment, where the network can. A like that fails never undoes the reply.
- `kinds`: which items it answers, `comment, reply` by default (answers on your own posts). Add `mention` to also answer people who tag you elsewhere, and `message` (or `story_reply`, `story_mention`) to answer **direct messages** — by a direct message back to the person, on every network that can send one, never by a comment reply. The engine answers a DM however it arrived (Instagram and Facebook by webhook, Mastodon and Bluesky by the poll), once, in the network's auto-reply mode (a rehearsal records it without sending). Networks allow such a message only for a while after the person's last one (Instagram and Facebook: 24 hours); a refusal skips the DM for good. **Make a rule** on a DM in the inbox drafts a rule for that kind.
- `cooldown_hours` (**Cool-down for direct messages**, default 24; 0 turns it off): after a person is answered by direct message — by any rule or by you from the inbox — no rule answers them again for this long. When someone sends several messages, only their newest is answered, and the earlier ones are recorded as answered by that reply. A rule answers only direct messages sent **after it was published**, so a new rule never replies to old chats. (Comments keep the 7-day look-back.) When a rule matches a direct message but the cool-down holds it, the item says so: a **Not auto-replied** badge in the inbox, and in its dialog why, until when, and a link to the rule. A message the network refuses (Instagram and Facebook allow one only within 24 hours of the person's last) says so the same way, in the network's words. The record (`held` on the item: `reason` `cooldown` | `refused`, `rule`, `ruleEntryId`, `until`, `note`, `at`) is written once, however many runs re-check the message, and cleared when it is answered. A message no rule matches has nothing to explain and isn't marked.

**Which rule answers.** A comment gets one reply, from the most specific rule that hits: a rule for **this post**, then a rule for **this network**, then a rule for **every network**, and the oldest first within each. The Rules tab lists them in that order: this network's rules, then the all-network ones (marked "All networks"), each with **Published** or **Draft**, and Instagram's older `ig-auto-reply` rules marked as such (they still answer, read as rules for network instagram).

**On a network's page.** **New rule** starts a draft for that network (its slug goes in `networks`) and opens it in the normal entry editor; **New rule for every network** leaves `networks` empty. A row opens the rule with **Edit rule** (the entry editor) and **Publish** / **Unpublish** (editors; publishing needs the keywords and the reply, as the entry's own publish rule says). From the inbox, **Make a rule** drafts one from a comment, for that comment's network.

## Replies {#replies}

The reply is recorded **on the inbox item**: the item is the reply log. It stores the mode, whether it was a rehearsal, the reply id, the text, the rule that fired, when, and who (a person's name for a reply from the inbox). The Replies tab is the items that have a reply, latest first, filterable to live or rehearsal.

- **One comment, one reply.** A live reply on an item is what "answered" means. Only inbox items count: older `social-reply-log` and Instagram `ig-reply-log` entries are not read.
- **Every reply has an item.** A reply to a comment the inbox hasn't stored (older than its 30 days, say) inserts the item first.
- **Pruning can't cause a second answer.** The engine only answers items under 7 days old (`max_age_days`, at most 90), and items are pruned 30 days after they were written. Two cases could still bite (a window set longer than the retention, and a network that gives items no time, which count as fresh forever), so the daily prune keeps an item with a live reply for 180 days.
- A reply from the inbox records the same way, by the person; replying again replaces the record.

## What Marvin makes {#what-marvin-makes}

- **The rule type** `social-auto-reply` is created when the first social integration is connected, or on the first visit to Social. It is internal (below), not a blueprint to apply.
- **The engine's task**, `Social engagement` (every 5 minutes), is created and enabled while an enabled integration offers `social.comments`, and disabled when none does. It reads each network for the inbox and the new-comment trigger whatever its auto-reply mode, and sends the replies of the networks switched on. It isn't something to set up: it appears in Scheduled tasks like any task. A system task, `reconcile_social_engagement` (hourly, admin), keeps every workspace's task in step, and connecting, changing or deleting an integration does it at once.
- **The Social blueprint set is retired.** Core no longer offers the Social set (the two entry types, the two collections `social-auto-reply-rules` and `social-replies`, the task). In workspaces that applied it, nothing is deleted: the entries stay, and a data migration removes only the two collections when they are still as the blueprint made them and empty (a smart collection's membership is derived, so no entry is touched), and otherwise just takes them off the sidebar.

## Internal entry types {#internal-entry-types}

Rules are entries (drafts, publish to activate, history, the normal editor) but they are helper content, so their type is **internal**: `capabilities.listed: false`. An internal type's entries stay out of **All entries** and the status lists (Inbox, Drafts, Needs review, Approved, Published, Archive) and their counts, the sidebar and dashboard counts, search (keyword and semantic), the AI content index, the collections' contents, MCP `search` / `find_entries`, and the publishing API. They are still found by naming the type (`entry_type: social-auto-reply`), the entry (`entries: […]`) or a collection that holds them (`collection: …`), which is how Social's own pages and a workflow that means them reach them; an unqualified "all entries" query, a status or a text search never does, so a bulk action can't touch them by accident. The one exception is the **Trash**: a trashed rule is listed there (marked *Social rule*) and counted, and Restore brings it back to its network's Rules tab, as a draft if it was published (like any entry), so a rule deleted by mistake is not lost. Emptying the Trash deletes it like the rest. **Internal is that one flag and nothing else** (there is no rule on the type's slug any more). Marvin creates the rule type with it set, and a migration set it on the older `social-auto-reply` and `social-reply-log` types in every workspace, so nothing came back among your content. It is visible and yours to change: the entry type editor has a **Show in content lists** switch (off means internal, with a line saying what uses the type, here *Audience › Social › Rules*), and the Content model list marks an unlisted type **Internal**, with the reason in its tooltip. Switching it on lists the rules among your entries too, and Social keeps working: the engine and the Rules tab find the rules by their type, not by the flag. The schema editor keeps the flag when it saves a type; entry events still fire (a workflow triggered on "entry published" with no type filter sees a published rule).

A smart collection can gather the rules (and any other internal entries) too: name the type under **Entry types**, or set its **Listed** rule to **Unlisted only** to take the entries of every internal type at once, combined with the other rules. A collection set to **Listed only** never holds them. Making it **Visible to sites** doesn't publish them: the publishing API never serves an internal type. See [Collections](collections.md#the-listed-rule).

## The capabilities (what a plugin implements) {#capabilities}

Like posting, each plugin declares the capabilities it has, each on one action (`capability=`), and Marvin does the rest. `network` in every output is the plugin's own name.

| Capability | Arguments | Output | Gated |
| --- | --- | --- | --- |
| `social.post` | `text`, `images` (0–10 public https URLs), `alt`, `link`, `dry_run` | `posted`, `post_id`, `url`, `network`, `would_post` on a dry run | yes |
| `social.comments` | `since` (the opaque cursor returned last time), `limit` (50), `kinds` | `items`, `cursor` | no |
| `social.reply` | `comment_id`, `text`, `private` (default `true`), `dry_run` | `replied`, `reply_id`, `private`, `url`, `network`, and `would_reply` on a dry run | yes |
| `social.like` | `comment_id` | `liked`, `network` | no |
| `social.hide` | `comment_id`, `hidden` (default `true`) | `hidden`, `network` | no |
| `social.delete_comment` | `comment_id` | `deleted`, `network` | yes |
| `social.repost` | `post_id` | `reposted`, `url`, `network` | yes |
| `social.message` | `to` (`{id?, handle?}`), `text`, `dry_run` | `sent`, `message_id`, `network` | yes |
| `social.inbox_items` | `payload` (a webhook body) | `items` (Marvin keeps them; the step adds `count`, `kept`) | no |

`social.comments` returns items oldest to newest: `id` (what the other capabilities take as `comment_id`), `kind` (`comment`, `reply` or `mention`; an integration's `inbox_items_from_webhook` may also return `message`, `story_reply`, `story_mention`, `reaction` and `live_comment`, and `attachments`: `{type, url, title}`), `post_id`, `post_url`, `author` (`id`, `handle`, `name`), `text`, `created_at` (ISO, UTC), `url`, `network`. A mode a network can't do is refused with the error code `unsupported`. "Gated" means approval-gated: Marvin treats a gated action as `requires_approval` even when the plugin forgot to say so, and a workflow runs it only after a **Wait for approval** step ([Workflows → Answer comments and reach out](workflows.md#social-engagement)). Posting reaches every network that offers it; the engagement capabilities name one `integration`, because a comment id means something to one network only. A workflow posts with [Workflows → Post to social networks](workflows.md#post-to-social-networks).

| | Read comments | Private reply | Public reply | Like | Hide | Delete | Repost | Message |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Instagram | yes | yes | yes | no | yes | yes | no | only as a reply to a comment |
| Facebook Page | yes | yes (Messenger, within 7 days) | yes | yes | yes | yes | no | Messenger, within 24 hours of their last message |
| Mastodon | yes (notifications) | yes (a direct reply) | yes | yes (favourite) | no | own replies only | yes (boost) | yes |
| Bluesky | yes (notifications) | yes (chat) | yes | yes | yes | own replies only | yes | yes (chat) |

## The engine {#engine}

The task's config: `max_replies` (20 per run; the rest wait for the next), `max_age_days` (7, at most 90), `limit` (50, items read per network per run). For each enabled integration whose plugin offers `social.comments` it reads the items since the integration's stored cursor, keeps them for the inbox, announces each new one, and, when the network's auto-reply is rehearsal or on, drops the account's own comments (compared by handle and id against the integration's config: `own_username`, `handle`, `page_id`, `ig_user_id`…), items older than the window and comments already answered, matches the published rules, replies in the rule's mode, and records the reply on the item. A reply that failed for a reason worth retrying is tried again next run (three attempts). A network that refuses (`unsupported`, `refused`) is skipped for that comment, with no retry and nothing recorded. One network failing never stops the others.

- **Cursors.** Each integration's read cursors (live and rehearsal, kept apart, and a third for announcing), its retry queue and last poll time live in `integrations.state.social`, never shown to the plugin, next to `auto_reply`. A cursor the plugin rejects (`invalid_cursor`) is dropped and the read starts again from the newest items, which the window and the item's reply keep from being answered twice. With no published rules no reply cursor moves, so a rule written later still sees what was waiting.
- **Approval.** A workflow's `social.reply` needs an Approval step; the engine doesn't have one, so a published rule stands in for it, through one narrow door: the engine can call only `social.comments`, `social.reply` and `social.like` (never message, repost or delete); a reply counts as approved only when it comes from a rule that is still published at the moment of sending and the text is that rule's reply, character for character (no templating); and nothing but the engine reaches that path.

## Workflows: a new comment starts one {#new-comment-trigger}

The same poll announces each new comment, reply or mention as the event `social_comment_received`, so a workflow can start on it: classify it with AI, send it to review, reply after an Approval step, hide spam, like it, record a metric ([Workflows → Start on a new comment](workflows.md#new-comment-trigger) has the fields and an example; the Library's **Triage new comments** is one ready-made). It needs no switch: any enabled network that offers `social.comments` is read, whatever its auto-reply is, and a network with auto-reply off still fires the trigger.

- **Its own cursor.** Announcing keeps `events_cursor` in `state.social`, apart from the reply cursors, so changing a network's auto-reply changes nothing about what is announced. When both stand at the same place, one read serves both jobs.
- **Once each.** The first poll of a connection announces nothing already there. From then on an item is announced once: each id is claimed before its event is sent (the last 500 are remembered). Items older than the window or written before the first poll are never announced.
- **Never the account's own.** The same own-account check as replying leaves out the account's own comments and replies, so a workflow that answers in public can't start itself again. An integration whose config names no account can't be told apart: set one before letting a workflow reply in public.

## The inbox {#inbox}

The comments, replies and mentions of every connected network, and what was answered. **Every network read the poll makes is kept** in `social_inbox_items` (one row per network item, unique on integration and item id, one batch insert per read), except the account's own items and items older than 30 days; the daily prune (`prune_social_inbox_items`) deletes what is older, except items with a live reply (above). An item records its author, text, kind, post, link, what it arrived with (`attachments`), when it was written, when Marvin first saw it, a **status** and the reply. Keeping items can't fail a poll.

**What a network pushes.** A delivery to an integration's own incoming webhook (one its blueprint created, such as **Instagram webhooks**) reaches the inbox too, as it happens: after the signature passes, the integration says what the delivery holds (`inbox_items_from_webhook`, integration SDK 0.18.0) and the items are kept as the poll's are — deduplicated with them, the account's own skipped. Core never reads the network's payload. That brings kinds a poll can't read:

| Kind | What it is |
| --- | --- |
| `comment`, `reply`, `mention` | As the poll reads them, but as they happen. On Instagram an @mention arrives only this way; Meta sends its ids, not its text. |
| `message` | A direct message: its text, or a shared post or reel (its caption as the text, its picture attached) |
| `story_reply` | Someone replied to your story |
| `story_mention` | Someone mentioned you in their story |
| `reaction` | Someone reacted to your message |
| `live_comment` | A comment on your live video |

An item that came in by direct message (a message, a story reply, a story mention, a reaction) is answered only by **Reply**, which sends a direct message back (`social.message`) and records it on the item as its reply; it never offers **Make a rule**, and no auto-reply rule answers it. Networks allow such a message only for a while after the person's last one (Instagram: 24 hours). Workflows on the webhook start as before, whatever the inbox keeps; a failure turning a delivery into items never fails the delivery.

Facebook works the same way: apply its **Facebook webhooks** incoming webhook (the `meta` schemes, the app's App secret) and subscribe the Page to `feed`, `mention` and `messages` — Page comments and replies, @mentions and Messenger messages and reactions reach the inbox. Mastodon and Bluesky send no webhooks for an account; the poll reads them as before.

**From a workflow, for a webhook the integration didn't create** (a relay such as n8n, a second app, a delivery you replay): a **Run integration** step with the capability `social.inbox_items` hands the integration the delivery (`args: {payload: ${event.payload}}`) and keeps the items it returns in that integration's inbox, as above; the step's output adds `count` and `kept` (how many were new). It names its `integration` and needs no Approval step (nothing is sent). Sign that webhook: the editor warns when the trigger's webhook isn't signed, since anyone with its URL could otherwise put items in the inbox.

Compact rows (network logo, who, an excerpt, the kind and when, status and **Sent** / **Rehearsal** badges; a new item has a dot and a bold name). Filter by network (on the all-networks page), kind, status and text; the filters live in the page's address. Tap a row to open it: the whole text, links to the post and to the item on the network, the rule that answered, and the actions. Opening a new item marks it seen; **Mark all seen** clears the rest.

| Action | Capability | Role | Notes |
| --- | --- | --- | --- |
| **Reply** | `social.reply` | ADMIN | A text box and a **Private / Public** choice, private preselected, shown only for the modes the network offers. Sent as you and recorded on the item, status `replied`. |
| **Like** | `social.like` | EDITOR | New or seen items become `liked`; a reply or a hide is never downgraded. |
| **Hide** / **Unhide** | `social.hide` | EDITOR | Comments under your own posts only (not mentions). Hidden wins over every other status. |
| **Delete** | `social.delete_comment` | ADMIN | Asks first; removes the comment on the network and drops the item. Not for mentions. |
| **Message** | `social.message` | ADMIN | A direct message to the author, not a reply to the comment. On an item that came in by direct message the button is **Reply**: the message is the answer, recorded on the item (status `replied`). |
| **Trash** / **Restore** | none | EDITOR | Moves the item out of the inbox into its **Trash** (Status → Trash), or back. Marvin only: nothing on the network changes (that is **Delete**). It keeps its status, a rule never answers it, and a poll never brings it back; it is pruned with the rest after 30 days. |
| **Make a rule** | none | EDITOR | A **draft** `social-auto-reply` entry: keywords suggested from the text, that comment's integration, private replies, and your reply box text as the reply. It does nothing until published. |

**Status** is `new`, `seen`, `liked`, `replied` or `hidden`: seeing never undoes anything, a like never downgrades a reply, a reply never unhides, hiding wins, unhiding goes back to `replied` or `seen`.

**The approval, for a person.** A person pressing a button is the human approval a workflow's Approval step stands for, through a third, narrow door (`social_inbox_actions.InboxActor.act`) separate from the engine's: the caller is a workspace member holding the role in the table (checked before anything is looked up, so a lower role gets 403, never a 404 that confirms an id); only the five capabilities above can pass; the comment id and the integration are taken from the stored item, never from the request; the text is the person's own; no approver, no call; and every call is made with `dry_run` false. A failure shows the network's own sentence (422 for a refusal, 502 for a network error) and changes nothing.

## Buckets: what each item needs {#buckets}

Every inbox item can be sorted into one of six fixed buckets, the same on every network (core decides; a plugin only hands over the item), in the order a person works through them:

| Bucket | What it is |
| --- | --- |
| `keyword` | It hit a published rule's keyword: the rule answers it |
| `lead` | Asks about price, availability or buying, or describes a problem you solve |
| `question` | A question others probably share |
| `feedback` | Disagrees, complains, adds substance |
| `support` | Praise, emoji, tags: no reply needed |
| `noise` | Spam, pitches, bait, bots |

**Sorted on arrival, for free.** When an item is first stored (a poll's or a webhook's), Marvin sorts it as `keyword` when a published rule's keyword hits it (the same match the engine answers by: the rule must cover that network and kind, and a direct message must come after the rule was published), else as `support` when it is only emoji and tags or up to four words of plain praise. The rest stay **unsorted**. No AI is involved, and it happens whatever the network's auto-reply mode.

**A person sorts.** In an item's dialog, **Needs** puts it in a bucket or back to Unsorted (EDITOR). A person's choice is theirs: Marvin never changes it, and a re-poll never re-sorts an item.

**The inbox filters by bucket.** Chips over the list show each bucket that has items, then Unsorted, with counts; one is the filter (`?bucket=lead`, or `unsorted`), and a chip again clears it. Each row shows its bucket (who sorted it is in the badge's tooltip). The new-comment trigger carries it as `${event.bucket}`.

**AI sorts the rest, if you turn it on.** **Settings › Social › Sort comments with AI** (ADMIN; off by default). Then, once per engine run, after every network was read and before anything is announced or answered, the items no one has sorted yet (none by a rule, Marvin or a person), written within the 7-day answer window, newest first, **at most 20**, go to the workspace's AI provider in **one** request, and each comes back as `lead`, `question`, `feedback`, `support` or `noise` (`keyword` stays the rules'). So the new-comment trigger's `${event.bucket}` already has the AI's answer. An item the answer leaves out, or gives a bucket that isn't one of those, is marked as looked at (`bucketSource: ai`, no bucket) and never sent again; an answer with no items at all marks nothing and the batch is tried next run. It runs through the same AI pipeline as everything else: the monthly budget (a spent budget skips it), the workspace's provider and default model, an AI execution (source `scheduled`) with its cost. Comments are sent as data to classify, never as instructions. When AI is off, unconfigured or failing, nothing is sorted, the run's note says why, and replies and announcements go on. A `lead` is a filter, not a notification. The switch is `ai_sort` in the Social engagement task's config; `GET /summary` returns it as `aiSort`.

Coming next (`tasks/social-comment-buckets-plan.md`): rules that answer only some buckets, auto-like for `support`, auto-hide for `noise`, and **Save as idea**.

## API {#api}

`/api/groups/social-inbox`, workspace-scoped, mounted when the SDK is installed; the response keys are camelCase.

| Method | Path | Role | Purpose |
| --- | --- | --- | --- |
| GET | `/summary` | EDITOR | What the sidebar and the pages need: `show` (an enabled integration offers a `social.*` capability), `new`, each connected network (`slug`, `name`, `provider` for its logo, `capabilities`, `readsComments`, `canReply`, `autoReply`, `new`) and `can` (what the caller's role may do). `?visit=true` (the Social pages) first creates what is missing: the rule type and the engine's task. |
| GET | `` | EDITOR | The items, newest first. Filters: `integration` (slug), `network`, `kind`, `status` (repeatable), `q`, `since`, `until`, `bucket` (one bucket, or `unsorted`), `limit` (1–200, 50), `offset`. Each item carries `actions`, `replyModes`, `reply`, `held`, `bucket` and `bucketSource`. Also returns `total`, `new` and `buckets` (items per bucket and `unsorted`, of the listed integration, whatever the other filters). |
| GET | `/replies` | EDITOR | The Replies view: items with a reply, latest first. `integration`, `rehearsal` (`true` dry runs, `false` real), `limit`, `offset`. `reply` carries `mode`, `rehearsal`, `replyId`, `text`, `rule`, `ruleEntryId`, `at`, `by`, `byName`. |
| PUT | `/ai-sort` | ADMIN | `{enabled}`: sort unsorted items with AI, once per engine run, at most 20 (see [Buckets](#buckets)). 409 when no network reads comments yet |
| PUT | `/integrations/{slug}/auto-reply` | ADMIN | `{mode: off\|rehearsal\|on}`. 404 for a network that isn't connected, 409 for a mode a network that can't reply can't have. |
| GET | `/rules` | EDITOR | `?integration=<slug>`: that network's rules plus the all-network ones (`allNetworks`); without it, every rule. Each carries `id`, `slug`, `status`, `published`, `keywords`, `reply`, `networks`, `post`, `replyAs`, `kinds`, `path` (the entry editor). |
| POST | `/rules` | EDITOR | `{integration?}`: a new blank **draft** for that network (its slug in `networks`), or for every network when none is named. Returns the rule with its editor `path`. |
| PUT | `/rules/{id}/published` | EDITOR | `{published}`: publish (it then answers) or return it to a draft. The entry's own publish rules apply. |
| POST | `/seen` | EDITOR | `{ids}` or `{all: true, integration?}`: new becomes seen |
| POST | `/{id}/reply` | ADMIN | `{text, private = true}` |
| POST | `/{id}/like` | EDITOR | |
| POST | `/{id}/hide` | EDITOR | `{hidden = true}` |
| POST | `/{id}/trash` | EDITOR | `{trashed = true}` — the inbox's Trash (Marvin only); `GET ?trashed=true` lists it |
| POST | `/{id}/bucket` | EDITOR | `{bucket}` — one of the six [buckets](#buckets), or `null` to clear it; recorded as a person's choice, which Marvin never overwrites |
| DELETE | `/{id}` | ADMIN | |
| POST | `/{id}/message` | ADMIN | `{text}` |
| POST | `/{id}/rule` | EDITOR | `{reply?}` creates the draft rule; returns `id`, `slug`, `keywords`, `path` |

An action the item's network doesn't offer (or the integration is switched off, or its plugin isn't installed) is refused: 422 for the first, 409 for the others.

**Changed from the first Social inbox:** `/summary` no longer returns `available` or `engine` (there is no task to set up; it returns `show`, `new`, `integrations` with their mode and `can`); a reply's `logSlug` and `logEntryId` are gone (the reply is on the item: `text`, `rule`, `ruleEntryId`, `note`, `byName` are new); the reply result has no `logged`; **Make a rule** names the integration's slug, not the network, and no longer answers 409.

## Not covered {#not-covered}

A rule moved to the Trash shows in the Trash, marked *Social rule*, and can be restored from there (a rule that was published comes back as a draft: publish it again). Items answered by Instagram's old plugin task have no reply on them.

## Moving from the Instagram plugin's own auto-reply

Before Social, the Instagram plugin answered comments itself: `ig-auto-reply` rule entries, an `ig-reply-log` entry per reply, a "Social — Auto-Responses" and a "Social — Sent" collection (an "Instagram" group in the sidebar) and an **Instagram auto-reply** scheduled task. Social replaces all of it, and Marvin no longer reads any of it: those entries are not rules, and they don't stop a comment being answered.

- **Nothing to convert, nothing to switch off.** A migration (`b8d4e2f61a73`) removes the leftovers once, from every workspace that has them: the entries of `ig-auto-reply` and `ig-reply-log` and the two entry types, the two collections (only when they are the plugin's smart collections over those types, so the sidebar's "Instagram" group goes with them), and the scheduled task `instagram-auto-reply` (only a `run_integration_action` task whose action is `auto_reply`), with its run history. It touches nothing else: the **Instagram token refresh** task, other tasks, collections and entries stay. Running it again finds nothing.
- **To get the same replies back:** open Social › Instagram › Rules, write a rule per keyword (this network's page makes them for Instagram, with "Reply as: private" as the default), publish it, and set the network's auto-reply to rehearsal, then on.
- **The plugin** (0.8.0) no longer ships those types, collections or the task, and no longer has the `auto_reply`, `list_recent_comments` or `send_private_reply` actions: Social reads comments (`social.comments`) and replies (`social.reply`) through the plugin's `comments` and `reply` actions.
- **A workspace that still has the plugin's older version** can apply its old blueprints again (a blueprint is an offer; the catalogue is read from the installed plugin). Marvin ignores what they make: update the plugin instead.
