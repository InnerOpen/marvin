# Social posting: one "post to social" capability, direct per-network plugins (2026-10-19)

Jared: "I like that. I'd rather not go through a third party." The decision is to use no aggregator (Buffer, Ayrshare…).
Each network gets its own integration plugin, and Marvin core gets one shared capability, as `notify` is shared today.
A recipe says "post this", not "post to Instagram". Roadmap row 9 (`social-adapters`) is unblocked:
`poll-companion` and `campaign-scoreboard`.

## What exists
- The `instagram` plugin already posts: `publish_media` (image or a 2–10 image carousel, caption, approval-gated,
  dry run, quota) and comment auto-replies. Its actions declare no capability.
- Capabilities (services/integrations/alert_routing.py): an action declares `capability`, and a workflow's integration
  step can name `capability` instead of `action`. Approval-gated actions are skipped by capability routing.

## Core (Marvin)
1. **`social.post` capability, one argument shape** (the contract each plugin maps onto its own API):
   `text` (required), `images` (0–10 public image URLs or asset ids/slugs; core resolves assets to their public URLs),
   `alt` (list, one per image), `link` (a URL to attach or append), `dry_run`. Output: `posted`, `post_id`, `url`
   (permalink), `network`, plus `would_post` on a dry run. Each plugin says what it can't do (the length limit, needing an
   image) by refusing with a clear error.
2. **Approval by default.** Posting is public and can't be quietly undone, so `social.post` actions are approval-gated.
   Capability routing learns to accept a gated action when the step comes after an Approval step. The save check
   already does this for named actions.
3. **Post everywhere connected.** A capability step without `integration` runs on every enabled integration that
   provides `social.post`, one after another. Output `results` holds one entry per network. A failure on one doesn't
   stop the others: it's reported in its entry and fails the step at the end (unless `fail_on_error: false`). With
   `integration`, it posts to that one only.
4. **Per-network text.** A `per_network` map (`{"bluesky": {"text": "…"}}`) overrides the arguments for one network
   (Bluesky's 300 characters vs Instagram's 2,200), with filters such as `truncate`.
5. Recipe "Share a published entry everywhere" (draft → approval → post) and docs (workflows manual, integrations).

## Plugins (one repo each, like MarvinIntegrationInstagram)
| Network | Work | Notes |
|---|---|---|
| Instagram (exists) | S | `publish_media` declares `social.post`, with args mapped (`text` → caption, `images` → image_url(s)). It needs at least one image (Instagram can't post text alone): a clear error |
| Facebook Page | S–M | Same Meta app and approval as Instagram (Page token, `pages_manage_posts`). Text, link and photos |
| Bluesky | S | App password, AT Protocol `createRecord`. Images are uploaded as blobs (fetched from the URL); link card. 300 characters |
| Mastodon | S | Server URL + access token. Media upload, then status. 500 characters (per server) |
| Pinterest | M, later | Needs Pinterest app approval. A pin needs an image + board; skip until wanted |

LinkedIn, TikTok and X are out of scope: they have hard app reviews, and X charges for its API.

## Decisions (Jared, 2026-10-19: all as recommended)
1. First round: Instagram + Facebook Page + Bluesky + Mastodon.
2. Every social post needs a person's approval first (an Approval step before it). No opt-out.
3. A step naming no integration posts to every connected one, one after another.

## Steps
- [x] Core: capability contract + asset→URL + approval-gated capability routing + fan-out + per_network; tests
- [x] Instagram plugin: declare `social.post`; map args; release
- [x] Bluesky plugin; Mastodon plugin; Facebook Page plugin (new repos, released like the others)
- [x] Recipe + docs; roadmap row 9 → done

## Review (2026-10-19)
- **Built:**
  - Core (Marvin `4bbc3d08`, `33257c69`) and Instagram `post` (0.6.0, `fa1d8dd`, unpushed).
  - New local repos: `~/code/MarvinIntegrationFacebook` (`8637207`), `~/code/MarvinIntegrationBluesky` (`5fc78af`) and `~/code/MarvinIntegrationMastodon` (`b409006`).
- **Tests:** plugin tests 81 / 53 / 97 / 152.
- **Contract checked:** a dry-run fan-out ran through core with all four real plugins installed, using a fake HTTP client. Every network answered in the contract's shape, and text-only was refused by Instagram alone.
- **Approval after a Wait or retry:** fixed. The approval is kept in the run snapshot, so "approve now, post at 9" works.
- **Not yet published (Jared: "Not yet"):**
  - no GitHub repos for the three new plugins;
  - the plugins are not in Marvin's `plugins` group;
  - Marvin develop is not pushed.
- **Before going live:** one real post per network, to settle each README's "verify" list (Graph alt-text fields, the AT Protocol shapes, the Mastodon health scope).
