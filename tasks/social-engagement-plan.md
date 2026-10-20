# Social engagement: read comments, reply (private by default), and the rest, on every network (2026-10-20)

Jared: "plan it, private replies like Instagram but don't limit it either. if there are other features". Today only
the Instagram plugin reads comments and auto-replies (private reply, keyword rules as `ig-auto-reply` entries, a
`ig-reply-log` entry per send, a scheduled task polling every few minutes). This makes that work on every connected
network, keeps private replies as the default, allows public replies, and adds the other engagement actions the
networks offer. Same pattern as posting (tasks/social-posting-plan.md): shared capabilities in core, each plugin
maps them onto its own API.

## Shared capabilities (the contract every plugin implements)
| Capability | Args → output | Notes |
|---|---|---|
| `social.comments` (read) | `{since?, limit?, kinds?}` → `{items: [{id, kind: comment\|reply\|mention, post_id, post_url, author: {id, handle, name}, text, created_at, url, network}], cursor}` | comments on own posts, replies, mentions |
| `social.reply` | `{comment_id, text, private: true (default), dry_run}` → `{replied, reply_id, private, url, network}` | private = DM-style reply to the commenter; `private: false` = public reply in the thread. A network that can't do the asked mode refuses with `unsupported` |
| `social.like` | `{comment_id}` → `{liked}` | like / favourite a comment or reply |
| `social.hide` | `{comment_id, hidden: true}` → `{hidden}` | hide a comment under own post (moderation) |
| `social.delete_comment` | `{comment_id}` → `{deleted}` | delete a comment under own post (or own reply) |
| `social.repost` | `{post_id}` → `{reposted, url}` | boost / repost (Mastodon, Bluesky) |
| `social.message` | `{to: {id or handle}, text, dry_run}` → `{sent}` | a direct message not tied to a comment (later steps of a flow) |

## Who can do what
| | Read comments | Private reply | Public reply | Like | Hide | Delete | Repost | Message |
|---|---|---|---|---|---|---|---|---|
| Instagram | yes (exists) | yes (exists) | yes (`/{comment}/replies`) | no (API has none) | yes | yes | no | only as a reply to a comment (API limit) |
| Facebook Page | yes (post comments) | yes (Messenger private reply, `pages_messaging`, within 7 days) | yes | yes | yes | yes | no | Messenger, within 24h of their last message |
| Mastodon | yes (mention/reply notifications) | yes (direct-visibility reply) | yes | yes (favourite) | no (no hiding others' replies) | own replies only | yes (boost) | yes (direct status) |
| Bluesky | yes (reply/mention notifications) | yes (chat; needs an app password with DM access) | yes | yes | yes (threadgate hidden replies) | own replies only | yes | yes (chat) |

Each plugin declares only the capabilities it has. Core shows what's possible per network.

## Core
1. **Normalised comments** and the capability routing for the seven above (reusing alert_routing's capability lookup).
2. **One shared rule type** `social-auto-reply` (core blueprint): keywords, reply text, `networks` (any or a list),
   `post` (any or one post id/URL), `reply_as` private (default) | public | both, optional `also_like: true`.
   And `social-reply-log`: one per reply sent (network, comment id, rule, mode, when) — the dedupe key.
3. **The auto-reply engine** in core: a scheduled job (one per workspace, every 5 minutes by default) that, for each
   connected network with `social.comments` + `social.reply`, reads new items since its cursor, matches published rules
   (Instagram's matching.py moves to core), replies in the rule's mode, logs it. It starts in **rehearsal** (dry run:
   logs what it would send) until switched on, as Instagram's does. Per-network limits: no reply to its own account,
   one reply per comment, at most N per run, the network's reply windows (Facebook 7 days, Instagram 7 days).
4. **Instagram compatibility:** existing `ig-auto-reply` rules are read as shared rules (network instagram), and
   `ig-reply-log` counts as the log, so nothing is answered twice in the switch-over. The plugin's own `auto_reply`
   action and task stay working until the shared engine is switched on for Instagram, then the plugin's task is
   turned off (not deleted).
5. **Workflow use:** a trigger "new comment" (`social_comment_received`, from the same poll) so a workflow can classify a
   comment (AI), send it to review, reply after an Approval step, hide spam, etc. Plus the steps (capabilities) above.
6. **A page:** Settings → Integrations → Social inbox — recent comments across networks, what was replied (rehearsal
   or sent), quick actions (reply, like, hide) — reading `social-reply-log` and the last poll. (Could be phase 2.)

## Approval (proposed)
- A **published rule** is the approval for its reply text: the auto-reply engine sends without asking each time
  (after rehearsal is switched off), as Instagram's auto-reply does today.
- In a **workflow**, `social.reply`, `social.message`, `social.repost` and `social.delete_comment` need an Approval step
  first (public or irreversible); `social.like` and `social.hide` don't (easily undone moderation).

## Plugins
- Instagram: public reply, hide, delete; declare `social.comments` / `social.reply` on the existing actions.
- Facebook: read comments, private reply (Messenger), public reply, like, hide, delete. Adds `pages_messaging`.
- Mastodon: notifications → comments; direct and public replies; favourite; boost; direct message; delete own reply.
  Token adds `read:notifications`, `write:favourites`, `write:statuses`.
- Bluesky: notifications → comments; public reply; like; repost; hide (threadgate); chat for private reply and
  messages (app password with "allow access to your direct messages").

## Phases
1. Core contract + engine + shared rules (with Instagram compatibility) + Instagram and Mastodon (simplest APIs) → ship.
2. Facebook and Bluesky (Messenger and chat permissions to set up), the "new comment" trigger.
3. The Social inbox page.

## Decisions (Jared, 2026-10-20: all as recommended)
1. A published rule is the approval for its reply text: the engine sends on its own once rehearsal is off. In a workflow,
   reply / message / repost / delete need an Approval step first; like and hide don't.
2. One shared rule type across networks. Instagram's `ig-auto-reply` rules and `ig-reply-log` carry over, so nothing is
   answered twice.
3. Phases: 1 core + shared rules + Instagram + Mastodon (ship); 2 Facebook + Bluesky + the "new comment" trigger;
   3 the Social inbox page.

## Review, phase 1 (2026-10-20)
- **Built (core):** the seven capabilities (`social.comments/reply/like/hide/delete_comment/repost/message`); reply, message,
  repost and delete_comment gated like `social.post` at save and run time, none of them fan out (they name an `integration`);
  shared rule + log entry types as core blueprints (category Social, `services/blueprints/social.py`), plus two collections and
  the `social-engagement` task; the engine (`services/integrations/social_engagement.py`, handler `social_engagement`);
  `integrations.state` (migration `5e1c7a9d3b24`) for cursors and the retry queue; Instagram compatibility; docs.
- **Added beyond the plan:** a rule `kinds` field (default `comment, reply`; `mention` is opt-in) because Mastodon yields
  reply/mention and Instagram comment/reply; `unsupported`/`refused` from a plugin skip the comment with no retry and no
  log; `invalid_cursor` drops the cursor and rereads; rehearsal keeps its own cursor so leaving it still answers the window.
- **Open:** `keywords` is a comma-separated
  text field in the editor (the engine also takes a list); the engine sends then logs, so a crash between the two could
  answer one comment twice.

## Review, phase 2 (the new-comment trigger, 2026-10-20)
- **Built:** `social_comment_received` (event catalogue, trigger heading Social, payload = the normalised item + `integration` slug and
  `integration_id`, `${event.author.handle}` and conditions work); announced by the same 5-minute poll: `Settings.announce` (task config,
  default true), the poll runs for announcing even with no rules or log type, and needs only `social.comments`; a templated
  `integration` on a capability step (run time, save check, retry check); the Triage new comments recipe; the Social engagement card on
  Settings → Integrations (applies core's set, shows the task's state); docs and authoring guide.
- **Events cursor:** `state.social.events_cursor` + `events_started_at` + `events_seen` (last 500 ids), independent of the live and
  rehearsal reply cursors; ids are claimed before the event is sent (at most once); first poll announces nothing; own items, items older
  than the 7-day window and items written before the first poll are never announced. One network read serves both jobs when the
  cursors agree.
- **Open:** an integration whose config names no account can't have its own items recognised (a workflow's public reply could re-trigger
  it); events are sent synchronously, so a slow workflow step delays the rest of the poll (the poll reads at most `limit` items).
