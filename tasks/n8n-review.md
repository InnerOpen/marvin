# n8n node list vs Marvin: what is worth building

Source: `/home/jared/.claude/jobs/2e74da59/tmp/n8n.json` (1,431 rows, "Master List of n8n Nodes", 16 Feb 2026).
Marvin checked at `~/code/Marvin` (branch `develop`, 1.1.0-rc.1) and the sibling plugin repos in `~/code/`. Read-only; nothing was changed.

Notes on the list: it is a scraped spreadsheet. The "type" column is unreliable (native nodes such as `n8n-nodes-base.httpRequest`, `markdown`, `rssFeedRead` are under "Regular"; some rows are scrape junk such as `/nodes/html.svg`, `2025-07-29T08:37:30Z`). I matched on name and description, not on type.
Size key: **S** = a catalogue/preset/embed entry or recipe; **M** = a new step type or one integration plugin; **L** = a new subsystem.

---

## 1. What Marvin already has

### Integrations (all external plugins; core ships no provider)
Loader: `src/marvin/services/integrations/loader.py` (entry-point group `marvin.integrations`; SDK `marvin_integration_sdk`). Provider table: `docs/manual/whats-new/integrations.md`. Plugin repos live in `~/code/MarvinIntegration*`.

| Provider | Category | What it does |
|---|---|---|
| `slack` | notify | `send_message`, announce published entries |
| `apprise` | notify | `notify` to 100+ services through one Apprise URL (Slack, Discord, Telegram, Teams, Pushover, Pushbullet, Gotify, Matrix, Mattermost, Zulip, SMS gateways, Mastodon/Bluesky per Apprise's own list, so verify before relying on it) |
| `openai_images` | capability | `image.generate` |
| `instagram` | destination | list comments, DM a commenter, keyword auto-reply, refresh token. **No posting.** |
| `square` | destination | locations, create/close listing (sell one-off items by checkout link); own webhook scheme and workflows |
| `cloudflare_pages` | destination | deployments, build log, connect notifications, deploy |
| `buttondown` | destination | subscribe, lookup, create issue email, connect webhooks; recipe `newsletter-delivery` |
| `n8n` | destination | `trigger_workflow` (JWT-signed call to an n8n Webhook node), list workflows/webhooks, get execution; n8n reports back via an incoming webhook (`docs/manual/whats-new/n8n.md`) |
| `example` | destination | template |

Capability kinds the core resolves (`src/marvin/services/integrations/capability.py`): `image.generate`, `image.edit`, `image.describe`, `image.search`, `image.upscale`, plus `notify`. **No audio (TTS / transcription), translate, or social-post capability.**

### Incoming webhook signature presets
`src/marvin/services/webhooks/incoming_signature.py` `PRESETS`: `hmac_sha256_hex` (GitHub/Buttondown style), `shopify`, `slack`, `stripe`, `standard_webhooks` (Svix/Resend/Clerk), `static_token` (Cloudflare, GitLab), plus `custom` (header, prefix, encoding hex/base64, message template, timestamp tolerance, `sha1|sha256|sha512`) and provider-contributed ones (`buttondown`, `square`, `cloudflare`). A `custom` spec can already express most vendors; presets are convenience.

### Workflow engine
Step kinds (`src/marvin/services/automation/actions/`, one `@register_action` each): `approval`, `collect` (aggregate/query), `email` (to a workspace member only), `emit_event` (incl. custom events with payload), `entry` (publish/unpublish/archive/trash/restore, collection ops, `set_data`/`set_metadata`, `create`, `request_review`), `fetch` (GET/HEAD through the SSRF-guarded client: status, title, text, json, `find`, link check), `handler` (allow-listed internal tasks such as `request_site_rebuild`), `integration` (run any provider action), `media` (resize/crop/convert/grade/inspect/palette/render, OCR/PDF text/pages, find_sensitive/redact, zip, watermark, background removal), `metric`, `operation` (AI op, incl. free-form `custom` with JSON schema), `parallel` (2-5 branches, join all/any), `repeat` (AI over rows, up to 25), `schema_check`, `snapshot`, `wait` (durable, tz/DST-aware), `webhook` (fire a saved outgoing webhook; JSON body; response parsed into `steps.<id>.output.body`).
Control flow: per-step `when` conditions (`matcher.py`: eq, neq, contains, in, starts_with, exists, changed*, gt/gte/lt/lte, longer/shorter_than), `on_failure` steps, idempotency keys, dry run, depth-bounded cascades.
Templates (`matcher.py` `interpolate`): `${path}` only, with **one** filter (`|url`).
Triggers (`engine.py` `_trigger_matches`): `event` (about 150 event types in `services/event_bus_service/event_types.py`), `incoming_webhook`, `chained`, `on_error`, `manual` (typed params), `schedule` (own `services/cron.py`), MCP run.
Library: 116 recipes in `src/marvin/services/automation/recipes/catalogue.json` (rendered at `docs/workflow-library/catalogue.md`); 104 runnable, 3 `needs-adapter` (`audio-edition` needs media/TTS, `poll-companion` and `campaign-scoreboard` need social adapters), 1 `needs-engine-capability` (`reply-drafting-desk`, comments). Roadmap: `docs/workflow-library/roadmap.md` (row 9 "Social adapters": **Open, no social provider exists**).

### Embeds (oEmbed allow-list)
`src/marvin/services/media_embeds/providers.py` `PROVIDERS`: YouTube (nocookie), Vimeo, Spotify, SoundCloud, Apple Music, Apple Podcasts, TIDAL, Bandcamp (embed code only), Simplecast, Transistor. Kinds are only `video | audio | podcast | playlist`. Click-to-load privacy mode (`docs/manual/whats-new/media-embeds.md`). **No form, booking, map, social-post or image-host embeds.**

### Storage, backup, AI
- Storage: `local` built in, `s3` via plugin `~/code/MarvinStorageS3` (R2 in production); registry `src/marvin/services/storage/registry.py`; runbooks `docs/manual/assets-on-r2.md`, `docs/manual/offsite-backup.md` (targets: local/NAS and s3/R2).
- AI provider plugins: OpenAI (+Azure), Anthropic, Google, Ollama (`~/code/MarvinAI{OpenAI,Anthropic,Google,Ollama}`; guide `docs/manual/reference/ai-provider-plugins.md`). System ops: summary, tags, improve-writing, alt-text, classify-form-submission, describe-image, enrich-resource-metadata, answer-workspace-question (`src/marvin/services/ai/operations/system.py`).
- Other: SMTP profiles/templates (`src/marvin/services/email/`), forms as submittable entry types with honeypot/CAPTCHA/rate limit (`docs/manual/whats-new/forms-and-submission-protection.md`), site privacy disclosure (processors, cookies), remote MCP server (`src/marvin/services/mcp_remote/`), outgoing webhooks (`docs/manual/whats-new/outgoing-webhooks.md`: no retries from a workflow step, 15 s timeout).
- **Not found anywhere**: RSS/Atom/sitemap/ICS output (searched `src/`, `docs/manual`, `~/code/MarvinAstro/src`), importers (WordPress/Ghost/Notion/CSV), a CSV/XLSX step, a social-post provider.

### Key framing
Marvin already has an **n8n bridge** and **Apprise**. So the long tail (Pinterest, Mailchimp, Google Sheets, Airtable, SMS, 400 other SaaS) is reachable today by handing off to n8n. Build natively only where Marvin's own data model, approval gating, dry run or idempotency adds something, or where the integration is core to a CMS (feeds, social, newsletter, forms, shop, embeds).

---

## 2. n8n Core nodes vs Marvin building blocks

| n8n Core node | Marvin | Gap | Size |
|---|---|---|---|
| HTTP Request | Partly: `fetch` (GET/HEAD only), `webhook` step (needs a saved webhook or raw url; JSON body only; no retries; uses plain `httpx`, not the guarded client), `integration` step | **General guarded HTTP step**: any method, query/headers/body (JSON, form, multipart), auth presets, retries, parsed response | M |
| Edit Fields (Set), Code, Function, Item Lists | Partly: `entry set_data`; templates are `${path}` + `|url` only | **No transform layer**: no default/coalesce, upper/lower, truncate, slug, join, json, math, string building | S-M (filter library) |
| Date & Time | Relative dates in queries; `wait` knows time zones; templates cannot format or add dates | Date format/add/diff filters | S (in the filter library) |
| Markdown, HTML Extract, XML, RSS Read, RSS Trigger | `fetch` gives title/text/json and `find`; renderers convert markdown on publish but not as a step | **Parse feeds/HTML/XML, markdown to HTML and back, strip HTML**; no feed-polling trigger | M |
| Extract from File / Convert to File / Spreadsheet File | `media` `extract_text` (PDF/OCR), `zip` | **CSV/XLSX read and write** (subscriber/order import, export) | M |
| Crypto, JWT, TOTP | Inbound HMAC verify only; n8n provider signs its own JWT | sha256/hmac/base64 filters (low need) | S |
| Compression | `media zip` (assets only) | fine for CMS | none |
| If, Switch, Filter | Per-step `when`, `parallel` branches | No explicit else/switch node (two `when`s do it) | S (editor sugar) |
| Merge, Aggregate, Split Out, Loop Over Items | `parallel` join, `collect`, `repeat` (cap 25) | covered; cap is deliberate | none |
| Limit, Sort, Remove Duplicates, Compare Datasets | Query-level ordering; idempotency keys; duplicate-asset recipe | Dedupe/compare on step output | S |
| Execute Sub-workflow | `chained` trigger, `emit_event` custom events with payload, MCP `run_workflow` | No call-and-return step with inputs/outputs | M |
| Wait | `wait` step (better: durable, tz-aware) | covered | none |
| Webhook / Respond to Webhook | `incoming_webhook` trigger; fixed acknowledgement | Custom reply body not found | S |
| Schedule / Cron / Manual / Error trigger | `schedule`, `manual` (typed params), `on_error` | covered | none |
| Form trigger | Submittable entry types + `form_submission_received` | covered | none |
| Human-in-the-loop / approval | `approval` step with push Approve/Deny | covered, ahead of n8n | none |
| AI Transform, agents, LLM chains, guardrails | `operation` (incl. `custom` with output schema), agents, spend budgets | covered | none |
| MCP client/trigger | Marvin is an MCP server; agents can use MCP tools | covered | none |
| Execute Command, SSH, FTP, Read/Write Files, Code sandbox | Deliberately absent (roadmap: "running anything" is left) | skip (security) | none |
| Email Send / IMAP trigger | `email` step (members only); outside recipients through email subscriptions | Inbound email trigger absent (skip) | none |

### Biggest gaps (ranked)
1. **Transform/expression layer.** `${x|url}` is the only filter, so every webhook or integration recipe that needs a formatted date, trimmed text, a slug or a default is stuck.
2. **General HTTP request step.** The `webhook` step is tied to a saved webhook row, sends JSON only, does not retry and bypasses the SSRF-guarded client that `fetch` uses (a hardening item in its own right).
3. **Feed / HTML / XML / markdown handling.** Nothing reads or writes RSS, and nothing converts markdown or HTML as a step.
4. **Spreadsheet/CSV in and out.** Blocks import/export of subscribers, orders and form submissions.
5. **Sub-workflow call-and-return**, plus dedupe/sort/limit on step output.

---

## 3. Relevant n8n nodes, by bucket

Coverage: **Full / Partial / None**. "Via n8n" means reachable today through the n8n integration, not natively.

### A. Content distribution (social, newsletters, feeds)

| n8n node | Marvin today | What it adds | Size |
|---|---|---|---|
| Postiz, Blotato, Upload Post, Late, Nuelink, PostPulse (social schedulers) | None (roadmap row 9 open); `instagram` is comments only | One provider gives posting to several networks (IG, TikTok, FB, LinkedIn, Pinterest...) from a published entry, with approval by default; unblocks `poll-companion`, `campaign-scoreboard` | M (one aggregator), L (a social capability with draft/publish/metrics) |
| Mastodon | Apprise may reach it (verify) | Direct post of title + link + image; free API, simple token | M |
| X, LinkedIn, Facebook Graph API, Pinterest, Reddit | None | Direct posting. Pinterest suits a craft brand; X's API is paid | M each |
| YouTube, Vimeo (upload/manage) | Embeds only | Rare for the three sites | M, low |
| Buttondown (not in list) | Full | | |
| Mailchimp, ConvertKit/Kit, MailerLite, Brevo, GetResponse, Mailjet, Mailgun, SendGrid, Sendy, Laposta, Mautic | `buttondown` only; `email` step is members only | A common `newsletter` capability (subscribe, send issue) so recipes are provider-agnostic; MailerLite/Kit/Mailchimp are the realistic small-brand ones | M first, then S-M each |
| RSS Read, RSS Feed Trigger | None | Curation, "new post on partner site" triggers | M |
| (RSS/Atom output) | **None found** | Every blog needs a feed; Buttondown and readers consume it | S-M (publishing API endpoint or Astro helper) |
| Bitly, Short.io, TinyURL, Yourls, Relink | Recipes `utm-librarian`, `one-tap-share-links` | Short links in posts | S (recipe via `fetch`/HTTP step) |
| Medium | None | Crossposting; Medium reportedly no longer issues new API tokens (verify) | M, skip for now |
| Hacker News, Product Hunt, Discourse, Disqus | None | Not relevant to small brand sites | skip |

### B. Publishing targets and imports

| n8n node | Marvin today | What it adds | Size |
|---|---|---|---|
| WordPress | None | Import posts and media into entries (migrating an old site); optional crosspost | M (import), L (importer framework) |
| Ghost | None | Same; Ghost JSON export is easy to read | M |
| Webflow, Wix, Sitecreator, Ycode | None | Publish targets; Marvin already publishes through its own API and Cloudflare Pages | skip |
| Contentful, Storyblok, Strapi, Directus, Cockpit, Flotiq (other CMSs) | None | Migration-in only | skip |
| Notion | None | Import pages/databases; plausible for Jared's notes-to-site flow | M |
| Google Docs / Google Drive | None | "Docs to draft entry" import; Jared uses Google Drive | M |
| Netlify, Cloudflare | `cloudflare_pages` covers Cloudflare | Netlify only if a site moves | skip |
| GitHub / Git | `handler request_site_rebuild`, Pages deploy | Not needed | skip |

### C. Notifications

| n8n node | Marvin today | What it adds | Size |
|---|---|---|---|
| Slack | Full: `slack` plugin | | |
| Discord, Microsoft Teams, Telegram, Pushover, Pushbullet, Gotify, Pushcut, Matrix, Mattermost, Rocket.Chat, Zulip, Line | Full via `apprise` (`notify` capability) | Native plugins would add nothing | none |
| Twilio, ClickSend, MessageBird, Vonage, Plivo, Sms77/seven, TextMagic, SimpleTexting | Partly: Apprise has SMS gateways; none native | SMS to a customer list or alert; only if a use appears | M, low |
| WhatsApp Business Cloud | None | Customer messaging; heavy approval process | skip |
| Gmail, Outlook (send) | SMTP profiles | Covered by SMTP | none |

### D. Forms and CRM

| n8n node | Marvin today | What it adds | Size |
|---|---|---|---|
| Typeform, Tally, Jotform, Wufoo, Formstack, Fillout, Formcarry, Gravity Forms, WPForms, OpnForm, Paperform, Google Forms, SurveyMonkey, KoBo, Zigpoll, Formsite | Partly: Marvin's own forms (submittable entry types) cover the need natively; external form tools can post to an incoming webhook; signature presets missing for Tally/Typeform | Accept submissions from a tool the owner already uses: presets for the HMAC schemes, plus a recipe mapping the payload into an `inbox` entry | S each (preset + recipe) |
| Google Sheets, Airtable, Baserow, NocoDB, Grist, SeaTable, Notion DB | None (via n8n) | "Every form submission also goes to a sheet": the common small-brand wish | S each once a generic HTTP step exists; M for OAuth-based Sheets |
| HubSpot, Pipedrive, Salesforce, Zoho, Freshworks, Capsule, Keap, ActiveCampaign, Monica | None (via n8n) | CRM sync; Jared's sites have no CRM | skip (n8n bridge) |
| Calendly Trigger, Cal.com Trigger, Acuity Trigger | None | See calendar bucket | |

### E. Commerce

| n8n node | Marvin today | What it adds | Size |
|---|---|---|---|
| Square (not in list) | Full: `square` plugin | | |
| Stripe | Partly: `stripe` signature preset only | Provider actions (create Payment Link, list payments) and "paid" events to entries/inventory | M |
| Shopify | Partly: `shopify` signature preset only | Product/order sync into entries; only if a site moves to Shopify | M |
| WooCommerce | None (no preset) | Order webhooks (`X-WC-Webhook-Signature`, base64 HMAC-SHA256, verify) into entries | S preset, M provider |
| Gumroad (+Trigger) | None | "Sale" pings into entries/thank-you flow (ping is form-encoded and unsigned, verify incoming webhook handles it) | S-M |
| Snipcart, Big Cartel, Ecwid, Order Desk, ShipStation, Easyship, Sellix, Paddle, ThriveCart, PayPal, Patreon, Magento, Shopware, Dokan, Teachable | None | Big Cartel and Snipcart fit makers and static sites; Patreon (membership) fits creators; the rest skip | M each, low |
| Etsy | Not in the list | Noted because Mash & Burn may sell there; would need n8n or a custom plugin | n/a |
| Xero, QuickBooks, Invoice Ninja, Wise | None | Accounting | skip |

### F. Media and assets

| n8n node | Marvin today | What it adds | Size |
|---|---|---|---|
| Cloudinary, imgbb, Imgur, Giphy, Pinata/IPFS, BunnyCDN, Mux | Full-ish: Pillow `media` ops, R2 storage, picture derivatives, watermark, background removal | Cloudinary would duplicate resize/crop; Mux only for hosted video | skip |
| Edit Image | Full: `media` | | none |
| Bannerbear, Placid, Orshot, Templated, Abyssale, APITemplate, HTML/CSS to Image, GetScreenshot, ScreenshotOne, Urlbox, QuickChart | Full: `media render` (template to image) and `quote-card-studio`, `retro-poster-machine` recipes | | none |
| Cloud Convert, ConvertAPI, PDF.co, PDF4ME, PDF Generator API, CraftMyPDF, Carbone, DocuSeal | Partly: `media` convert/PDF text/zip; no PDF generation from content except the printed PDF op | PDF/doc generation is already in `media` | skip |
| YouTube (list/playlist/upload), Vimeo | Embeds only | | M, low |
| Pinterest / Instagram media | See social | | |
| Unsplash | Not in list | | n/a |
| AltText.ai | Full: `generate-alt-text` op | | none |

### G. AI and text

| n8n node | Marvin today | What it adds | Size |
|---|---|---|---|
| OpenAI, Anthropic, Gemini, Ollama, Mistral, Groq, Cohere, Bedrock, Azure OpenAI, DeepSeek, xAI, OpenRouter, Perplexity | Full for OpenAI/Azure/Anthropic/Google/Ollama (plugins). Others reachable only if they speak the OpenAI API | OpenRouter/Groq/Mistral work if the OpenAI plugin takes a base URL (verify) | S (docs/preset) |
| DeepL, Google Translate, LingvaNex, FluentC, Localazy, Lokalise, Crowdin, Phrase, Transifex, SimpleLocalize | Partly: `translation-desk` recipe uses the LLM | A `text.translate` capability with DeepL (cheap, consistent, glossary) next to the LLM route | M (capability) + S (DeepL provider) |
| AssemblyAI, Deepgram, AWS Transcribe, Whisper-type | None (no audio capability) | Transcribe uploaded audio/video into a draft entry or captions; podcasts | M (new capability kind) |
| ElevenLabs, Murf, OpenAI TTS, Botnoi, Typecast | None | Unblocks the `needs-adapter` recipe `audio-edition` (narrated posts) | M |
| SEO: DataForSEO, SE Ranking, Ritekit, SEO Content Machine, Winston AI, Markupai | Partly: `seo-assistant` recipe (LLM) | Real keyword/rank data needs paid APIs | skip |
| Lighthouse / PageSpeed | None | After a deploy, run PageSpeed through `fetch` and alert on a regression | S (recipe) |
| Brave Search, Tavily, Exa, SerpApi, Firecrawl, scrapers (Apify, ScrapingBee, ...) | `fetch` (one URL) | Research/scrape; not a CMS job | skip |
| Vector stores, memory, embeddings, LangChain nodes | Marvin has its own embeddings/search index | | none |

### H. Analytics

| n8n node | Marvin today | What it adds | Size |
|---|---|---|---|
| Google Analytics, PostHog, Mixpanel, Segment | Partly: `metric` step records numbers; privacy section lists processors | Pull weekly pageviews/top pages into a digest or `best-of-month`; needs OAuth for GA4; would also need a processor disclosure | M, low |
| Plausible, Matomo, Umami, Fathom | Not in list (Fathom row is the meeting assistant) | Privacy-friendly analytics fit the brands better than GA, but are outside this list | n/a |
| Google Search Console | Not in list | | n/a |

### I. Calendar and events

| n8n node | Marvin today | What it adds | Size |
|---|---|---|---|
| iCal | None (no ICS output found) | `.ics` feed / "Add to calendar" for workshop entries | S-M |
| Google Calendar (+Trigger), Zoho Calendar | None natively (the Claude connector is separate) | Create calendar events from workshop entries | M (OAuth) |
| Calendly (+Trigger), Cal.com Trigger, Acuity Trigger, Eventbrite Trigger, Corsizio, Occasion, Planyo, Team Up, Anny, DaySchedule | None | Booking webhooks to entries ("Workshop booked" to a sold-count field, thank-you email); Calendly's scheme looks like Stripe's `t=..,v1=..` (verify) | S preset + S recipe each |
| HeySummit, GoToWebinar, Demio, WebinarJam, Zoom | None | Webinars; not relevant | skip |

### J. Storage and backup

| n8n node | Marvin today | What it adds | Size |
|---|---|---|---|
| S3, AWS S3, Google Cloud Storage, Azure Storage | Full: `s3` storage plugin and S3 backup target (R2 in production) | | none |
| Backblaze B2 (not in list) | Probably works via the S3 plugin with a custom endpoint (verify) | Cheap second off-site copy | S (docs) |
| Nextcloud, WebDAV | None; NAS target is local | WebDAV backup target for a homelab Nextcloud | M |
| Dropbox, Google Drive, OneDrive, Box, Zoho WorkDrive | None | OAuth backup or asset-import sources; R2 plus NAS already satisfy backups | M each, low |
| FTP, SSH | None | Deploy to shared hosting; the sites use Cloudflare Pages | skip |
| BunnyCDN, Pinata | None | | skip |

### K. Generic building blocks
See section 2. Candidates: HTTP request (M), transform filters (S-M), feed/HTML/XML/markdown (M), CSV/XLSX (M), sub-workflow (M), dedupe/sort/limit (S).

---

## 4. Ranked: worth building (top 12)

Weighted to Jared's real use (newsletter, social, shop, forms, workshops) and to reuse of existing mechanisms.

| # | Build | Why | Reuses | Size |
|---|---|---|---|---|
| 1 | **Generic HTTP request step** (method, query, headers, body, auth presets, retries, parsed response, SSRF guard) | Unlocks everything in the long tail (Sheets, Airtable, Mailchimp, link shorteners, PageSpeed) as recipes with no new plugin; also fixes the `webhook` step's guard bypass | `fetch`'s guarded client, secrets, idempotency | M |
| 2 | **Template filter library** (`default`, `date`, `truncate`, `slug`, `join`, `json`, `upper/lower`, `strip_html`, `md_to_html`, `base64`, `sha256`, simple math) | Every recipe needs shaping; today only `\|url` exists | `matcher.py` `FILTERS` | S-M |
| 3 | **Social publishing capability** with one aggregator provider first (Postiz or similar), then Mastodon and Pinterest; approval required by default | The biggest missing feature for brand sites; roadmap row 9 is open; unblocks two `needs-adapter` recipes | Capability routing, approval step, `instagram` plugin patterns | M then L |
| 4 | **RSS/Atom + sitemap + ICS output** from the publishing API (or MarvinAstro helper) | Table stakes for a blog; feeds Buttondown/readers; ICS serves workshops | Publishing API, MarvinAstro | S-M |
| 5 | **Webhook signature preset pack**: Tally, Typeform, WooCommerce, Calendly, Cal.com, Webflow, Ghost, Paddle, Telegram (token) | Lets owners take submissions, bookings and orders from tools they already use; a preset is a dict entry | `PRESETS` in `incoming_signature.py` | S each |
| 6 | **Newsletter capability + second provider** (MailerLite or Kit, then Mailchimp), shaped like `buttondown` | Recipes (`newsletter-delivery`) become provider-agnostic; choice for users who are not on Buttondown | Integration SDK, capability routing | M |
| 7 | **Form and booking embeds**: Tally, Typeform, Google Forms, Calendly/Cal.com, Google Maps/Calendar; needs new embed kinds (`form`, `booking`, `map`) and frame hosts | Workshop booking and contact forms on Astro sites without custom code; reuses the allow-list and click-to-load privacy | `media_embeds/providers.py` | M (new kinds) then S each |
| 8 | **Submission destinations as recipes**: Google Sheets, Airtable, Notion DB, plus a **CSV/XLSX read-write step** | "Every submission also lands in a sheet" and subscriber/order import-export | Depends on #1; `form_submission_received` | S each, M (CSV step) |
| 9 | **Shop events**: Stripe (payment links, paid events), WooCommerce/Shopify order webhooks into entries | Square exists for one-offs; Stripe is the common alternative and the presets already exist | `stripe`/`shopify` presets, `entry create` step | M |
| 10 | **Audio capabilities**: TTS (ElevenLabs/OpenAI) and transcription (AssemblyAI/Deepgram/Whisper) | Unblocks `audio-edition`; captions/transcripts for podcast embeds | capability routing, `media` attach | M |
| 11 | **Calendar and booking**: ICS output (see #4), Google Calendar provider, booking-webhook recipes (Calendly/Cal.com/Acuity) | Mash & Burn runs workshops: sold-out flag, reminder, thank-you | `wait` step, `email` step, presets | M |
| 12 | **Importers** (WordPress REST/export, Ghost JSON, Notion, Google Docs) as `source`-category providers | Onboarding and migration; not needed for Jared's own sites unless he moves content | `import_asset`, blueprints, `entry create` | L |

Quick wins that are not in the 12: PageSpeed/Lighthouse post-deploy recipe (S, via `fetch`); Backblaze B2 through the S3 plugin (S, docs after verifying); an "n8n recipe gallery" (S: documented n8n patterns for Pinterest, Etsy, Mailchimp, Sheets that call the existing `trigger_workflow`); a shared guarded client for the `webhook` step (S, hardening).

---

## 5. Already covered (no work)
Slack and all chat/push services via Apprise; Buttondown newsletter; Square shop; Cloudflare Pages deploys; S3/R2 storage and backups; every LLM provider that matters, image generation, alt text, vision; image resize/crop/convert/watermark/background removal/render templates, PDF/OCR/zip; approval (human-in-the-loop); durable wait; schedule/manual/error/webhook triggers; collect/repeat/parallel (aggregate/loop/merge); schema validation; snapshots; form intake with honeypot/CAPTCHA/spam classification; YouTube/Vimeo/Spotify/SoundCloud/Apple/TIDAL/Bandcamp/Simplecast/Transistor embeds; MCP server; outgoing and incoming webhooks; n8n bridge for anything else.

## 6. Skip, and why
- **Blockchain, crypto, NFT** (1Shot, Alchemy, NMKR, Crossmint, Venly, Relysia, Chainstream...): irrelevant.
- **Dev-ops, security, monitoring** (AWS IAM/ELB/Lambda, Datadog, Splunk, CrowdStrike, Cisco, Rundeck, Jenkins, Sentry...): not a CMS job; Marvin has its own health alerts.
- **Niche B2B SaaS and CRM** (Salesforce, Zoho, Pipedrive, HR/ATS, field-service, ERP): no use on the three sites; the n8n bridge covers a one-off.
- **Other CMS and site builders** (Contentful, Strapi, Webflow, Wix...): competitors, not targets (import at most).
- **Databases, vector stores, message queues** (Postgres, Mongo, Kafka, MQTT, Pinecone...): wrong layer.
- **Scrapers and search APIs** (Apify, ScrapingBee, Firecrawl, SerpApi...): research tooling, not content management.
- **Local execution** (Execute Command, SSH, Code sandbox): deliberate security boundary, and the roadmap already defers it.
- **Duplicate community wrappers** (several dozen `n8n-nodes-*` entries for PDF generators, screenshot APIs, TTS and chatbots that repeat a bigger service): one choice per capability is enough.
- **Wallet passes, webinars, chatbots, meeting assistants, accounting**: no fit.
- **Direct Medium/Hacker News/Disqus**: low audience value, and Medium API access is restricted (verify).

---

## 7. Caveats
- Header and signature details for third-party webhooks (Tally, Typeform, WooCommerce, Calendly, Cal.com, Webflow, Paddle, Ghost) and oEmbed endpoints for Calendly/Eventbrite/Google Forms come from general knowledge, not from the n8n list or from a live check. Verify each before building.
- Apprise service coverage (Mastodon, Bluesky, SMS gateways) is taken from the project's documented list, not tested here.
- Whether `marvin-storage-s3` accepts a Backblaze B2 endpoint and whether the OpenAI plugin takes a custom base URL were not checked in the plugin code.
- Marvin's integration plugins are in sibling repos; I read their READMEs and the in-repo manual, not their source.
