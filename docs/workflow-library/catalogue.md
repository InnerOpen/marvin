# Workflow Library catalogue

Rendered from `src/marvin/services/automation/recipes/catalogue.json` by `scripts/render_workflow_library.py` — do not edit by hand.

107 recipes: **24** verified-current, **11** supported-after-configuration, **16** needs-adapter, **56** needs-engine-capability.

Statuses are defined in [README.md](README.md). A recipe link opens its workflow JSON (with `{{setup}}` placeholders); `<id>.vars.json` beside it declares each placeholder's type.

## Runnable today

| Recipe | Status | Trigger | Needs | Side effects |
|---|---|---|---|---|
| [newsletter-delivery](../../src/marvin/services/automation/recipes/newsletter-delivery.json) — Newsletter delivery | verified-current | `entry_published` | buttondown integration | content mutation, email ⚠, external post |
| [publication-announcement](../../src/marvin/services/automation/recipes/publication-announcement.json) — Publication announcement | verified-current | `entry_published` | outgoing webhook | content mutation, external post |
| [editorial-approval-gate](../../src/marvin/services/automation/recipes/editorial-approval-gate.json) — Editorial approval gate | verified-current | `entry_updated` | entry type with required fields (its completeness rules are the validation) | content mutation |
| [seo-assistant](../../src/marvin/services/automation/recipes/seo-assistant.json) — SEO assistant | verified-current | `entry_updated` | AI enabled for the workspace with the `automation` invocation source allowed; a default model | content mutation, paid call ⚠ |
| [content-refresh](../../src/marvin/services/automation/recipes/content-refresh.json) — Content refresh | verified-current | `entry_updated` | outgoing webhook | external post |
| [comment-discussion-starter](../../src/marvin/services/automation/recipes/comment-discussion-starter.json) — Comment discussion starter | verified-current | `entry_published` | outgoing webhook | content mutation, external post |
| [editorial-task-maker](../../src/marvin/services/automation/recipes/editorial-task-maker.json) — Editorial task maker | verified-current | `entry_published` | n8n integration | content mutation, external post |
| [utm-librarian](../../src/marvin/services/automation/recipes/utm-librarian.json) — UTM librarian | verified-current | `entry_created` | an entry type with a page URL pattern (so `entry.url` resolves) and two fields for UTM source and medium | content mutation |
| [client-handoff](../../src/marvin/services/automation/recipes/client-handoff.json) — Client handoff | verified-current | `entry_updated` | outgoing webhook | content mutation, external post |
| [failure-repair-desk](../../src/marvin/services/automation/recipes/failure-repair-desk.json) — Failure repair desk | verified-current | `on_error` (`automation_failed`) | — | content mutation |
| [publication-ledger](../../src/marvin/services/automation/recipes/publication-ledger.json) — Publication ledger | verified-current | `entry_published` | — | content mutation |
| [blocked-publication-rescue](../../src/marvin/services/automation/recipes/blocked-publication-rescue.json) — Blocked publication rescue | verified-current | `entry_scheduled_publish_blocked` | apprise integration | content mutation, notification |
| [form-intake-desk](../../src/marvin/services/automation/recipes/form-intake-desk.json) — Form intake desk | verified-current | `form_submission_received` | apprise integration; a submittable entry type (capabilities.submittable) — submissions are entries of that type | content mutation, notification |
| [submission-surge-alert](../../src/marvin/services/automation/recipes/submission-surge-alert.json) — Submission surge alert | verified-current | `submission_surge_detected` | apprise integration; submission protection with a surge threshold on the entry type | notification |
| `host-rebuild-dispatch` — Host rebuild dispatch | supported-after-configuration | subscription: `webhook_triggered` | site_auto_rebuild preference on, or the request_site_rebuild handler / Rebuild button; outgoing webhook | external post ⚠ |
| [deployment-celebration](../../src/marvin/services/automation/recipes/deployment-celebration.json) — Deployment celebration | verified-current | `site_deployment_completed` | apprise integration; a producer of site_deployment_completed: the Cloudflare Pages plugin's blueprint, or your own incoming webhook + emit_event workflow; incoming webhook; workflow | notification |
| [deployment-failure-desk](../../src/marvin/services/automation/recipes/deployment-failure-desk.json) — Deployment failure desk | verified-current | `site_deployment_failed` | apprise integration; a producer of site_deployment_failed (see deployment-celebration); incoming webhook; workflow | notification |
| `integration-health-companion` — Integration health companion | supported-after-configuration | subscription: `integration_attention_needed` | SMTP (workspace or platform) for email; VAPID for push; notification settings | notification |
| `connection-recovery-log` — Connection recovery log | supported-after-configuration | subscription: `integration_attention_resolved` | — | external post |
| `webhook-repair-desk` — Webhook repair desk | supported-after-configuration | subscription: `webhook_delivery_failed` | SMTP or VAPID push; notification settings | notification |
| `scheduled-task-watchdog` — Scheduled task watchdog | supported-after-configuration | subscription: `scheduled_task_failed` | notification settings | notification |
| `ai-spending-heads-up` — AI spending heads-up | supported-after-configuration | subscription: `ai_budget_threshold_reached` | an AI monthly budget set (Settings → AI → Limits); SMTP; email event subscription | email |
| `ai-budget-pause-desk` — AI budget pause desk | supported-after-configuration | subscription: `ai_budget_exceeded` | an AI monthly budget; SMTP; email event subscription | email |
| `ai-quota-recovery-desk` — AI quota recovery desk | supported-after-configuration | subscription: `ai_provider_quota_exceeded` | SMTP; email event subscription | email |
| `agent-approval-inbox` — Agent approval inbox | supported-after-configuration | subscription: `approval_requested` | VAPID web push configured; approvers have the app installed with notifications on; native | notification |
| [collection-welcome-mat](../../src/marvin/services/automation/recipes/collection-welcome-mat.json) — Collection welcome mat | verified-current | `entry_added_to_collection` | AI enabled with the `automation` source allowed | content mutation, paid call ⚠ |
| `new-member-welcome` — New member welcome | supported-after-configuration | subscription: `member_added` | SMTP; email event subscription | email |
| `api-token-rotation-notice` — API token rotation notice | supported-after-configuration | subscription: `api_client_token_rotated` | SMTP; email event subscription | email |
| [unpublish-entries-with-images](../../src/marvin/services/automation/recipes/unpublish-entries-with-images.json) — Move every entry with an image back to draft | verified-current | `manual` | — | content mutation |
| [summarise-and-feature-on-publish](../../src/marvin/services/automation/recipes/summarise-and-feature-on-publish.json) — Summarise a published entry and add it to a collection | verified-current | `entry_published` | AI enabled with the `automation` source allowed | content mutation, paid call ⚠ |
| [hourly-site-rebuild](../../src/marvin/services/automation/recipes/hourly-site-rebuild.json) — Every hour, rebuild the site | verified-current | `schedule` | a deploy target (an event-driven outgoing webhook or integration subscription on webhook_triggered) for the rebuild to reach anything | external post ⚠ |
| [archive-entry-from-webhook](../../src/marvin/services/automation/recipes/archive-entry-from-webhook.json) — A webhook call finds an entry by slug and archives it | verified-current | `incoming_webhook` | incoming webhook | content mutation |
| [trash-unattached-images](../../src/marvin/services/automation/recipes/trash-unattached-images.json) — Trash every unattached image | verified-current | `manual` | — | content mutation |
| [restore-trashed-resources](../../src/marvin/services/automation/recipes/restore-trashed-resources.json) — Restore all resources in the Trash | verified-current | `manual` | — | content mutation |
| [asset-upload-announcement](../../src/marvin/services/automation/recipes/asset-upload-announcement.json) — Post new uploads to a chat channel | verified-current | `asset_uploaded` | outgoing webhook | external post |

## Waiting on a capability or an adapter

| Recipe | Status | Trigger | Blocked by |
|---|---|---|---|
| `translation-desk` — Translation desk | needs-engine-capability | `entry_published` | create-entry, custom-operation, workflow-approvals |
| `audio-edition` — Audio edition | needs-adapter | `entry_published` | media-adapters, asset-resource-targets |
| `series-index-keeper` — Series index keeper | needs-engine-capability | `entry_published` | iterate-aggregate, collection-scope |
| `weekly-digest` — Weekly digest | needs-engine-capability | `schedule` | iterate-aggregate, relative-dates, create-entry, custom-operation |
| `broken-link-patrol` — Broken link patrol | needs-engine-capability | `schedule` | fetch, create-entry, iterate-aggregate |
| `living-resource-collection` — Living resource collection | needs-engine-capability | `resource_updated` | asset-resource-targets, custom-operation, workflow-approvals |
| `publication-release-gate` — Publication release gate | needs-engine-capability | `entry_updated` | joins, asset-resource-targets |
| `featured-collection-curator` — Featured collection curator | needs-engine-capability | `entry_published` | custom-operation, workflow-approvals |
| `evergreen-resurfacer` — Evergreen resurfacer | needs-engine-capability | `schedule` | relative-dates, custom-operation, create-entry |
| `one-entry-many-voices` — One entry, many voices | needs-engine-capability | `entry_published` | custom-operation, create-entry |
| `carousel-storyteller` — Carousel storyteller | needs-adapter | `entry_published` | media-adapters, custom-operation, social-adapters, workflow-approvals |
| `thread-builder` — Thread builder | needs-engine-capability | `entry_published` | custom-operation, social-adapters |
| `quote-card-studio` — Quote card studio | needs-adapter | `entry_published` | media-adapters, custom-operation, asset-resource-targets |
| `teaser-ladder` — Teaser ladder | needs-engine-capability | `entry_published` | waits, social-adapters, custom-operation |
| `behind-the-scenes-diary` — Behind the scenes diary | needs-engine-capability | `entry_updated` | custom-operation, create-entry, asset-resource-targets |
| `community-question` — Community question | needs-engine-capability | `entry_published` | custom-operation |
| `poll-companion` — Poll companion | needs-adapter | `entry_published` | social-adapters, custom-operation |
| `reply-drafting-desk` — Reply drafting desk | needs-engine-capability | `comment_added` | comments, custom-operation, workflow-approvals |
| `campaign-scoreboard` — Campaign scoreboard | needs-adapter | `schedule` | social-adapters, waits, metrics |
| `social-experiment-log` — Social experiment log | needs-engine-capability | `manual` | custom-operation, metrics |
| `platform-preview-checker` — Platform preview checker | needs-engine-capability | `entry_updated` | branches, fetch, asset-resource-targets, social-adapters |
| `launch-kit` — Launch kit | needs-engine-capability | `entry_published` | custom-operation, create-entry, joins, workflow-approvals |
| `milestone-celebration` — Milestone celebration | needs-engine-capability | `entry_updated` | custom-operation, workflow-approvals, create-entry |
| `event-countdown` — Event countdown | needs-engine-capability | `entry_published` | waits, relative-dates, create-entry |
| `best-of-month` — Best of month | needs-engine-capability | `schedule` | iterate-aggregate, relative-dates, media-adapters, create-entry |
| `community-welcome-pack` — Community welcome pack | needs-engine-capability | subscription: `member_added` | member-email, ops-triggers, custom-operation |
| `alt-text-assistant` — Alt text assistant | needs-engine-capability | `asset_uploaded` | asset-resource-targets |
| `responsive-image-factory` — Responsive image factory | needs-adapter | `asset_uploaded` | media-adapters, asset-resource-targets |
| `background-remover` — Background remover | needs-adapter | `manual` | media-adapters, asset-resource-targets |
| `product-scene-studio` — Product scene studio | needs-engine-capability | `manual` | workflow-approvals, asset-resource-targets, media-adapters |
| `smart-crop-pack` — Smart crop pack | needs-adapter | `asset_uploaded` | media-adapters, asset-resource-targets, workflow-approvals |
| `brand-recolor` — Brand recolor | needs-adapter | `manual` | media-adapters, asset-resource-targets |
| `seasonal-variation` — Seasonal variation | needs-engine-capability | `manual` | workflow-approvals, asset-resource-targets |
| `thumbnail-audition` — Thumbnail audition | needs-engine-capability | `manual` | workflow-approvals, workflow-approvals, asset-resource-targets |
| `image-quality-gate` — Image quality gate | needs-engine-capability | `asset_uploaded` | asset-resource-targets, media-adapters, branches |
| `privacy-crop-desk` — Privacy crop desk | needs-engine-capability | `asset_uploaded` | asset-resource-targets, media-adapters, workflow-approvals |
| `before-after-slider-kit` — Before/after slider kit | needs-adapter | `manual` | media-adapters, create-entry, asset-resource-targets |
| `contact-sheet-maker` — Contact sheet maker | needs-adapter | `manual` | asset-resource-targets, iterate-aggregate, media-adapters |
| `ocr-notebook` — OCR notebook | needs-adapter | `asset_uploaded` | media-adapters, create-entry |
| `document-preview-factory` — Document preview factory | needs-adapter | `asset_uploaded` | media-adapters, asset-resource-targets |
| `file-format-converter` — File format converter | needs-adapter | `asset_uploaded` | media-adapters, asset-resource-targets |
| `attribution-companion` — Attribution companion | needs-engine-capability | `asset_attached_to_entry` | asset-resource-targets |
| `duplicate-asset-scout` — Duplicate asset scout | needs-engine-capability | `asset_uploaded` | asset-resource-targets, branches |
| `image-prompt-archive` — Image prompt archive | needs-engine-capability | `manual` | workflow-approvals, asset-resource-targets |
| `comic-strip-edition` — Comic strip edition | needs-engine-capability | `manual` | custom-operation, workflow-approvals, media-adapters |
| `marvin-margin-notes` — Marvin margin notes | needs-engine-capability | `manual` | custom-operation |
| `ada-explains-it` — Ada explains it | needs-engine-capability | `entry_published` | custom-operation, create-entry |
| `retro-poster-machine` — Retro poster machine | needs-engine-capability | `manual` | workflow-approvals, media-adapters |
| `trading-card-collection` — Trading card collection | needs-engine-capability | `entry_updated` | custom-operation, media-adapters, asset-resource-targets |
| `achievement-cabinet` — Achievement cabinet | needs-engine-capability | `entry_updated` | create-entry, custom-events |
| `meme-workshop` — Meme workshop | needs-engine-capability | `manual` | custom-operation, workflow-approvals, media-adapters |
| `choose-your-own-adventure` — Choose your own adventure | needs-engine-capability | `manual` | custom-operation, create-entry, sandbox |
| `future-newspaper` — Future newspaper | needs-engine-capability | `manual` | custom-operation, media-adapters |
| `workshop-field-guide` — Workshop field guide | needs-engine-capability | `manual` | iterate-aggregate, custom-operation, media-adapters |
| `color-moodboard` — Color moodboard | needs-adapter | `manual` | media-adapters, asset-resource-targets, iterate-aggregate |
| `soundtrack-brief` — Soundtrack brief | needs-engine-capability | `manual` | custom-operation |
| `alternate-universe-cover` — Alternate universe cover | needs-engine-capability | `manual` | workflow-approvals, workflow-approvals |
| `time-capsule` — Time capsule | needs-engine-capability | `entry_updated` | snapshots, waits, create-entry |
| `surprise-remix-button` — Surprise remix button | needs-engine-capability | `manual` | manual-params, custom-operation, create-entry |
| `fictional-debate-club` — Fictional debate club | needs-engine-capability | `manual` | custom-operation, create-entry |
| `agent-directory-intake` — Agent directory intake | needs-engine-capability | `form_submission_received` | fetch, sandbox, branches |
| `resource-availability-watch` — Resource availability watch | needs-engine-capability | `schedule` | fetch, asset-resource-targets, iterate-aggregate |
| `project-milestone-report` — Project milestone report | needs-engine-capability | `entry_updated` | iterate-aggregate, custom-operation, create-entry |
| `knowledge-gap-finder` — Knowledge gap finder | needs-engine-capability | `manual` | collection-scope, custom-operation, create-entry |
| `meeting-notes-to-tasks` — Meeting notes to tasks | needs-engine-capability | `entry_created` | custom-operation, workflow-approvals |
| `release-notes-compiler` — Release notes compiler | needs-engine-capability | `manual` | iterate-aggregate, relative-dates, custom-operation, create-entry |
| `intake-triage` — Intake triage | needs-engine-capability | `form_submission_received` | form-classification, branches, custom-operation |
| `archive-packager` — Archive packager | needs-adapter | `manual` | media-adapters, collection-scope, iterate-aggregate |
| `personal-project-radar` — Personal project radar | needs-engine-capability | `schedule` | relative-dates, custom-operation, create-entry |
| `resource-attachment-notes` — Resource attachment notes | needs-engine-capability | `entry_resource_attached` | asset-resource-targets, custom-operation |
| `entry-schema-impact-report` — Entry schema impact report | needs-engine-capability | `entry_type_updated` | iterate-aggregate, create-entry |
| `asset-attachment-social-kit` — Asset attachment social kit | needs-engine-capability | `asset_attached_to_entry` | asset-resource-targets, custom-operation |

## By category

### Publishing and editorial

- [newsletter-delivery](../../src/marvin/services/automation/recipes/newsletter-delivery.json) — **Newsletter delivery** · verified-current · `entry_published`  
  A published newsletter entry becomes a Buttondown issue; the issue id and delivery result are recorded on the entry.
  - Identical in shape to the Buttondown plugin's own `buttondown-issue-on-publish` blueprint; installing the plugin's content offers it with one click.
  - Replay-safe at the provider: the recorded `buttondown_email_id` is sent back as `email_id`, so a re-publish updates the issue instead of creating a second one.
  - `${site.url}` is the workspace's Canonical URL (None when unset): the provider uses it to absolutise relative links.
- [publication-announcement](../../src/marvin/services/automation/recipes/publication-announcement.json) — **Publication announcement** · verified-current · `entry_published`  
  A published entry is announced to a community channel through an outgoing webhook; the response code is recorded on the entry.
  - The brief's completion event (`newsletter_issue_processed`) is not possible: emit_event only sends entry_* and site_deployment_* events. The run's own `automation_ran` event, with the run id, is the completion signal — a `chained` workflow can react to it.
  - `announcement.run` is the event's correlation id, shared with the run history row.
- [editorial-approval-gate](../../src/marvin/services/automation/recipes/editorial-approval-gate.json) — **Editorial approval gate** · verified-current · `entry_updated`  
  When an entry's status changes to approved it is published; if the publish gate refuses (missing required fields, expiry passed) the entry goes back to Needs review with the exact reasons.
  - Validation is Marvin's own publish gate (services/entries/completeness.py), not a workflow-level check: required fields, required asset roles, resource types, tags and the expiry date.
  - `approved` is a real entry status; the condition uses `changed_to`, so only the transition fires it, not every save of an approved entry.
- [seo-assistant](../../src/marvin/services/automation/recipes/seo-assistant.json) — **SEO assistant** · verified-current · `entry_updated`  
  When an entry is sent to review, AI proposes a search-result description (summary) and tags; the proposals are staged as suggestions for a person to accept.
  - Title generation is not available: no operation writes `title`; summary (meta description) and tags are what the registry offers with a write-back map.
  - “Body changes” cannot be detected: entry_updated's changed_fields covers only status/title/slug. The recipe keys on the review transition instead.
  - Write-back follows the workspace approval mode (services/ai/approval.py): mid-review entries are always staged.
  - Blocked by: `data-change-detection` (to run on body changes rather than the review transition); `custom-operation` (to generate a title)
- `translation-desk` — **Translation desk** · needs-engine-capability · `entry_published`  
  Publication → generate linked translated drafts → route to reviewers
  - Linking translations needs a relationship field or metadata convention (`translation_of`) — set_metadata can record it once the draft exists.
  - Blocked by: `create-entry` (a translated draft is a new entry); `custom-operation` (no translation operation exists); `workflow-approvals` (reviewer routing with a decision)
- `audio-edition` — **Audio edition** · needs-adapter · `entry_published`  
  Publication → narrate article → attach audio → update podcast feed
  - Blocked by: `media-adapters` (a TTS provider action that returns an audio asset); `asset-resource-targets` (attaching the derived asset with lineage)
- `series-index-keeper` — **Series index keeper** · needs-engine-capability · `entry_published`  
  Series member published → refresh ordered index and navigation
  - Possible today (partial): a target query `{collection: <series>}` with `set_metadata` can stamp each member, but no step can read the ordered list to write an index.
  - Blocked by: `iterate-aggregate` (the index is built from all members); `collection-scope` (a series is a collection)
- `weekly-digest` — **Weekly digest** · needs-engine-capability · `schedule`  
  Weekly schedule → aggregate eligible entries → generate newsletter draft
  - Possible today (partial): a schedule (interval 604800 s) + target `{status: published}` runs steps per entry — but each row runs alone, so no digest.
  - Blocked by: `iterate-aggregate` (reduce the week's entries into one input); `relative-dates` (`published_after: -7d` and a weekly cron); `create-entry` (the draft issue); `custom-operation` (write the digest)
- `broken-link-patrol` — **Broken link patrol** · needs-engine-capability · `schedule`  
  Scheduled scan → check links → create repair notes
  - Possible today (partial): a schedule + target `{status: published}` + `request_review` could flag every published entry — but blindly, without checking links.
  - Blocked by: `fetch` (no step can GET a URL and read the status); `create-entry` (repair notes are entries); `iterate-aggregate` (one note per scan, not per link)
- `living-resource-collection` — **Living resource collection** · needs-engine-capability · `resource_updated`  
  Resource changes → locate referring entries → propose passage updates
  - Blocked by: `asset-resource-targets` (resource context and `has_resources`/`resource` target filtering by the triggering resource); `custom-operation` (propose passage updates); `workflow-approvals` (a person accepts the proposal)
- `publication-release-gate` — **Publication release gate** · needs-engine-capability · `entry_updated`  
  Wait until text, images and downloads pass checks → publish together
  - Possible today (partial): the publish gate already blocks on required fields, required asset roles and resource types (completeness rules); the editorial-approval-gate recipe uses it.
  - Blocked by: `joins` (wait for several checks); `asset-resource-targets` (image and file checks)
- [content-refresh](../../src/marvin/services/automation/recipes/content-refresh.json) — **Content refresh** · verified-current · `entry_updated`  
  Every save of a published entry tells an external copy or search index to re-fetch it, through an outgoing webhook.
  - “Body changes” cannot be detected: changed_fields covers only status, title and slug (services/entries/entry_service.py `_TRACKED_FIELDS`). The recipe fires on every save of a published entry, including the publish itself and metadata writes made by other workflows.
  - If the external copy is the site itself, prefer the native rebuild: content changes already queue a coalesced rebuild (site_rebuild_queued → webhook_triggered).
  - Blocked by: `data-change-detection` (to fire only when the body changed); `idempotency` (to coalesce bursts of saves)
- `featured-collection-curator` — **Featured collection curator** · needs-engine-capability · `entry_published`  
  Publication → suggest topic collections → update approved collections
  - Possible today (partial): a fixed rule is possible today: entry_published + conditions on `entry.data.<topic>` + `add_to_collection`.
  - Blocked by: `custom-operation` (suggest collections from the entry and the collection list); `workflow-approvals` (a person approves before add_to_collection)
- [comment-discussion-starter](../../src/marvin/services/automation/recipes/comment-discussion-starter.json) — **Comment discussion starter** · verified-current · `entry_published`  
  A published entry opens a discussion topic in a forum through an outgoing webhook; the topic URL from the response is recorded on the entry.
  - The response field holding the topic URL is a setup variable (`discussion_url_path`) spliced into the `${steps.discussion.output.body.<path>}` template.
- [editorial-task-maker](../../src/marvin/services/automation/recipes/editorial-task-maker.json) — **Editorial task maker** · verified-current · `entry_published`  
  A published entry creates follow-up tasks in your task tool through an n8n flow; the n8n execution id is recorded on the entry.
  - Marvin has no task entity; n8n is the adapter to whichever task tool you use. The two task titles are templates — edit them in the recipe.
- `evergreen-resurfacer` — **Evergreen resurfacer** · needs-engine-capability · `schedule`  
  Schedule → find older relevant content → propose refreshed drafts
  - Possible today (partial): a schedule + target `{status: published, published_before: "2025-01-01"}` (an absolute date) + `generate-summary` works today but the date must be re-typed.
  - Blocked by: `relative-dates` (`published_before: -365d` in the target); `custom-operation` (propose a refresh); `create-entry` (a refreshed draft beside the original)

### Social and community

- `one-entry-many-voices` — **One entry, many voices** · needs-engine-capability · `entry_published`  
  Publication → draft LinkedIn, short-post and community versions preserving meaning
  - Possible today (partial): `improve-writing` proposes one rewrite of one field (no write-back); its output can be stored with set_metadata.
  - Blocked by: `custom-operation` (per-channel rewrites with a persona); `create-entry` (drafts as entries (or a `social_drafts` metadata convention))
- `carousel-storyteller` — **Carousel storyteller** · needs-adapter · `entry_published`  
  Article → outline slides → render branded carousel → queue draft
  - Blocked by: `media-adapters` (render slides); `custom-operation` (outline); `social-adapters` (queue a draft); `workflow-approvals` (openai_images.generate requires approval)
- `thread-builder` — **Thread builder** · needs-engine-capability · `entry_published`  
  Article → ordered thread with links → save draft sequence
  - Blocked by: `custom-operation` (thread generation); `social-adapters` (draft on the network)
- `quote-card-studio` — **Quote card studio** · needs-adapter · `entry_published`  
  Extract exact attributed quote → render branded card → attach social draft
  - Blocked by: `media-adapters` (render the card); `custom-operation` (exact quote extraction with verification); `asset-resource-targets` (attach the derived asset)
- `teaser-ladder` — **Teaser ladder** · needs-engine-capability · `entry_published`  
  Launch → schedule teaser, launch post and follow-up variants
  - Blocked by: `waits` (post at offsets from the launch); `social-adapters` (publish); `custom-operation` (variants)
- `behind-the-scenes-diary` — **Behind the scenes diary** · needs-engine-capability · `entry_updated`  
  Project update → turn process photos and notes into a workshop post
  - Blocked by: `custom-operation` (write the post from notes and photos); `create-entry` (the post); `asset-resource-targets` (read the attached photos (vision))
- `community-question` — **Community question** · needs-engine-capability · `entry_published`  
  Publication → generate specific discussion question → queue channel post
  - Possible today (partial): the webhook half exists: see publication-announcement; `generate-summary` output can be posted as `${steps.summary.output.summary}`.
  - Blocked by: `custom-operation` (generate the question)
- `poll-companion` — **Poll companion** · needs-adapter · `entry_published`  
  Article → propose poll options → create poll draft
  - Blocked by: `social-adapters` (a poll-capable provider); `custom-operation` (options)
- `reply-drafting-desk` — **Reply drafting desk** · needs-engine-capability · `comment_added`  
  New comment → classify intent → suggest reply → wait for approval
  - Instagram comments: the Instagram plugin's `auto_reply` runs from a scheduled task with its own rules; its reply actions are requires_approval and cannot run from a workflow.
  - Blocked by: `comments` (no comment events are ever sent); `custom-operation` (classify and draft); `workflow-approvals` (wait for approval)
- `campaign-scoreboard` — **Campaign scoreboard** · needs-adapter · `schedule`  
  After campaign → collect supported metrics → compare against baseline
  - Blocked by: `social-adapters` (metrics actions); `waits` (after the campaign); `metrics` (baseline comparison)
- `social-experiment-log` — **Social experiment log** · needs-engine-capability · `manual`  
  Create two draft variants → assign experiment IDs → report observed results
  - Possible today (partial): set_metadata can stamp an experiment id (`${event.correlation_id}`) on an entry today.
  - Blocked by: `custom-operation` (variants); `metrics` (observations)
- `platform-preview-checker` — **Platform preview checker** · needs-engine-capability · `entry_updated`  
  Draft → check length, links, image ratio and preview → flag fixes
  - Blocked by: `branches` (flag only what fails); `fetch` (link checks); `asset-resource-targets` (image ratio); `social-adapters` (per-network limits)
- `launch-kit` — **Launch kit** · needs-engine-capability · `entry_published`  
  Product entry → assemble announcement, FAQ, images and newsletter draft
  - Blocked by: `custom-operation` (each piece); `create-entry` (drafts); `joins` (assemble in parallel); `workflow-approvals` (image generation requires approval)
- `milestone-celebration` — **Milestone celebration** · needs-engine-capability · `entry_updated`  
  Project complete → generate grounded achievement post and visual
  - Possible today (partial): `entry.data.<status> changed_to complete` is not detectable (changed_fields covers status/title/slug only); `entry.data.status eq complete` on entry_updated fires on every save while complete.
  - Blocked by: `custom-operation` (the post); `workflow-approvals` (openai_images.generate requires approval); `create-entry` (the post as a draft)
- `event-countdown` — **Event countdown** · needs-engine-capability · `entry_published`  
  Event entry → create reminder drafts relative to event date
  - Blocked by: `waits` (fire at date offsets); `relative-dates` (date arithmetic in templates); `create-entry` (reminder drafts)
- `best-of-month` — **Best of month** · needs-engine-capability · `schedule`  
  Monthly schedule → select published highlights → create recap carousel
  - Blocked by: `iterate-aggregate` (the month's set as one input); `relative-dates` (monthly cron + `published_after: -30d`); `media-adapters` (render the carousel); `create-entry` (the recap)
- [utm-librarian](../../src/marvin/services/automation/recipes/utm-librarian.json) — **UTM librarian** · verified-current · `entry_created`  
  A new campaign entry gets a tracking link built from its URL and UTM fields, recorded in metadata with the campaign mapping.
  - Pure string templating: `${entry.url}?utm_source=${entry.data.utm_source}&…` — values must already be URL-safe.
  - `entry.url` is absolute when the workspace Canonical URL is set, else the site path.
- `community-welcome-pack` — **Community welcome pack** · needs-engine-capability · subscription: `member_added`  
  Opt-in member event → assemble relevant reading links → draft welcome
  - Possible today (partial): see new-member-welcome for the admin-facing notification that works today.
  - Blocked by: `member-email` (address the member); `ops-triggers` (member events as triggers); `custom-operation` (assemble the pack)

### Images and files

- `alt-text-assistant` — **Alt text assistant** · needs-engine-capability · `asset_uploaded`  
  Image added → describe visible content → save editable alt text
  - The operation exists (`generate-alt-text`, asset, requires_vision) and works from the operations API; only the workflow runner lacks the asset path.
  - Blocked by: `asset-resource-targets` (load the image for `generate-alt-text` and write `alt_text` back)
- `responsive-image-factory` — **Responsive image factory** · needs-adapter · `asset_uploaded`  
  Image added → create requested sizes and formats → link derivatives
  - Marvin's `media_enrich` handler runs an entry type's recipe media derivations for one entry — the nearest existing primitive (entry-scoped, not asset-scoped).
  - Blocked by: `media-adapters` (resize/convert); `asset-resource-targets` (derivative lineage)
- `background-remover` — **Background remover** · needs-adapter · `manual`  
  Selected product image → remove background → save transparent derivative
  - Blocked by: `media-adapters` (a background-removal provider); `asset-resource-targets` (derivative)
- `product-scene-studio` — **Product scene studio** · needs-engine-capability · `manual`  
  Product image → create styled scenes while preserving product details → review
  - Blocked by: `workflow-approvals` (`openai_images.generate` is requires_approval and is refused by the integration step (actions/integration.py)); `asset-resource-targets` (reference image + derivative); `media-adapters` (image editing)
- `smart-crop-pack` — **Smart crop pack** · needs-adapter · `asset_uploaded`  
  Image → focal-point crops for square, portrait and landscape → preview
  - Blocked by: `media-adapters` (focal-point crop); `asset-resource-targets` (derivatives); `workflow-approvals` (preview before saving)
- `brand-recolor` — **Brand recolor** · needs-adapter · `manual`  
  Selected artwork → apply brand palette → save derivative
  - Blocked by: `media-adapters` (recolor); `asset-resource-targets` (derivative)
- `seasonal-variation` — **Seasonal variation** · needs-engine-capability · `manual`  
  Approved graphic → seasonal variants → retain original and lineage
  - Blocked by: `workflow-approvals` (`openai_images.generate` is requires_approval and is refused by the integration step (actions/integration.py)); `asset-resource-targets` (lineage)
- `thumbnail-audition` — **Thumbnail audition** · needs-engine-capability · `manual`  
  Entry → generate three thumbnail concepts → user selects one
  - Blocked by: `workflow-approvals` (`openai_images.generate` is requires_approval and is refused by the integration step (actions/integration.py)); `workflow-approvals` (a choice among three); `asset-resource-targets` (attach the chosen one)
- `image-quality-gate` — **Image quality gate** · needs-engine-capability · `asset_uploaded`  
  Upload → check dimensions, blur and orientation → flag or normalize
  - Blocked by: `asset-resource-targets` (asset facts in context); `media-adapters` (blur/orientation analysis); `branches` (flag or normalise)
- `privacy-crop-desk` — **Privacy crop desk** · needs-engine-capability · `asset_uploaded`  
  Image → propose sensitive-region masking → approve redacted derivative
  - Blocked by: `asset-resource-targets` (vision on the asset); `media-adapters` (masking); `workflow-approvals` (approve the redaction)
- `before-after-slider-kit` — **Before/after slider kit** · needs-adapter · `manual`  
  Pair original and derivative → generate comparison asset and entry
  - Blocked by: `media-adapters` (render the comparison); `create-entry` (the entry); `asset-resource-targets` (pairing by lineage)
- `contact-sheet-maker` — **Contact sheet maker** · needs-adapter · `manual`  
  Query related images → label and render contact sheet
  - Blocked by: `asset-resource-targets` (asset queries); `iterate-aggregate` (many → one sheet); `media-adapters` (render)
- `ocr-notebook` — **OCR notebook** · needs-adapter · `asset_uploaded`  
  Image or PDF → extract text → retain page references → create draft notes
  - Blocked by: `media-adapters` (OCR / PDF text extraction); `create-entry` (notes)
- `document-preview-factory` — **Document preview factory** · needs-adapter · `asset_uploaded`  
  File upload → render cover and page previews → attach derivatives
  - Blocked by: `media-adapters` (PDF rendering); `asset-resource-targets` (derivatives)
- `file-format-converter` — **File format converter** · needs-adapter · `asset_uploaded`  
  Uploaded file → supported output formats → save download references
  - Blocked by: `media-adapters` (conversion); `asset-resource-targets` (derivatives)
- `attribution-companion` — **Attribution companion** · needs-engine-capability · `asset_attached_to_entry`  
  Asset → read supplied license and credit fields → compose credit block
  - Possible today (partial): on asset_attached_to_entry a set_metadata step can record `${event.asset_name}` on the entry — but not the asset's own fields.
  - Blocked by: `asset-resource-targets` (read the asset's license/credit fields in a template)
- `duplicate-asset-scout` — **Duplicate asset scout** · needs-engine-capability · `asset_uploaded`  
  Upload → compare hashes or similarity → suggest existing asset
  - Assets already store a `checksum`; a query key for it would make this a one-step recipe.
  - Blocked by: `asset-resource-targets` (asset queries by checksum); `branches` (only when a match exists)
- `image-prompt-archive` — **Image prompt archive** · needs-engine-capability · `manual`  
  Generation → save prompt, model, seed if available and parent references
  - `openai_images.generate` returns `usage` (provider, model, tokens) and images (b64 or URL) but no asset is created from a workflow.
  - Blocked by: `workflow-approvals` (`openai_images.generate` is requires_approval and is refused by the integration step (actions/integration.py)); `asset-resource-targets` (write prompt/model/parent onto the generated asset)

### Playful experiments

- `comic-strip-edition` — **Comic strip edition** · needs-engine-capability · `manual`  
  Article → four-panel fictional adaptation → generate panels → review
  - Blocked by: `custom-operation` (a free-form prompt with a persona resource; built-in operations have fixed prompts); `workflow-approvals` (`openai_images.generate` is requires_approval and is refused by the integration step (actions/integration.py)); `media-adapters` (layout)
- `marvin-margin-notes` — **Marvin margin notes** · needs-engine-capability · `manual`  
  Entry → draft dry pessimistic commentary in a configurable persona
  - Possible today (partial): `improve-writing` with `input.tone` proposes a rewrite in a tone, stored via set_metadata — a tone, not a persona.
  - Blocked by: `custom-operation` (a free-form prompt with a persona resource; built-in operations have fixed prompts)
- `ada-explains-it` — **Ada explains it** · needs-engine-capability · `entry_published`  
  Technical article → warm folksy explanation as a clearly marked adaptation
  - Blocked by: `custom-operation` (a free-form prompt with a persona resource; built-in operations have fixed prompts); `create-entry` (the adaptation as its own draft)
- `retro-poster-machine` — **Retro poster machine** · needs-engine-capability · `manual`  
  Project → fictional vintage poster with accurate project title
  - Blocked by: `workflow-approvals` (`openai_images.generate` is requires_approval and is refused by the integration step (actions/integration.py)); `media-adapters` (typography rendering)
- `trading-card-collection` — **Trading card collection** · needs-engine-capability · `entry_updated`  
  Project milestone → create collectible card with grounded stats
  - Blocked by: `custom-operation` (a free-form prompt with a persona resource; built-in operations have fixed prompts); `media-adapters` (render the card); `asset-resource-targets` (attach it)
- `achievement-cabinet` — **Achievement cabinet** · needs-engine-capability · `entry_updated`  
  Milestone event → award configured badge → update project collection
  - Possible today (partial): `add_to_collection` on a condition (`entry.data.milestone eq shipped`) works today — the badge itself can't be created.
  - Blocked by: `create-entry` (a badge entry); `custom-events` (a `milestone` event)
- `meme-workshop` — **Meme workshop** · needs-engine-capability · `manual`  
  Entry → propose caption concepts → render selected approved template
  - Blocked by: `custom-operation` (a free-form prompt with a persona resource; built-in operations have fixed prompts); `workflow-approvals` (select a caption); `media-adapters` (render onto a template asset)
- `choose-your-own-adventure` — **Choose your own adventure** · needs-engine-capability · `manual`  
  Story entry → generate branching draft and check reachable endings
  - Blocked by: `custom-operation` (a free-form prompt with a persona resource; built-in operations have fixed prompts); `create-entry` (one entry per branch); `sandbox` (graph reachability check)
- `future-newspaper` — **Future newspaper** · needs-engine-capability · `manual`  
  Project notes → clearly labeled speculative future front page
  - Blocked by: `custom-operation` (a free-form prompt with a persona resource; built-in operations have fixed prompts); `media-adapters` (document rendering)
- `workshop-field-guide` — **Workshop field guide** · needs-engine-capability · `manual`  
  Process notes → illustrated tools and steps → printable guide
  - Blocked by: `iterate-aggregate` (many notes → one guide); `custom-operation` (a free-form prompt with a persona resource; built-in operations have fixed prompts); `media-adapters` (PDF rendering)
- `color-moodboard` — **Color moodboard** · needs-adapter · `manual`  
  Selected assets → extract palette → produce moodboard and design notes
  - Blocked by: `media-adapters` (palette extraction + render); `asset-resource-targets` (asset selection); `iterate-aggregate` (many → one)
- `soundtrack-brief` — **Soundtrack brief** · needs-engine-capability · `manual`  
  Story → suggest mood, tempo and instrumentation → save production brief
  - Possible today (partial): once a free-form operation exists, `set_data` can store its output in the type's own fields today.
  - Blocked by: `custom-operation` (a free-form prompt with a persona resource; built-in operations have fixed prompts)
- `alternate-universe-cover` — **Alternate universe cover** · needs-engine-capability · `manual`  
  Entry → sci-fi, noir or botanical cover variations → review
  - Blocked by: `workflow-approvals` (`openai_images.generate` is requires_approval and is refused by the integration step (actions/integration.py)); `workflow-approvals` (review and pick)
- `time-capsule` — **Time capsule** · needs-engine-capability · `entry_updated`  
  Capture approved project snapshot → schedule retrospective draft
  - Blocked by: `snapshots` (capture the version); `waits` (months later); `create-entry` (the retrospective)
- `surprise-remix-button` — **Surprise remix button** · needs-engine-capability · `manual`  
  Manual run → choose allowed transformation → save new draft
  - A manual run has no entry; today a target query selects the set, and every row runs the same steps.
  - Blocked by: `manual-params` (pick the entry and the transformation at run time); `custom-operation` (a free-form prompt with a persona resource; built-in operations have fixed prompts); `create-entry` (the remix as a new draft)
- `fictional-debate-club` — **Fictional debate club** · needs-engine-capability · `manual`  
  Entry → draft clearly fictional dialogue between configured viewpoints
  - Blocked by: `custom-operation` (a free-form prompt with a persona resource; built-in operations have fixed prompts); `create-entry` (the dialogue as a draft)

### Operations and knowledge

- [client-handoff](../../src/marvin/services/automation/recipes/client-handoff.json) — **Client handoff** · verified-current · `entry_updated`  
  When an entry's status changes to the configured ready status it is posted to the client's intake endpoint; the endpoint's JSON response is stored on the entry as the receipt.
  - `ready_status` must be one of Marvin's statuses (needs_review, approved, published); `changed_to` fires once on the transition.
  - The whole `entry.data` object is sent — review what the type's fields contain before enabling.
  - Blocked by: `idempotency` (to never hand off the same version twice)
- `agent-directory-intake` — **Agent directory intake** · needs-engine-capability · `form_submission_received`  
  Agent submission → validate capability document → sandbox checks → review
  - Possible today (partial): form-intake-desk covers the intake half (record, review, notify).
  - Blocked by: `fetch` (retrieve the capability document); `sandbox` (schema validation); `branches` (pass/fail routing)
- `resource-availability-watch` — **Resource availability watch** · needs-engine-capability · `schedule`  
  Schedule → check known resource URLs → flag changed availability
  - Blocked by: `fetch` (HEAD/GET each URL); `asset-resource-targets` (resources as targets); `iterate-aggregate` (one report)
- `project-milestone-report` — **Project milestone report** · needs-engine-capability · `entry_updated`  
  Completion → assemble linked outcomes → create report draft
  - Blocked by: `iterate-aggregate` (linked outcomes); `custom-operation` (write the report); `create-entry` (the draft)
- `knowledge-gap-finder` — **Knowledge gap finder** · needs-engine-capability · `manual`  
  Collection → find missing coverage → propose article backlog
  - Possible today (partial): `answer-workspace-question` (retrieval) can answer “what topics are missing?” as one step output today — nothing can turn the answer into entries.
  - Blocked by: `collection-scope` (read the collection); `custom-operation` (find gaps); `create-entry` (backlog items)
- `meeting-notes-to-tasks` — **Meeting notes to tasks** · needs-engine-capability · `entry_created`  
  Notes entry → extract commitments with evidence → draft tasks
  - Possible today (partial): the task half exists: editorial-task-maker shows n8n `trigger_workflow` creating tasks from templated data.
  - Blocked by: `custom-operation` (extract commitments as structured output); `workflow-approvals` (approve before creating)
- `release-notes-compiler` — **Release notes compiler** · needs-engine-capability · `manual`  
  Query changes → group and summarize → create release draft
  - Blocked by: `iterate-aggregate` (the change set as one input); `relative-dates` (since the last release); `custom-operation` (summarise); `create-entry` (the draft)
- `intake-triage` — **Intake triage** · needs-engine-capability · `form_submission_received`  
  New request → classify → assign queue → draft clarifying questions
  - Possible today (partial): form-intake-desk records, reviews and notifies; routing by a classification needs branches (or a second workflow keyed on metadata written by the first).
  - Blocked by: `form-classification` (`classify-form-submission` gets no submission context from the workflow runner); `branches` (route by category / is_spam); `custom-operation` (clarifying questions)
- [failure-repair-desk](../../src/marvin/services/automation/recipes/failure-repair-desk.json) — **Failure repair desk** · verified-current · `on_error` (`automation_failed`)  
  When any workflow run fails on an entry and the integration's error policy did not handle it, the entry is sent to Needs review with the workflow name and error as the reason.
  - The on_error trigger listens to `automation_failed`; the failed run names its entry as `event.trigger_entity_type/id`, which the entry step targets explicitly (`entity_id`).
  - A “repair task” in an external tool is one more step away: add an n8n `trigger_workflow` step (see editorial-task-maker).
  - The native `workflow_failed` alert (Automation → Notifications) already emails/pushes admins once per incident; this recipe adds the in-content flag.
- [publication-ledger](../../src/marvin/services/automation/recipes/publication-ledger.json) — **Publication ledger** · verified-current · `entry_published`  
  Every publication of the configured type records who published, the run's correlation id, the URL and slug in the entry's metadata; the run history holds the per-step record.
  - “Expose execution history” exists natively: GET /api/automations/{id}/executions (+ /{execution_id}) lists runs, steps, outputs and retry chains; `run` here is the correlation id shared with the event log.
  - There is no timestamp template; the run history and event log carry the time.
- `archive-packager` — **Archive packager** · needs-adapter · `manual`  
  Collection → gather entries and permitted files → generate ZIP with manifest
  - Blocked by: `media-adapters` (zip + manifest); `collection-scope` (the collection's entries and files); `iterate-aggregate` (many → one)
- `personal-project-radar` — **Personal project radar** · needs-engine-capability · `schedule`  
  Schedule → identify stalled projects → draft small next actions
  - Possible today (partial): a schedule + target `{entry_type: project, status: draft, updated_before: "<absolute date>"}` + `request_review` flags stalled projects today, with the date re-typed.
  - Blocked by: `relative-dates` (`updated_before: -14d`); `custom-operation` (next actions); `create-entry` (or set_data onto the project)

### Event-driven extensions

- [blocked-publication-rescue](../../src/marvin/services/automation/recipes/blocked-publication-rescue.json) — **Blocked publication rescue** · verified-current · `entry_scheduled_publish_blocked`  
  When a scheduled publish is held (unmet requirements, expiry, or approval-only publishing) the entry is sent to Needs review with the exact reason and an editor is notified with a link.
  - entry_scheduled_publish_blocked is sent once per distinct reason (and again after an edit), not every 5 minutes — so this does not spam.
  - Marvin already pushes this event to people with the app (services/push_notifications.py); this recipe adds the in-content flag and a channel notice.
  - `event.waiting_for` is `requirements` or `approval`; `event.reason` is the one-line explanation, `event.issues` the list.
- [form-intake-desk](../../src/marvin/services/automation/recipes/form-intake-desk.json) — **Form intake desk** · verified-current · `form_submission_received`  
  A public submission to the configured entry type is stamped with intake facts, sent to Needs review for triage, and the owner is notified with the message.
  - The brief's “classify” step is not possible yet: `classify-form-submission` receives no submission context from the workflow runner (it reads the legacy FormSubmissions table). See intake-triage.
  - Marvin already creates the entry (status inbox, or needs_review when protection flagged it) and pushes form_submission_received to people with the app.
  - Legacy Forms (the Forms table) also send this event, but with no entry — the `entry.entry_type` condition keeps the recipe to submittable entry types.
  - Blocked by: `form-classification` (to classify before routing); `branches` (to route spam to the Trash and the rest to a queue)
- [submission-surge-alert](../../src/marvin/services/automation/recipes/submission-surge-alert.json) — **Submission surge alert** · verified-current · `submission_surge_detected`  
  When one form receives an unusual burst of submissions, the form owner is notified with the counts; nothing is deleted.
  - The event has no entry (entity_type entry_type); entry steps would fail here. The counts come straight from `$event.submission_count / threshold / window_minutes`.
- `host-rebuild-dispatch` — **Host rebuild dispatch** · supported-after-configuration · subscription: `webhook_triggered`  
  Once Marvin's coalesced rebuild is sent (webhook_triggered, “Site Rebuild Sent”), your host's deploy hook is called — through an event-driven outgoing webhook or an integration action subscription, never a workflow.
  - webhook_triggered is NOT a workflow trigger (event catalog `triggerable=False`); a workflow with `event: webhook_triggered` passes structural validation but never fires — the authoring validator rejects it.
  - Do not also subscribe to entry_updated or site_rebuild_queued: that is the double-deployment path the brief warns about.
- [deployment-celebration](../../src/marvin/services/automation/recipes/deployment-celebration.json) — **Deployment celebration** · verified-current · `site_deployment_completed`  
  When the host reports a successful deployment (site_deployment_completed) a success notice with the site URL and deployment id is sent.
  - “Optionally draft a release announcement” needs a create-entry action (roadmap).
  - No host reports deployments to Marvin by itself: there is no dedicated callback endpoint; the incoming webhook + emit_event pair is the path.
  - Blocked by: `create-entry` (to draft the announcement)
- [deployment-failure-desk](../../src/marvin/services/automation/recipes/deployment-failure-desk.json) — **Deployment failure desk** · verified-current · `site_deployment_failed`  
  When the host reports a failed deployment (site_deployment_failed) the maintainer is notified with the error, deployment id and site.
  - A repair task is one n8n step away (see editorial-task-maker); creating a Marvin entry for it needs the create-entry action.
  - Blocked by: `create-entry` (to open a repair task entry)
- `integration-health-companion` — **Integration health companion** · supported-after-configuration · subscription: `integration_attention_needed`  
  Marvin's own integration alerts (deduplicated, with reminders) reach your channels; nothing duplicates them.
  - Not a workflow: integration_attention_needed is deliberately not triggerable (a reacting workflow could call the failing connection). The “repair task” half would need the event as a trigger (roadmap: ops-triggers) or an integration event subscription to n8n.
  - Blocked by: `ops-triggers` (to open a repair task from the alert)
- `connection-recovery-log` — **Connection recovery log** · supported-after-configuration · subscription: `integration_attention_resolved`  
  When a connection that needed attention works again, the recovery is delivered to every channel that got the alert (native) and, optionally, recorded by an external log sink.
  - The recovery notice itself is native (services/integrations/errors.py `resolved_channel_rows`): nothing to configure for the channels that delivered the alert.
- `webhook-repair-desk` — **Webhook repair desk** · supported-after-configuration · subscription: `webhook_delivery_failed`  
  When an outgoing webhook fails after its retries, people hear about it on a channel that does not depend on that webhook.
  - Not a workflow: webhook_delivery_failed is hidden from triggers. The webhook's own delivery log (GET /api/groups/webhooks/{id}/logs) is the repair context.
  - Blocked by: `ops-triggers` (to open a repair task automatically)
- `scheduled-task-watchdog` — **Scheduled task watchdog** · supported-after-configuration · subscription: `scheduled_task_failed`  
  A failing scheduled task alerts once per incident and announces its recovery; the task's history is the repair context.
  - Not a workflow: scheduled_task_* are internal scheduler events, not triggerable. A workflow run on a schedule that fails reports through `automation_failed` (the `workflow_failed` kind), not here.
- `ai-spending-heads-up` — **AI spending heads-up** · supported-after-configuration · subscription: `ai_budget_threshold_reached`  
  When the workspace crosses its AI budget warning percentage, admins get an email with the spend and limit.
  - Not a workflow trigger. “Propose cheaper options” is a concept (would need the model list and pricing as event fields).
- `ai-budget-pause-desk` — **AI budget pause desk** · supported-after-configuration · subscription: `ai_budget_exceeded`  
  When the AI budget is exceeded admins are told; Marvin itself already refuses new AI runs (including workflow operation steps) until the month rolls over or the limit changes.
  - The pause is native (services/ai/budget.py `blocked_reason`); there is no workflow action to pause or resume AI. “Identify blocked work” = the AI executions list filtered by failed.
- `ai-quota-recovery-desk` — **AI quota recovery desk** · supported-after-configuration · subscription: `ai_provider_quota_exceeded`  
  When the AI provider reports its quota exhausted, admins are told which operation hit it.
  - “Suggest configured provider alternatives” is a concept; the event carries provider_type and operation_slug only.
- `agent-approval-inbox` — **Agent approval inbox** · supported-after-configuration · subscription: `approval_requested`  
  People get a push notification with Approve / Deny when an agent asks for a tool approval; nothing approves automatically.
  - These are agent tool-call approvals; they are not a pause for arbitrary workflow steps (roadmap: workflow-approvals).
- [collection-welcome-mat](../../src/marvin/services/automation/recipes/collection-welcome-mat.json) — **Collection welcome mat** · verified-current · `entry_added_to_collection`  
  An entry added to the configured collection that has no summary gets one from AI (applied to drafts, staged as a suggestion for anything further along) — so the collection always reads well.
  - A narrower reading of the brief: the entry's summary is refreshed, not the collection's (a collection has no summary field and no step can read a collection's entries). A themed roundup needs collection-scope + create-entry.
  - The event carries `collection_name` (not the slug), so the condition compares the name.
  - Blocked by: `collection-scope` (a summary of the collection itself); `create-entry` (a roundup draft)
- `resource-attachment-notes` — **Resource attachment notes** · needs-engine-capability · `entry_resource_attached`  
  Draft an entry-specific material/technique/supplier note from linked resource
  - Possible today (partial): `generate-summary` on the entry sees its linked resources (ContextBuilder.with_resources) — a summary, not a note.
  - Blocked by: `asset-resource-targets` (the attached resource's fields in context (the event carries only resource_name)); `custom-operation` (draft the note)
- `entry-schema-impact-report` — **Entry schema impact report** · needs-engine-capability · `entry_type_updated`  
  Find impacted entries and report validation changes before migration
  - Possible today (partial): a target `{entry_type: "${event.entry_type_slug}"}` + `request_review` flags every entry of the type — a blunt instrument, no report.
  - Blocked by: `iterate-aggregate` (one report over the type's entries); `create-entry` (the report)
- `asset-attachment-social-kit` — **Asset attachment social kit** · needs-engine-capability · `asset_attached_to_entry`  
  Draft a caption and crop suggestions for the entry's newly attached image
  - Possible today (partial): `generate-summary` on the entry runs today (text only).
  - Blocked by: `asset-resource-targets` (vision on the attached asset (`describe-image` gets no image from the runner)); `custom-operation` (caption)
- `new-member-welcome` — **New member welcome** · supported-after-configuration · subscription: `member_added`  
  Admins (or a fixed address) are emailed when a member joins, with the member's name and role; the token-free payload is all the template sees.
  - The member cannot be addressed: member_added carries no email (recipient_type `event_field` has nothing to resolve). Invited members already receive Marvin's system invitation email.
  - Blocked by: `member-email` (to welcome the member directly with role-appropriate links)
- `api-token-rotation-notice` — **API token rotation notice** · supported-after-configuration · subscription: `api_client_token_rotated`  
  Admins are emailed when an API client's token is rotated; the payload carries the client name and token prefix, never the token.
  - api_client_* events are workspace-scope and audit-locked (always in the Event Log). Not a workflow trigger.

### Starter examples

- [unpublish-entries-with-images](../../src/marvin/services/automation/recipes/unpublish-entries-with-images.json) — **Move every entry with an image back to draft** · verified-current · `manual`  
  A manual run selects every published entry that has an image attached and moves each back to draft.
  - A manual run skips the trigger gate but a `target` still applies its conditions as the WHERE clause.
  - Dry-run it first: POST /api/automations/{id}/run?dry_run=true lists the entries it would touch.
- [summarise-and-feature-on-publish](../../src/marvin/services/automation/recipes/summarise-and-feature-on-publish.json) — **Summarise a published entry and add it to a collection** · verified-current · `entry_published`  
  When an entry of the configured type is published, AI writes (or proposes) a summary and the entry joins the configured collection.
  - A published entry is never a draft, so under allow-draft-update the summary is staged as a suggestion, not applied.
- [hourly-site-rebuild](../../src/marvin/services/automation/recipes/hourly-site-rebuild.json) — **Every hour, rebuild the site** · verified-current · `schedule`  
  On an interval, a site rebuild is requested; Marvin coalesces requests and sends one webhook_triggered to the deploy target.
  - Interval and once schedules fire; `cron` is accepted but never computes a next run (croniter is not a dependency).
  - The schedule's own run has no event: `${event.*}` is empty and conditions are skipped (a `target` still applies).
- [archive-entry-from-webhook](../../src/marvin/services/automation/recipes/archive-entry-from-webhook.json) — **A webhook call finds an entry by slug and archives it** · verified-current · `incoming_webhook`  
  An external system POSTs `{"slug": …}` to an incoming webhook URL; the named entry is archived, or sent to review with the error when it can't be.
  - `webhook: any` matches every incoming webhook of the workspace; name one slug to scope it.
- [trash-unattached-images](../../src/marvin/services/automation/recipes/trash-unattached-images.json) — **Trash every unattached image** · verified-current · `manual`  
  A manual run moves every image that no entry uses into the Trash, where it can be restored until the Trash is emptied.
  - A bare `trash` step acts on the current item: its entity_type follows the target.
  - Dry-run it first: POST /api/automations/{id}/run?dry_run=true lists the assets it would touch.
- [restore-trashed-resources](../../src/marvin/services/automation/recipes/restore-trashed-resources.json) — **Restore all resources in the Trash** · verified-current · `manual`  
  A manual run takes every trashed resource back out of the Trash.
  - `trashed: true` is the only way a target reaches the Trash; every other query leaves trashed rows out.
- [asset-upload-announcement](../../src/marvin/services/automation/recipes/asset-upload-announcement.json) — **Post new uploads to a chat channel** · verified-current · `asset_uploaded`  
  Every upload is announced in a chat channel with its type, name, MIME type and public URL.
  - `${asset.url}` is the public URL when the storage provider serves one, otherwise empty.

## Capability gaps

| Id | Capability | Priority | Recipes blocked | Acceptance |
|---|---|---|---|---|
| `custom-operation` | Free-form AI operation | P0 | 38 | An operation step can carry its own prompt and JSON output schema (or name a workspace-defined operation with a persona resource); the parsed, schema-validated output is the step output; budget, approval mode and min_role apply exactly as for built-in operations. |
| `asset-resource-targets` | Assets and resources as workflow subjects | P1 | 28 | asset_*/resource_* events hydrate `asset.*` / `resource.*` in the match context; an operation step with entity_type asset loads the image for vision ops and writes back `alt_text`; the target selector accepts entity asset|resource; derived assets record lineage (parent, operation, params). |
| `create-entry` | Create-entry action | P0 | 26 | An entry step `{"op": "create", "entry_type": …, "title": …, "data": {…}, "status": "draft"}` creates a schema-validated entry, returns `entry_id`/`slug` as step output, emits entry_created at depth+1, previews in a dry run, and never duplicates on a retried run (idempotency key = run + step). |
| `media-adapters` | Image, file and audio processing adapters | P1 | 24 | SDK capabilities for resize/crop/convert/OCR/render/TTS/zip exist as integration actions with declared input/output schemas; outputs are stored as derived assets with lineage; originals are never modified. |
| `workflow-approvals` | Approval step inside a workflow | P1 | 20 | A step parks the run durably, notifies approvers (reusing the Approve/Deny push used for agent approvals), resumes with `${steps.<id>.output.decision}`, expires, and re-checks the entry's version before applying; integration actions marked requires_approval may run after an approval step. |
| `iterate-aggregate` | Iterate / aggregate over a target set | P1 | 12 | A target-selected set can be reduced into one output (`${target.rows}` / an aggregate step) so one step sees all rows, bounded by the target cap, with per-row errors recorded; a schedule trigger + target + aggregate step produces a digest payload in a dry run. |
| `branches` | Conditional steps (if/else) | P0 | 6 | A step can declare `when` conditions evaluated against `steps.*` / `previous.*` (same operators as today); a false condition records the step as skipped (not failed) and later templates referencing it resolve to None; the dry run shows which branch would run. |
| `relative-dates` | Relative dates and cron schedules | P1 | 6 | `updated_before: "-30d"` (and `now`-relative `${…}` arithmetic) is accepted by entries/query.py `_when` and shown resolved in the preview; `schedule_type: cron` computes `next_run_at` with its timezone (croniter) and fires on the tick. |
| `social-adapters` | Social publishing adapters | P1 | 6 | Providers for the networks in use expose draft/publish/metrics actions; publish actions are requires_approval by default; drafts are stored on the entry (metadata or a linked entry). |
| `collection-scope` | Collection-scoped steps | P1 | 4 | A step can read a collection's entries (`${collection.entries}`) and an operation can run over that set to produce one output (summary, roundup). |
| `fetch` | HTTP fetch step | P1 | 4 | A GET/HEAD step (SSRF-guarded, bounded body) returns status, headers and parsed body as step output; a link-check handler reports broken links for one entry. |
| `waits` | Durable waits and delays | P1 | 4 | `{"kind": "wait", "until": "${entry.data.event_date} - 7d"}` persists the run, survives a restart, honours the workspace timezone and DST, can be cancelled, and resumes exactly once. |
| `ops-triggers` | Operational events as workflow triggers | P2 | 3 | ai_budget_*, integration_attention_*, webhook_delivery_failed and scheduled_task_failed become triggerable with origin filtering (a workflow never reacts to a failure its own run caused) and an independent fallback channel. |
| `data-change-detection` | Data-field change detection | P1 | 2 | entry_updated's changed_fields/before/after cover the entry type's own fields (opt-in per type, values elided for large fields) so `entry.data.body` with op `changed` works. |
| `form-classification` | Form-submission classification from workflows | P0 | 2 | The workflow runner loads an entry-backed submission into `ctx.form_submission` so classify-form-submission classifies the real data; its output (`is_spam`, `category`) is usable by branches. |
| `idempotency` | Per-step idempotency keys | P0 | 2 | A webhook/integration step with `idempotency_key` (templated) that already succeeded for that key within the window is skipped and its recorded output reused; two concurrent duplicate events deliver once. |
| `joins` | Parallel branches and joins | P1 | 2 | Fan-out steps run independently and a join step waits for all (or any), with deterministic merge of outputs and partial-failure semantics. |
| `member-email` | Member-addressed email | P2 | 2 | member_added carries the member's email (or email subscriptions accept recipient_type `member`), and member events are triggerable with the subject distinguished from the actor. |
| `metrics` | Metrics windows and experiments | P2 | 2 | A step records a metric observation against a variant id and window; a report lists observations without causal claims. |
| `sandbox` | Schema validation / sandbox handler | P2 | 2 | A step validates a fetched JSON document against a JSON schema and reports violations as output. |
| `comments` | Comment events | P2 | 1 | comment_added/updated/deleted have an emitter that carries entry_id and the comment text, are triggerable, and hydrate `entry.*`. |
| `custom-events` | Custom emit_event names | P2 | 1 | A workspace can register `custom.<name>` events (catalog entry with payload fields); emit_event sends them with a templated payload; they are triggerable and subscribable; depth bounding applies. |
| `manual-params` | Manual / MCP run parameters | P1 | 1 | A manual or mcp trigger declares typed inputs; the Run dialog and the MCP tool collect them; steps read `${input.*}`; the run records them. |
| `snapshots` | Entity snapshots and restore | P2 | 1 | A step captures an entry version; a later step (or person) restores it; external publications are listed as not restorable. |
