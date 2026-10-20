# Workflow Library catalogue

Rendered from `src/marvin/services/automation/recipes/catalogue.json` by `scripts/render_workflow_library.py` — do not edit by hand.

117 recipes: **105** verified-current, **8** supported-after-configuration, **3** needs-adapter, **1** needs-engine-capability.

Statuses are defined in [README.md](README.md). A recipe link opens its workflow JSON (with `{{setup}}` placeholders); `<id>.vars.json` beside it declares each placeholder's type.

## Runnable today

| Recipe | Status | Trigger | Needs | Side effects |
|---|---|---|---|---|
| [newsletter-delivery](../../src/marvin/services/automation/recipes/newsletter-delivery.json) — Newsletter delivery | verified-current | `entry_published` | buttondown integration | content mutation, email ⚠, external post |
| [publication-announcement](../../src/marvin/services/automation/recipes/publication-announcement.json) — Publication announcement | verified-current | `entry_published` | outgoing webhook | content mutation, external post |
| [editorial-approval-gate](../../src/marvin/services/automation/recipes/editorial-approval-gate.json) — Editorial approval gate | verified-current | `entry_updated` | entry type with required fields (its completeness rules are the validation) | content mutation |
| [seo-assistant](../../src/marvin/services/automation/recipes/seo-assistant.json) — SEO assistant | verified-current | `entry_updated` | AI enabled for the workspace with the `automation` invocation source allowed; a default model | content mutation, paid call ⚠ |
| [translation-desk](../../src/marvin/services/automation/recipes/translation-desk.json) — Translation desk | verified-current | `entry_published` | — | content mutation, paid call |
| [series-index-keeper](../../src/marvin/services/automation/recipes/series-index-keeper.json) — Series index keeper | verified-current | `entry_published` | — | content mutation |
| [weekly-digest](../../src/marvin/services/automation/recipes/weekly-digest.json) — Weekly digest | verified-current | `schedule` | — | content mutation, paid call |
| [broken-link-patrol](../../src/marvin/services/automation/recipes/broken-link-patrol.json) — Broken link patrol | verified-current | `schedule` | an integration that can notify (Slack or Apprise) | content mutation, external post, external read |
| [living-resource-collection](../../src/marvin/services/automation/recipes/living-resource-collection.json) — Living resource collection | verified-current | `resource_updated` | — | content mutation, paid call |
| [publication-release-gate](../../src/marvin/services/automation/recipes/publication-release-gate.json) — Publication release gate | verified-current | `entry_updated` | — | content mutation |
| [content-refresh](../../src/marvin/services/automation/recipes/content-refresh.json) — Content refresh | verified-current | `entry_updated` | outgoing webhook | external post |
| [featured-collection-curator](../../src/marvin/services/automation/recipes/featured-collection-curator.json) — Featured collection curator | verified-current | `entry_published` | — | content mutation, paid call |
| [comment-discussion-starter](../../src/marvin/services/automation/recipes/comment-discussion-starter.json) — Comment discussion starter | verified-current | `entry_published` | outgoing webhook | content mutation, external post |
| [editorial-task-maker](../../src/marvin/services/automation/recipes/editorial-task-maker.json) — Editorial task maker | verified-current | `entry_published` | n8n integration | content mutation, external post |
| [evergreen-resurfacer](../../src/marvin/services/automation/recipes/evergreen-resurfacer.json) — Evergreen resurfacer | verified-current | `schedule` | — | content mutation, paid call |
| [one-entry-many-voices](../../src/marvin/services/automation/recipes/one-entry-many-voices.json) — One entry, many voices | verified-current | `entry_published` | — | content mutation, paid call |
| [carousel-storyteller](../../src/marvin/services/automation/recipes/carousel-storyteller.json) — Carousel storyteller | verified-current | `entry_published` | — | content mutation, paid call |
| [thread-builder](../../src/marvin/services/automation/recipes/thread-builder.json) — Thread builder | verified-current | `entry_published` | — | content mutation, paid call |
| [quote-card-studio](../../src/marvin/services/automation/recipes/quote-card-studio.json) — Quote card studio | verified-current | `entry_published` | — | content mutation, paid call |
| [teaser-ladder](../../src/marvin/services/automation/recipes/teaser-ladder.json) — Teaser ladder | verified-current | `entry_published` | — | content mutation, paid call |
| [behind-the-scenes-diary](../../src/marvin/services/automation/recipes/behind-the-scenes-diary.json) — Behind the scenes diary | verified-current | `entry_published` | — | content mutation, paid call |
| [community-question](../../src/marvin/services/automation/recipes/community-question.json) — Community question | verified-current | `entry_published` | — | content mutation, external post, paid call |
| [social-experiment-log](../../src/marvin/services/automation/recipes/social-experiment-log.json) — Social experiment log | verified-current | `manual` | — | content mutation, paid call |
| [platform-preview-checker](../../src/marvin/services/automation/recipes/platform-preview-checker.json) — Platform preview checker | verified-current | `entry_updated` | — | content mutation, external call |
| [launch-kit](../../src/marvin/services/automation/recipes/launch-kit.json) — Launch kit | verified-current | `entry_published` | — | content mutation, paid call |
| [milestone-celebration](../../src/marvin/services/automation/recipes/milestone-celebration.json) — Milestone celebration | verified-current | `entry_updated` | openai_images integration | content mutation, paid call |
| [event-countdown](../../src/marvin/services/automation/recipes/event-countdown.json) — Event countdown | verified-current | `entry_published` | — | content mutation, paid call |
| [best-of-month](../../src/marvin/services/automation/recipes/best-of-month.json) — Best of month | verified-current | `schedule` | — | content mutation |
| [utm-librarian](../../src/marvin/services/automation/recipes/utm-librarian.json) — UTM librarian | verified-current | `entry_created` | an entry type with a page URL pattern (so `entry.url` resolves) and two fields for UTM source and medium | content mutation |
| [community-welcome-pack](../../src/marvin/services/automation/recipes/community-welcome-pack.json) — Community welcome pack | verified-current | `member_added` | — | content mutation, paid call |
| [one-tap-share-links](../../src/marvin/services/automation/recipes/one-tap-share-links.json) — One-tap share links | verified-current | `entry_published` | — | content mutation, paid call |
| [on-this-day](../../src/marvin/services/automation/recipes/on-this-day.json) — On this day | verified-current | `schedule` | — | content mutation, paid call |
| [audience-milestone](../../src/marvin/services/automation/recipes/audience-milestone.json) — Audience milestone | verified-current | `entry_published` | — | content mutation, paid call |
| [collaborator-shout-out](../../src/marvin/services/automation/recipes/collaborator-shout-out.json) — Collaborator shout-out | verified-current | `entry_published` | — | approval, content mutation, paid call |
| [thank-you-notes](../../src/marvin/services/automation/recipes/thank-you-notes.json) — Thank-you notes | verified-current | `entry_published` | — | content mutation, paid call |
| [post-event-recap](../../src/marvin/services/automation/recipes/post-event-recap.json) — Post-event recap | verified-current | `entry_published` | — | content mutation, paid call |
| [alt-text-assistant](../../src/marvin/services/automation/recipes/alt-text-assistant.json) — Alt text assistant | verified-current | `asset_uploaded` | — | content mutation, paid call |
| [responsive-image-factory](../../src/marvin/services/automation/recipes/responsive-image-factory.json) — Responsive image factory | verified-current | `asset_attached_to_entry` | — | content mutation |
| [background-remover](../../src/marvin/services/automation/recipes/background-remover.json) — Background remover | verified-current | `manual` | openai_images integration | content mutation, paid call |
| [product-scene-studio](../../src/marvin/services/automation/recipes/product-scene-studio.json) — Product scene studio | verified-current | `manual` | openai_images integration | content mutation, paid call |
| [smart-crop-pack](../../src/marvin/services/automation/recipes/smart-crop-pack.json) — Smart crop pack | verified-current | `asset_uploaded` | — | content mutation, paid call |
| [brand-recolor](../../src/marvin/services/automation/recipes/brand-recolor.json) — Brand recolor | verified-current | `manual` | — | content mutation |
| [seasonal-variation](../../src/marvin/services/automation/recipes/seasonal-variation.json) — Seasonal variation | verified-current | `manual` | openai_images integration | content mutation, paid call |
| [thumbnail-audition](../../src/marvin/services/automation/recipes/thumbnail-audition.json) — Thumbnail audition | verified-current | `manual` | openai_images integration | approval, content mutation, paid call |
| [image-quality-gate](../../src/marvin/services/automation/recipes/image-quality-gate.json) — Image quality gate | verified-current | `asset_uploaded` | an integration that can notify (Slack or Apprise) | external post |
| [privacy-crop-desk](../../src/marvin/services/automation/recipes/privacy-crop-desk.json) — Privacy crop desk | verified-current | `asset_uploaded` | — | content mutation, paid call |
| [before-after-slider-kit](../../src/marvin/services/automation/recipes/before-after-slider-kit.json) — Before and after kit | verified-current | `manual` | — | content mutation |
| [contact-sheet-maker](../../src/marvin/services/automation/recipes/contact-sheet-maker.json) — Contact sheet maker | verified-current | `manual` | — | content mutation |
| [ocr-notebook](../../src/marvin/services/automation/recipes/ocr-notebook.json) — OCR notebook | verified-current | `asset_uploaded` | — | content mutation, paid call |
| [document-preview-factory](../../src/marvin/services/automation/recipes/document-preview-factory.json) — Document preview factory | verified-current | `asset_uploaded` | — | content mutation |
| [file-format-converter](../../src/marvin/services/automation/recipes/file-format-converter.json) — File format converter (images) | verified-current | `asset_uploaded` | — | content mutation |
| [attribution-companion](../../src/marvin/services/automation/recipes/attribution-companion.json) — Attribution companion | verified-current | `asset_attached_to_entry` | — | content mutation |
| [duplicate-asset-scout](../../src/marvin/services/automation/recipes/duplicate-asset-scout.json) — Duplicate asset scout | verified-current | `asset_uploaded` | an integration that can notify (Slack or Apprise) | external post |
| [image-prompt-archive](../../src/marvin/services/automation/recipes/image-prompt-archive.json) — Image prompt archive | verified-current | `asset_attached_to_entry` | — | content mutation |
| [watermark-new-pictures](../../src/marvin/services/automation/recipes/watermark-new-pictures.json) — Watermark new pictures | verified-current | `asset_attached_to_entry` | — | content mutation |
| [watermark-a-set](../../src/marvin/services/automation/recipes/watermark-a-set.json) — Watermark a set of pictures | verified-current | `manual` | — | content mutation |
| [comic-strip-edition](../../src/marvin/services/automation/recipes/comic-strip-edition.json) — Comic strip edition | verified-current | `manual` | — | content mutation, paid call |
| [marvin-margin-notes](../../src/marvin/services/automation/recipes/marvin-margin-notes.json) — Marvin margin notes | verified-current | `manual` | — | content mutation, paid call |
| [ada-explains-it](../../src/marvin/services/automation/recipes/ada-explains-it.json) — Ada explains it | verified-current | `entry_published` | — | content mutation, paid call |
| [retro-poster-machine](../../src/marvin/services/automation/recipes/retro-poster-machine.json) — Retro poster machine | verified-current | `manual` | — | content mutation |
| [trading-card-collection](../../src/marvin/services/automation/recipes/trading-card-collection.json) — Trading card collection | verified-current | `entry_updated` | — | content mutation, paid call |
| [achievement-cabinet](../../src/marvin/services/automation/recipes/achievement-cabinet.json) — Achievement cabinet | verified-current | `custom.milestone` | custom event | content mutation |
| [meme-workshop](../../src/marvin/services/automation/recipes/meme-workshop.json) — Meme workshop | verified-current | `manual` | — | content mutation, paid call |
| [choose-your-own-adventure](../../src/marvin/services/automation/recipes/choose-your-own-adventure.json) — Choose your own adventure | verified-current | `manual` | — | content mutation, paid call |
| [future-newspaper](../../src/marvin/services/automation/recipes/future-newspaper.json) — Future newspaper | verified-current | `manual` | — | content mutation, paid call |
| [workshop-field-guide](../../src/marvin/services/automation/recipes/workshop-field-guide.json) — Workshop field guide | verified-current | `manual` | — | content mutation, paid call |
| [color-moodboard](../../src/marvin/services/automation/recipes/color-moodboard.json) — Color moodboard | verified-current | `manual` | — | content mutation, paid call |
| [soundtrack-brief](../../src/marvin/services/automation/recipes/soundtrack-brief.json) — Soundtrack brief | verified-current | `manual` | — | content mutation, paid call |
| [alternate-universe-cover](../../src/marvin/services/automation/recipes/alternate-universe-cover.json) — Alternate universe cover | verified-current | `entry_published` | openai_images integration | content mutation, paid call |
| [time-capsule](../../src/marvin/services/automation/recipes/time-capsule.json) — Time capsule | verified-current | `entry_published` | — | content mutation, paid call |
| [surprise-remix-button](../../src/marvin/services/automation/recipes/surprise-remix-button.json) — Surprise remix button | verified-current | `manual` | — | content mutation, paid call |
| [fictional-debate-club](../../src/marvin/services/automation/recipes/fictional-debate-club.json) — Fictional debate club | verified-current | `manual` | — | content mutation, paid call |
| [client-handoff](../../src/marvin/services/automation/recipes/client-handoff.json) — Client handoff | verified-current | `entry_updated` | outgoing webhook | content mutation, external post |
| [agent-directory-intake](../../src/marvin/services/automation/recipes/agent-directory-intake.json) — Agent directory intake | verified-current | `form_submission_received` | an integration that can notify (Slack or Apprise); entry type | content mutation, external post, external read |
| [resource-availability-watch](../../src/marvin/services/automation/recipes/resource-availability-watch.json) — Resource availability watch | verified-current | `schedule` | an integration that can notify (Slack or Apprise) | external post, external read |
| [project-milestone-report](../../src/marvin/services/automation/recipes/project-milestone-report.json) — Project milestone report | verified-current | `entry_updated` | — | content mutation, paid call |
| [knowledge-gap-finder](../../src/marvin/services/automation/recipes/knowledge-gap-finder.json) — Knowledge gap finder | verified-current | `manual` | — | content mutation, paid call |
| [meeting-notes-to-tasks](../../src/marvin/services/automation/recipes/meeting-notes-to-tasks.json) — Meeting notes to tasks | verified-current | `entry_created` | — | content mutation, paid call |
| [release-notes-compiler](../../src/marvin/services/automation/recipes/release-notes-compiler.json) — Release notes compiler | verified-current | `manual` | — | content mutation, paid call |
| [intake-triage](../../src/marvin/services/automation/recipes/intake-triage.json) — Intake triage | verified-current | `form_submission_received` | — | content mutation, paid call |
| [failure-repair-desk](../../src/marvin/services/automation/recipes/failure-repair-desk.json) — Failure repair desk | verified-current | `on_error` (`automation_failed`) | — | content mutation |
| [publication-ledger](../../src/marvin/services/automation/recipes/publication-ledger.json) — Publication ledger | verified-current | `entry_published` | — | content mutation |
| [archive-packager](../../src/marvin/services/automation/recipes/archive-packager.json) — Archive packager | verified-current | `manual` | — | content mutation |
| [personal-project-radar](../../src/marvin/services/automation/recipes/personal-project-radar.json) — Personal project radar | verified-current | `schedule` | — | content mutation, paid call |
| [blocked-publication-rescue](../../src/marvin/services/automation/recipes/blocked-publication-rescue.json) — Blocked publication rescue | verified-current | `entry_scheduled_publish_blocked` | an integration that can notify (Slack or Apprise) | content mutation, notification |
| [form-intake-desk](../../src/marvin/services/automation/recipes/form-intake-desk.json) — Form intake desk | verified-current | `form_submission_received` | an integration that can notify (Slack or Apprise); a submittable entry type (capabilities.submittable) — submissions are entries of that type | content mutation, notification |
| [form-submission-sorter](../../src/marvin/services/automation/recipes/form-submission-sorter.json) — Form submission sorter | verified-current | `form_submission_received` | a submittable entry type (capabilities.submittable) — submissions are entries of that type; AI on for workflows (Settings → AI) | content mutation, paid call |
| [submission-surge-alert](../../src/marvin/services/automation/recipes/submission-surge-alert.json) — Submission surge alert | verified-current | `submission_surge_detected` | an integration that can notify (Slack or Apprise); submission protection with a surge threshold on the entry type | notification |
| `host-rebuild-dispatch` — Host rebuild dispatch | supported-after-configuration | subscription: `webhook_triggered` | site_auto_rebuild preference on, or the request_site_rebuild handler / Rebuild button; outgoing webhook | external post ⚠ |
| [deployment-celebration](../../src/marvin/services/automation/recipes/deployment-celebration.json) — Deployment celebration | verified-current | `site_deployment_completed` | an integration that can notify (Slack or Apprise); a producer of site_deployment_completed: the Cloudflare Pages plugin's blueprint, or your own incoming webhook + emit_event workflow; incoming webhook; workflow | notification |
| [deployment-failure-desk](../../src/marvin/services/automation/recipes/deployment-failure-desk.json) — Deployment failure desk | verified-current | `site_deployment_failed` | an integration that can notify (Slack or Apprise); a producer of site_deployment_failed (see deployment-celebration); incoming webhook; workflow | notification |
| [integration-health-companion](../../src/marvin/services/automation/recipes/integration-health-companion.json) — Integration health companion | verified-current | `integration_attention_needed` | — | content mutation |
| `connection-recovery-log` — Connection recovery log | supported-after-configuration | subscription: `integration_attention_resolved` | — | external post |
| [webhook-repair-desk](../../src/marvin/services/automation/recipes/webhook-repair-desk.json) — Webhook repair desk | verified-current | `webhook_delivery_failed` | — | content mutation |
| `scheduled-task-watchdog` — Scheduled task watchdog | supported-after-configuration | subscription: `scheduled_task_failed` | notification settings | notification |
| `ai-spending-heads-up` — AI spending heads-up | supported-after-configuration | subscription: `ai_budget_threshold_reached` | an AI monthly budget set (Settings → AI → Limits); SMTP; email event subscription | email |
| `ai-budget-pause-desk` — AI budget pause desk | supported-after-configuration | subscription: `ai_budget_exceeded` | an AI monthly budget; SMTP; email event subscription | email |
| `ai-quota-recovery-desk` — AI quota recovery desk | supported-after-configuration | subscription: `ai_provider_quota_exceeded` | SMTP; email event subscription | email |
| `agent-approval-inbox` — Agent approval inbox | supported-after-configuration | subscription: `approval_requested` | VAPID web push configured; approvers have the app installed with notifications on; native | notification |
| [collection-welcome-mat](../../src/marvin/services/automation/recipes/collection-welcome-mat.json) — Collection welcome mat | verified-current | `entry_added_to_collection` | AI enabled with the `automation` source allowed | content mutation, paid call ⚠ |
| [resource-attachment-notes](../../src/marvin/services/automation/recipes/resource-attachment-notes.json) — Resource attachment notes | verified-current | `entry_resource_attached` | — | content mutation, paid call |
| [entry-schema-impact-report](../../src/marvin/services/automation/recipes/entry-schema-impact-report.json) — Entry schema impact report | verified-current | `entry_type_updated` | an integration that can notify (Slack or Apprise) | external post |
| [asset-attachment-social-kit](../../src/marvin/services/automation/recipes/asset-attachment-social-kit.json) — Asset attachment social kit | verified-current | `asset_attached_to_entry` | — | content mutation, paid call |
| [new-member-welcome](../../src/marvin/services/automation/recipes/new-member-welcome.json) — New member welcome | verified-current | `member_added` | SMTP | email |
| `api-token-rotation-notice` — API token rotation notice | supported-after-configuration | subscription: `api_client_token_rotated` | SMTP; email event subscription | email |
| [unpublish-entries-with-images](../../src/marvin/services/automation/recipes/unpublish-entries-with-images.json) — Move every entry with an image back to draft | verified-current | `manual` | — | content mutation |
| [summarise-and-feature-on-publish](../../src/marvin/services/automation/recipes/summarise-and-feature-on-publish.json) — Summarise a published entry and add it to a collection | verified-current | `entry_published` | AI enabled with the `automation` source allowed | content mutation, paid call ⚠ |
| [hourly-site-rebuild](../../src/marvin/services/automation/recipes/hourly-site-rebuild.json) — Every hour, rebuild the site | verified-current | `schedule` | a deploy target (an event-driven outgoing webhook or integration subscription on webhook_triggered) for the rebuild to reach anything | external post ⚠ |
| [archive-entry-from-webhook](../../src/marvin/services/automation/recipes/archive-entry-from-webhook.json) — A webhook call finds an entry by slug and archives it | verified-current | `incoming_webhook` | incoming webhook | content mutation |
| [trash-unattached-images](../../src/marvin/services/automation/recipes/trash-unattached-images.json) — Trash every unattached image | verified-current | `manual` | — | content mutation |
| [restore-trashed-resources](../../src/marvin/services/automation/recipes/restore-trashed-resources.json) — Restore all resources in the Trash | verified-current | `manual` | — | content mutation |
| [asset-upload-announcement](../../src/marvin/services/automation/recipes/asset-upload-announcement.json) — Post new uploads to a chat channel | verified-current | `asset_uploaded` | outgoing webhook | external post |
| [share-published-entry](../../src/marvin/services/automation/recipes/share-published-entry.json) — Share a published entry everywhere | verified-current | `entry_published` | an integration that can social.post (Instagram, a Facebook Page, Bluesky or Mastodon); AI on for workflows (Settings → AI) | external post, paid call |

## Waiting on a capability or an adapter

| Recipe | Status | Trigger | Blocked by |
|---|---|---|---|
| `audio-edition` — Audio edition | needs-adapter | `entry_published` | media-adapters |
| `poll-companion` — Poll companion | needs-adapter | `entry_published` | social-adapters |
| `reply-drafting-desk` — Reply drafting desk | needs-engine-capability | `comment_added` | comments |
| `campaign-scoreboard` — Campaign scoreboard | needs-adapter | `schedule` | social-adapters |

## By category

### Publishing and editorial

- [newsletter-delivery](../../src/marvin/services/automation/recipes/newsletter-delivery.json) — **Newsletter delivery** · verified-current · `entry_published`  
  A published newsletter entry becomes a Buttondown issue; the issue id and delivery result are recorded on the entry.
  - Identical in shape to the Buttondown plugin's own `buttondown-issue-on-publish` blueprint; installing the plugin's content offers it with one click.
  - Replay-safe at the provider: the recorded `buttondown_email_id` is sent back as `email_id`, so a re-publish updates the issue instead of creating a second one.
  - `${site.url}` is the workspace's Canonical URL (None when unset): the provider uses it to absolutise relative links.
- [publication-announcement](../../src/marvin/services/automation/recipes/publication-announcement.json) — **Publication announcement** · verified-current · `entry_published`  
  A published entry is announced to a community channel through an outgoing webhook; the response code is recorded on the entry.
  - The brief's completion event (`newsletter_issue_processed`) is not a built-in event. Register your own (Settings → Automation → Custom events) and send it with an Emit event step, or use the run's own `automation_ran` event, with the run id, as the completion signal — a `chained` workflow can react to it.
  - `announcement.run` is the event's correlation id, shared with the run history row.
- [editorial-approval-gate](../../src/marvin/services/automation/recipes/editorial-approval-gate.json) — **Editorial approval gate** · verified-current · `entry_updated`  
  When an entry's status changes to approved it is published; if the publish gate refuses (missing required fields, expiry passed) the entry goes back to Needs review with the exact reasons.
  - Validation is Marvin's own publish gate (services/entries/completeness.py), not a workflow-level check: required fields, required asset roles, resource types, tags and the expiry date.
  - `approved` is a real entry status; the condition uses `changed_to`, so only the transition fires it, not every save of an approved entry.
- [seo-assistant](../../src/marvin/services/automation/recipes/seo-assistant.json) — **SEO assistant** · verified-current · `entry_updated`  
  When an entry is sent to review, AI proposes a search-result description (summary) and tags; the proposals are staged as suggestions for a person to accept.
  - Title generation is not available: no operation writes `title`; summary (meta description) and tags are what the registry offers with a write-back map.
  - Body changes can now be detected (`changed_fields` contains `data.<field>`, 2026-10-18); this recipe still keys on the review transition.
  - Write-back follows the workspace approval mode (services/ai/approval.py): mid-review entries are always staged.
  - Blocked by: `custom-operation` (to generate a title)
- [translation-desk](../../src/marvin/services/automation/recipes/translation-desk.json) — **Translation desk** · verified-current · `entry_published`  
  A published entry gets a translation drafted as a new entry; an editor reviews it and, once approved, it is published.
  - An approval step parks the run; Automation → Approvals and a push ask the editors; the steps after it read ${steps.ok.output.decision}.
- `audio-edition` — **Audio edition** · needs-adapter · `entry_published`  
  Publication → narrate article → attach audio → update podcast feed
  - Blocked by: `media-adapters` (a TTS provider action that returns an audio asset)
- [series-index-keeper](../../src/marvin/services/automation/recipes/series-index-keeper.json) — **Series index keeper** · verified-current · `entry_published`  
  When a part of a series (a collection) is published, the series' index entry is rewritten as a list of its published parts, in the collection's order, with their links.
  - The first step checks membership: a one-row query for this entry in the collection.
  - Previous/next links are the site's: the publishing API serves the collection in the same order.
- [weekly-digest](../../src/marvin/services/automation/recipes/weekly-digest.json) — **Weekly digest** · verified-current · `schedule`  
  Every Monday morning, the week's published entries are gathered and an AI drafts a newsletter issue that introduces and links each one.
  - Gathers up to 20 entries published in the last 7 days (a relative date) and passes their text to the AI.
  - The issue is a draft for a person to edit and send.
- [broken-link-patrol](../../src/marvin/services/automation/recipes/broken-link-patrol.json) — **Broken link patrol** · verified-current · `schedule`  
  Every Monday, the links in each published entry are checked; an entry with broken links records how many, and a notification lists them.
  - Broken = no answer, 404, 410 or 5xx. 401/403/429 aren't counted: those are servers refusing robots.
  - Relative links (/articles/x) are checked against the workspace's site URL.
  - It doesn't take the entry offline: request_review would unpublish it.
  - It notifies every Monday while an entry still has broken links.
- [living-resource-collection](../../src/marvin/services/automation/recipes/living-resource-collection.json) — **Living resource collection** · verified-current · `resource_updated`  
  When a resource changes, the entries that use it are gathered and an AI drafts the passages that may now be out of date, with new wording.
  - Up to 20 entries using the resource (`resource: ${resource.id}`), with their text.
  - Every save of a resource is a change: one draft per save while entries use it.
- [publication-release-gate](../../src/marvin/services/automation/recipes/publication-release-gate.json) — **Publication release gate** · verified-current · `entry_updated`  
  When an entry is approved, its text, its pictures and its downloads are checked side by side; if all pass it is published, otherwise it goes back to Needs review with every check that failed named.
  - The three checks are the branches of one parallel step (join all, on_branch_failure continue): they run one after another in the order written, each independent of the others, so a missing picture never hides a short text. The step then reports how many failed and one line per failed branch.
  - Text: the chosen field must hold at least min_characters. Images: at least one picture (jpeg, png, webp, gif) attached to the entry, each with alt text. Downloads (PDF, zip): optional, but each one attached needs a description.
  - This is on top of Marvin's own publish gate (completeness rules: required fields, asset roles, resource types); a refusal there is caught by the on_failure step.
  - Only the move to Approved starts the gate (changed_to), so fixing a held entry and approving it again runs it again.
- [content-refresh](../../src/marvin/services/automation/recipes/content-refresh.json) — **Content refresh** · verified-current · `entry_updated`  
  Every save of a published entry tells an external copy or search index to re-fetch it, through an outgoing webhook.
  - It fires on every save of a published entry, including the publish itself and metadata writes made by other workflows; a `changed_fields contains data.<field>` condition (2026-10-18) would narrow it to one field.
  - If the external copy is the site itself, prefer the native rebuild: content changes already queue a coalesced rebuild (site_rebuild_queued → webhook_triggered).
  - Idempotency keys exist (2026-10-18) but dedupe identical calls; a burst of different saves is still one call each unless the key ignores what changed.
- [featured-collection-curator](../../src/marvin/services/automation/recipes/featured-collection-curator.json) — **Featured collection curator** · verified-current · `entry_published`  
  When the AI thinks a published entry fits a collection, an editor is asked; once approved it is added.
  - An approval step parks the run; Automation → Approvals and a push ask the editors; the steps after it read ${steps.ok.output.decision}.
- [comment-discussion-starter](../../src/marvin/services/automation/recipes/comment-discussion-starter.json) — **Comment discussion starter** · verified-current · `entry_published`  
  A published entry opens a discussion topic in a forum through an outgoing webhook; the topic URL from the response is recorded on the entry.
  - The response field holding the topic URL is a setup variable (`discussion_url_path`) spliced into the `${steps.discussion.output.body.<path>}` template.
- [editorial-task-maker](../../src/marvin/services/automation/recipes/editorial-task-maker.json) — **Editorial task maker** · verified-current · `entry_published`  
  A published entry creates follow-up tasks in your task tool through an n8n flow; the n8n execution id is recorded on the entry.
  - Marvin has no task entity; n8n is the adapter to whichever task tool you use. The two task titles are templates — edit them in the recipe.
- [evergreen-resurfacer](../../src/marvin/services/automation/recipes/evergreen-resurfacer.json) — **Evergreen resurfacer** · verified-current · `schedule`  
  Once a month, the three least recently touched entries published over a year ago get refresh ideas from the AI, saved as a draft entry.
  - Refreshing a piece (editing it) moves it to the back of the queue: the oldest updates come first.

### Social and community

- [one-entry-many-voices](../../src/marvin/services/automation/recipes/one-entry-many-voices.json) — **One entry, many voices** · verified-current · `entry_published`  
  A published entry gets a LinkedIn version, a short post and a community post written in its voice, saved together as a new draft to edit.
  - A custom AI step, then a create step: the new entry is a draft for a person to edit and publish.
- [carousel-storyteller](../../src/marvin/services/automation/recipes/carousel-storyteller.json) — **Carousel storyteller** · verified-current · `entry_published`  
  When an entry is published, the AI outlines it as five slides and each is rendered as a portrait card (1080×1350), attached to the entry as carousel-1 to carousel-5 for posting.
  - The first slide carries the entry's picture in the role you choose; the rest are plain cards.
  - Nothing is posted: download the five cards from the entry to post them as a carousel.
- [thread-builder](../../src/marvin/services/automation/recipes/thread-builder.json) — **Thread builder** · verified-current · `entry_published`  
  When an entry is published, it's turned into a thread of 3–8 short posts for the network you name, each within its length, saved as a draft to check and post.
  - Nothing is posted: the thread is a draft for a person to post. A social provider could later post it from metadata.thread.
- [quote-card-studio](../../src/marvin/services/automation/recipes/quote-card-studio.json) — **Quote card studio** · verified-current · `entry_published`  
  When an entry is published, the AI picks one sentence from its text; if that sentence really is in the text word for word, a quote card is rendered over the entry's picture and attached as quote-card.
  - The exact-quote check is a `when` on the render step: the entry's text must contain the AI's quote.
- [teaser-ladder](../../src/marvin/services/automation/recipes/teaser-ladder.json) — **Teaser ladder** · verified-current · `entry_published`  
  When a launch is announced, three posts are drafted on the way to its date: a teaser three days before, the launch post on the day and a follow-up a week after — skipping any moment already past.
  - The run waits (Wait step) and goes on at the time, in the workspace's time zone.
  - A changed date after publishing isn't followed: the waits were set when it was published. Other edits to the workflow apply when a wait goes on.
- [behind-the-scenes-diary](../../src/marvin/services/automation/recipes/behind-the-scenes-diary.json) — **Behind the scenes diary** · verified-current · `entry_published`  
  A published project update — its notes and process photos — becomes a draft behind-the-scenes workshop post.
  - A custom AI step, then a create step: the new entry is a draft for a person to edit and publish.
- [community-question](../../src/marvin/services/automation/recipes/community-question.json) — **Community question** · verified-current · `entry_published`  
  A published entry gets one specific discussion question written for it, posted to your community channel through an outgoing webhook and kept in its metadata.
  - A custom AI step (`op: "custom"`): its own prompt and output fields; the answer is checked against them.
- `poll-companion` — **Poll companion** · needs-adapter · `entry_published`  
  Article → propose poll options → create poll draft
  - Publishing to social networks exists (the social.post capability, 2026-10-19); what is missing is a provider action that creates a poll (social-adapters).
  - Blocked by: `social-adapters` (a poll-capable provider)
- `reply-drafting-desk` — **Reply drafting desk** · needs-engine-capability · `comment_added`  
  New comment → classify intent → suggest reply → wait for approval
  - Instagram comments: the Instagram plugin's `auto_reply` runs from a scheduled task with its own rules; its reply actions are requires_approval and cannot run from a workflow.
  - Blocked by: `comments` (no comment events are ever sent)
- `campaign-scoreboard` — **Campaign scoreboard** · needs-adapter · `schedule`  
  After campaign → collect supported metrics → compare against baseline
  - Recording and listing the numbers exists (the `metric` step, 2026-10-18), and so does posting (social.post, 2026-10-19); what is missing is a provider action that collects the numbers from a network (social-adapters).
  - Blocked by: `social-adapters` (metrics actions)
- [social-experiment-log](../../src/marvin/services/automation/recipes/social-experiment-log.json) — **Social experiment log** · verified-current · `manual`  
  Run it on a post: an AI writes two versions that differ in one element, each drafted as an entry marked with the experiment id and its variant; run it again with what you observed for each and the numbers are recorded for the window (a repeat of the same window replaces the number, never adds), and a plain list of what was observed — not a verdict — is kept on the post.
  - Observations, not conclusions: the report lists what was recorded per window and variant and compares nothing; whether one version did better, and why, is for a person to judge.
  - Run it on a post once to draft the two variants (leave the numbers blank). Run it again, any time, with the numbers observed so far for A and B: the window defaults to the week (day or month on request), counted in the workspace's time zone.
  - Recording the same window again replaces the number rather than adding to it, so enter what the network shows to date, not the increase since last time; running it twice with the same numbers changes nothing.
  - A post that already carries metadata.experiment_id is not drafted again; remove that key (and the two drafts) to start a new experiment on it.
  - The numbers also appear on Settings → Automation → Metrics, one table of windows by variant.
- [platform-preview-checker](../../src/marvin/services/automation/recipes/platform-preview-checker.json) — **Platform preview checker** · verified-current · `entry_updated`  
  Each time a social-post draft is edited, it's checked for the network you name — too long, dead links, a picture the wrong shape — and sent to Needs review with each problem as a reason; a clean draft is left alone.
  - Runs on drafts only, when their fields change (not on a status change).
  - Picture shape is read from the picture in the role you name; a draft without one skips that check.
- [launch-kit](../../src/marvin/services/automation/recipes/launch-kit.json) — **Launch kit** · verified-current · `entry_published`  
  When a product is published, one AI pass drafts its announcement, an FAQ and a newsletter issue, and a launch card is made from its picture — all from what the entry says.
  - The FAQ answers only from the entry and says when something isn't stated, rather than guessing.
- [milestone-celebration](../../src/marvin/services/automation/recipes/milestone-celebration.json) — **Milestone celebration** · verified-current · `entry_updated`  
  When a project's status field reaches its done value, the AI drafts a celebration post grounded in the entry; once an editor approves, OpenAI Images draws an illustration, attached as celebration, and the post is saved on the entry.
  - metadata.celebrated makes it once per project: a later save while still complete doesn't fire again.
- [event-countdown](../../src/marvin/services/automation/recipes/event-countdown.json) — **Event countdown** · verified-current · `entry_published`  
  When an event is published, a reminder post is drafted a week before its date and another the day before, at the time you choose — skipping any moment already past.
  - The run waits (Wait step) — it's kept, and goes on at the time, in the workspace's time zone (Settings → Site).
  - A changed date after publishing isn't followed: the waits were set when it was published. Other edits to the workflow apply when a wait goes on.
- [best-of-month](../../src/marvin/services/automation/recipes/best-of-month.json) — **Best of month** · verified-current · `schedule`  
  On the 1st of each month, up to nine entries published in the last 30 days with a picture are laid out as one titled grid image.
  - Each tile is the entry's main picture with its title. Post or attach the grid by hand, or add a step.
- [utm-librarian](../../src/marvin/services/automation/recipes/utm-librarian.json) — **UTM librarian** · verified-current · `entry_created`  
  A new campaign entry gets a tracking link built from its URL and UTM fields, recorded in metadata with the campaign mapping.
  - Pure string templating: `${entry.url}?utm_source=${entry.data.utm_source}&…` — values must already be URL-safe.
  - `entry.url` is absolute when the workspace Canonical URL is set, else the site path.
- [community-welcome-pack](../../src/marvin/services/automation/recipes/community-welcome-pack.json) — **Community welcome pack** · verified-current · `member_added`  
  When someone joins the workspace, a welcome note is drafted for them — hello by name, what the place is for, and the pieces in your start-here collection to read first, with their addresses.
  - Nothing is sent: the welcome is a draft addressed to them (their email in metadata.to) for you to send.
  - The new member's name, username and role go to the AI; their email doesn't.
- [one-tap-share-links](../../src/marvin/services/automation/recipes/one-tap-share-links.json) — **One-tap share links** · verified-current · `entry_published`  
  When an entry is published, a short post is written and the entry gets ready-made share links for Bluesky, Mastodon, Threads, LinkedIn and email — each opens that network's composer with the post and a tracked link, for a person to check and send.
  - Nothing is posted: each link opens the network's own composer, signed in as you, and you press send.
  - Each link carries utm_source=<network>, utm_medium=social and utm_campaign=<the entry's slug>, so your analytics can tell where visits came from.
  - LinkedIn's share link takes only the page address; the post text is for you to paste.
- [on-this-day](../../src/marvin/services/automation/recipes/on-this-day.json) — **On this day** · verified-current · `schedule`  
  Each morning, anything published a year ago today gets a throwback: an AI-drafted post looking back at it, with a picture card attached — nothing on days with nothing to remember.
  - “A year ago today” is the 24 hours that ended exactly 365 days before the 8am run, so a leap year can shift it by a day.
  - The card uses the newest piece's main picture; without one it's a plain card.
- [audience-milestone](../../src/marvin/services/automation/recipes/audience-milestone.json) — **Audience milestone** · verified-current · `entry_published`  
  When your sign-ups reach 10, 25, 50, 100, 250, 500, 1000 and on, a thank-you post is drafted with a card to share — counts only, never names, and once per milestone.
  - It counts the sign-up type's published entries: a sign-up confirmed by another workflow (e.g. Buttondown's) counts once it's published.
  - If two sign-ups are published at the same moment, the count can step over a milestone; the next one is still caught.
- [collaborator-shout-out](../../src/marvin/services/automation/recipes/collaborator-shout-out.json) — **Collaborator shout-out** · verified-current · `entry_published`  
  When a project is published, the people it lists who've agreed to be tagged are thanked in a drafted post, by their own handles — after an editor approves it — and each of them records the credit.
  - People are entries of their own (a person type with a handle and a yes/no “OK to tag” field); a project lists theirs by slug, comma-separated.
  - Only people whose “OK to tag” is ticked are mentioned — anyone else is left out of the post and isn't sent to the AI.
- [thank-you-notes](../../src/marvin/services/automation/recipes/thank-you-notes.json) — **Thank-you notes** · verified-current · `entry_published`  
  When a project is published, each person it lists gets their own short thank-you note drafted — what they did and what it meant — one draft per person, addressed to them.
  - The notes are drafts for you to send however you like — nothing is sent.
  - Collaborator shout-out is the public version (one post thanking everyone); this one is private and personal.
- [post-event-recap](../../src/marvin/services/automation/recipes/post-event-recap.json) — **Post-event recap** · verified-current · `entry_published`  
  The day after an event, a recap post is drafted from its RSVPs (counts, no names) and each guest who RSVP'd gets a personal thank-you message drafted on their RSVP, asking for photos.
  - The run waits (Wait step) until the day after the event's date, in the workspace's time zone.
  - RSVPs are entries of their own (one per guest, published once confirmed) naming their event by slug; messages are drafted on them, not sent — guests' details never reach the public recap.
- [share-published-entry](../../src/marvin/services/automation/recipes/share-published-entry.json) — **Share a published entry everywhere** · verified-current · `entry_published`  
  An AI-drafted post for each published entry; once approved, it goes to every connected social network.
  - Every social post needs a person's approval: the Approval step before the post step is required (a workflow without one is refused when saved).
  - The draft is kept under 280 characters so it fits Bluesky (300) and Mastodon (500). Add per_network to the post step to give one network its own text, e.g. {"instagram": {"text": "${entry.summary}"}}.
  - The entry's main picture is attached (${entry.image}); an entry without one posts text only, and Instagram refuses that.

### Images and files

- [alt-text-assistant](../../src/marvin/services/automation/recipes/alt-text-assistant.json) — **Alt text assistant** · verified-current · `asset_uploaded`  
  An uploaded image without alt text gets alt text written by the AI, describing what it shows; people can edit it on the asset.
  - `write_back: {"alt_text": "alt_text"}` writes onto the asset; in the review-everything approval mode it is staged as a suggestion instead.
  - Images that already have alt text are skipped (`asset.alt_text` must not exist).
- [responsive-image-factory](../../src/marvin/services/automation/recipes/responsive-image-factory.json) — **Responsive image factory** · verified-current · `asset_attached_to_entry`  
  When a picture is attached to an entry in its main role, three WebP sizes (1600, 800, 400 px wide) are made and attached beside it as <role>-1600, -800 and -400.
  - Never upscales: a picture narrower than a size keeps its own width.
  - Sizes from an earlier main picture stay attached; remove them by hand when the picture changes.
- [background-remover](../../src/marvin/services/automation/recipes/background-remover.json) — **Background remover** · verified-current · `manual`  
  Run it: each picture tagged with your tag is asked about, and once approved its background is removed — a transparent PNG kept as a version of the picture.
  - The edit keeps the subject unchanged (input fidelity high); a transparent background comes back as PNG.
- [product-scene-studio](../../src/marvin/services/automation/recipes/product-scene-studio.json) — **Product scene studio** · verified-current · `manual`  
  Run it: each tagged product picture is asked about, and once approved it's set in the scene you describe, the product itself kept exactly as it is.
  - Change the scene variable for another setting; each run makes one scene per picture.
- [smart-crop-pack](../../src/marvin/services/automation/recipes/smart-crop-pack.json) — **Smart crop pack** · verified-current · `asset_uploaded`  
  Every uploaded picture gets square (1:1), portrait (4:5) and landscape (16:9) crops centred on its subject, saved as new assets beside the original.
  - The crops are found in the Assets library; each says Made from the original.
- [brand-recolor](../../src/marvin/services/automation/recipes/brand-recolor.json) — **Brand recolor** · verified-current · `manual`  
  Run by hand: every image with the chosen tag gets a colour-graded copy in the workspace's preset, saved as a new asset.
  - Presets: rustic-warm, warm, cool, muted, or the workspace's own media presets (AI settings).
  - Preview it first with a dry run: it lists what would be made.
- [seasonal-variation](../../src/marvin/services/automation/recipes/seasonal-variation.json) — **Seasonal variation** · verified-current · `manual`  
  Run it: each tagged graphic is asked about, and once approved a seasonal version is made — same layout, text and logo — kept as a version of the original.
  - The original and its lineage are kept; the variant names what it was made from.
- [thumbnail-audition](../../src/marvin/services/automation/recipes/thumbnail-audition.json) — **Thumbnail audition** · verified-current · `manual`  
  Run it on an entry: the AI proposes three thumbnail concepts, an editor okays the drawing, three pictures are made and attached, and an editor picks one — recorded on the entry as its thumbnail.
  - The pick is recorded as the role of the chosen picture (thumbnail-option-N) — the site reads the entry's asset in that role.
  - The three options stay attached; detach the two not chosen on the entry page if you don't want them.
- [image-quality-gate](../../src/marvin/services/automation/recipes/image-quality-gate.json) — **Image quality gate** · verified-current · `asset_uploaded`  
  An uploaded picture that is too narrow or too blurry is reported to the team's notification channel, with its size and sharpness.
  - Sharpness is the variance of a Laplacian on a downscaled grey copy: blurry pictures score low. Check a few of yours with an Inspect step to pick the minimum.
  - Flagging the asset itself (metadata or a tag) waits for an asset metadata step.
- [privacy-crop-desk](../../src/marvin/services/automation/recipes/privacy-crop-desk.json) — **Privacy crop desk** · verified-current · `asset_uploaded`  
  When a picture is uploaded, the AI model looks for faces, number plates and personal details; an editor approves, and a blurred copy is saved beside it.
  - The original stays; publish the blurred copy instead (it's a version of the original in the library).
  - Pixelated in blocks, then softened: nothing readable survives.
- [before-after-slider-kit](../../src/marvin/services/automation/recipes/before-after-slider-kit.json) — **Before and after kit** · verified-current · `manual`  
  Run by hand: every version tagged for comparison gets a before/after image beside its original, saved as a new asset.
  - A comparison image, not a slider: an interactive slider is a site component.
- [contact-sheet-maker](../../src/marvin/services/automation/recipes/contact-sheet-maker.json) — **Contact sheet maker** · verified-current · `manual`  
  Up to 48 images with a tag are laid out, labelled, on one contact sheet image.
  - Versions (crops, sizes) are left out unless the query asks for them.
  - Change the tag to make a sheet of another set.
- [ocr-notebook](../../src/marvin/services/automation/recipes/ocr-notebook.json) — **OCR notebook** · verified-current · `asset_uploaded`  
  When a PDF is uploaded, its text is read page by page (scanned pages by the AI model) and an AI drafts study notes with page references.
  - PDFs only, so every uploaded photo doesn't cost an AI call; a media step reads a picture's text too (extract_text).
- [document-preview-factory](../../src/marvin/services/automation/recipes/document-preview-factory.json) — **Document preview factory** · verified-current · `asset_uploaded`  
  When a PDF is attached to an entry as its download, its first three pages become pictures attached as previews, and page one as the cover.
  - The cover is page one at 1600 px — its own picture, as an entry links each asset once.
- [file-format-converter](../../src/marvin/services/automation/recipes/file-format-converter.json) — **File format converter (images)** · verified-current · `asset_uploaded`  
  Every uploaded JPEG or PNG gets a WebP copy (smaller, same look) saved as a new asset beside it.
  - Images only in this slice: documents, audio and video formats need adapters that don't exist yet.
- [attribution-companion](../../src/marvin/services/automation/recipes/attribution-companion.json) — **Attribution companion** · verified-current · `asset_attached_to_entry`  
  When an image with credit and licence metadata is attached to an entry, its credit line is recorded on the entry.
  - Reads the asset through `${asset.metadata.<key>}`: asset events bind the asset as they bind the entry.
- [duplicate-asset-scout](../../src/marvin/services/automation/recipes/duplicate-asset-scout.json) — **Duplicate asset scout** · verified-current · `asset_uploaded`  
  When a file is uploaded that's already in the library (the same bytes), a notification names the existing copy.
  - Same file = same sha256 checksum; a resized or re-saved copy isn't the same file.
  - It only tells you: keep the copy, or move it to the Trash yourself.
- [image-prompt-archive](../../src/marvin/services/automation/recipes/image-prompt-archive.json) — **Image prompt archive** · verified-current · `asset_attached_to_entry`  
  When a generated picture is attached to an entry, the entry records the prompt, model and integration that made it (and the picture keeps them too).
  - Every image an integration step generates already carries generated_by, prompt, model and the run in its own metadata; this copies it onto the entry it illustrates.
- [watermark-new-pictures](../../src/marvin/services/automation/recipes/watermark-new-pictures.json) — **Watermark new pictures** · verified-current · `asset_attached_to_entry`  
  When a picture is attached to an entry in its main role, a watermarked copy (your text, in a corner or tiled) is made and attached beside it as <role>-watermarked.
  - Position: a corner, center, or tiled (repeated diagonally so it can't be cropped away); opacity and size can be set on the step.
  - The original stays attached too: point your site or posts at the <role>-watermarked picture.
- [watermark-a-set](../../src/marvin/services/automation/recipes/watermark-a-set.json) — **Watermark a set of pictures** · verified-current · `manual`  
  Run it: every picture with your tag gets a watermarked copy (your text, in a corner or tiled), kept as a version of the original.
  - Position: a corner, center, or tiled (repeated diagonally so it can't be cropped away); opacity and size can be set on the step.
  - Versions (other copies) are left out unless the target asks for them.

### Playful experiments

- [comic-strip-edition](../../src/marvin/services/automation/recipes/comic-strip-edition.json) — **Comic strip edition** · verified-current · `manual`  
  Run by hand: the AI retells each published entry as four captions; once an editor approves, a four-panel comic is rendered (the entry's picture in the first panel) and attached.
  - Panels 2–4 are halftone fills; drawn panels need image generation (OpenAI Images) per panel, a later step.
- [marvin-margin-notes](../../src/marvin/services/automation/recipes/marvin-margin-notes.json) — **Marvin margin notes** · verified-current · `manual`  
  Run it on your drafts of one type: each gets a short, dry, faintly pessimistic margin note in a voice you describe, kept in its metadata.
  - A custom AI step (`op: "custom"`): its own prompt and output fields; the answer is checked against them.
- [ada-explains-it](../../src/marvin/services/automation/recipes/ada-explains-it.json) — **Ada explains it** · verified-current · `entry_published`  
  A published technical article gets a warm, plain-language explanation drafted as a new entry, clearly marked as an AI adaptation.
  - A custom AI step, then a create step: the new entry is a draft for a person to edit and publish.
- [retro-poster-machine](../../src/marvin/services/automation/recipes/retro-poster-machine.json) — **Retro poster machine** · verified-current · `manual`  
  Run by hand: every published project with a picture and no poster yet gets a vintage-style poster with its exact title, attached as poster.
  - The title is the entry's own, never generated. metadata.poster marks it done; clear it to make another.
- [trading-card-collection](../../src/marvin/services/automation/recipes/trading-card-collection.json) — **Trading card collection** · verified-current · `entry_updated`  
  When a project's status field reaches its done value, the AI writes three or four stats from the entry's own facts and a line of flavour text, and a trading card is rendered and attached.
  - The prompt allows only facts the entry states; check a card before sharing it.
- [achievement-cabinet](../../src/marvin/services/automation/recipes/achievement-cabinet.json) — **Achievement cabinet** · verified-current · `custom.milestone`  
  When a project reaches a milestone (a workflow sends your `custom.milestone` event for it), a badge is drafted for it and added to your cabinet collection — once per project and badge.
  - Badges are drafts: publish the ones you want shown. The cabinet is a collection, so the site lists it in the collection's order.
  - Send the event from any workflow, e.g. one on entry_updated whose condition is `entry.data.stage` changed to `shipped`: an Emit event step with event custom.milestone and payload {"milestone": "Shipped", "badge": "First release"}. A workflow that sends an event is never woken by it, but another workflow is: that is how one workflow hands work to another.
- [meme-workshop](../../src/marvin/services/automation/recipes/meme-workshop.json) — **Meme workshop** · verified-current · `manual`  
  Run by hand: for each published entry with a picture, the AI proposes a kind two-line caption; once an editor approves it, the meme is rendered and attached.
  - One approval per entry — run it on a small set.
- [choose-your-own-adventure](../../src/marvin/services/automation/recipes/choose-your-own-adventure.json) — **Choose your own adventure** · verified-current · `manual`  
  Run it on a premise entry: an AI writes a branching adventure as a tree of passages, a schema check confirms every branch offers choices or ends, and only then is it drafted (as JSON in the entry's text field); a story with a branch that goes nowhere stops the run and names the branch.
  - Reachability: the story is a tree (each passage is an ending or offers 2–3 choices that lead on), so every passage is reachable from the start by construction and the schema check holds every branch to an ending. A story whose choices loop back to an earlier passage (a graph) can't be written this way, and checking one would need a graph step the engine doesn't have.
  - The draft holds the story as JSON text (passages nested under choices) in the entry type's text field, for a person or a front end to turn into pages.
  - Run inputs: the Run button asks for the premise entry; the agent's run_workflow passes it as `inputs`.
  - Each run drafts a new adventure.
- [future-newspaper](../../src/marvin/services/automation/recipes/future-newspaper.json) — **Future newspaper** · verified-current · `manual`  
  Run by hand: each published project gets an imagined front page from ten years on — headline, deck and story written from the entry, under a banner that says it isn't real news.
  - The newspaper template always prints a banner saying the page is imagined.
- [workshop-field-guide](../../src/marvin/services/automation/recipes/workshop-field-guide.json) — **Workshop field guide** · verified-current · `manual`  
  Run it on a project: its log entries and pictures are gathered, an AI writes a guide (tools, numbered steps, tips) and it's printed to a multi-page A4 PDF attached to the project.
  - The printable guide template: ## headings, - lists and 1. steps in the body; the project's pictures at the end.
  - Run inputs: the Run button asks for the project.
- [color-moodboard](../../src/marvin/services/automation/recipes/color-moodboard.json) — **Color moodboard** · verified-current · `manual`  
  Up to 12 tagged images become a collage, its main colours are read off, an AI writes short design notes, and all three are rendered as one moodboard.
  - The palette is read from the collage, so it weighs every picture.
- [soundtrack-brief](../../src/marvin/services/automation/recipes/soundtrack-brief.json) — **Soundtrack brief** · verified-current · `manual`  
  Run it on stories of one type: each gets a soundtrack suggestion — mood, tempo, instruments and a short composer's brief — kept in its metadata.
  - A custom AI step (`op: "custom"`): its own prompt and output fields; the answer is checked against them.
- [alternate-universe-cover](../../src/marvin/services/automation/recipes/alternate-universe-cover.json) — **Alternate universe cover** · verified-current · `entry_published`  
  When an entry is published, an editor is asked whether to make an alternate-universe cover; once approved, OpenAI Images draws it, the editor sees the picture and decides whether to use it, and only then is it attached to the entry as cover-variant.
  - Two approvals: the first spends the image, the second shows it (the approval step's `image`) and attaches it only on a yes — so an editor judges the actual picture, not the idea.
- [time-capsule](../../src/marvin/services/automation/recipes/time-capsule.json) — **Time capsule** · verified-current · `entry_published`  
  When a project is first published, what it says is sealed on the entry; months later (you choose, up to a year) a look back comparing then and now is drafted.
  - The look back reads the entry as it is when the capsule opens, beside the sealed text.
  - The sealed text is kept in the entry's metadata, so it can be read (or edited) on the entry page.
  - Editing the workflow while capsules wait is fine: each opens with the steps as they are then.
- [surprise-remix-button](../../src/marvin/services/automation/recipes/surprise-remix-button.json) — **Surprise remix button** · verified-current · `manual`  
  Run it, pick an entry and one of the remixes you set up (a haiku, a fairy tale…): an AI retells the entry in that form as a new draft.
  - Run inputs: the Run button asks for the entry and the remix; the agent's run_workflow passes them as `inputs`.
- [fictional-debate-club](../../src/marvin/services/automation/recipes/fictional-debate-club.json) — **Fictional debate club** · verified-current · `manual`  
  Run it on your published entries: each gets a short, clearly fictional dialogue between viewpoints you choose, as a new draft.
  - A custom AI step, then a create step: the new entry is a draft for a person to edit and publish.

### Operations and knowledge

- [client-handoff](../../src/marvin/services/automation/recipes/client-handoff.json) — **Client handoff** · verified-current · `entry_updated`  
  When an entry's status changes to the configured ready status it is posted to the client's intake endpoint; the endpoint's JSON response is stored on the entry as the receipt.
  - `ready_status` must be one of Marvin's statuses (needs_review, approved, published); `changed_to` fires once on the transition.
  - The whole `entry.data` object is sent — review what the type's fields contain before enabling.
  - Idempotency keys exist (2026-10-18): an `idempotency_key` on the webhook step such as `handoff-${entry.id}` would make the call once per window; this recipe doesn't set one.
- [agent-directory-intake](../../src/marvin/services/automation/recipes/agent-directory-intake.json) — **Agent directory intake** · verified-current · `form_submission_received`  
  A form submission naming an agent's capability document: the page is fetched, its JSON is checked against your schema, the problems (or a clean bill) are recorded on the submission, it goes to review and a notification says which.
  - Possible today (partial): form-intake-desk covers the intake half (record, review, notify) when no document needs checking.
  - The “sandbox checks” of the idea (running the agent) are not part of this: the check is the document's shape — required fields, types, patterns — never a call to the agent itself.
  - The schema is a setup variable (a JSON Schema object, Draft 2020-12). To keep it in one place for several workflows, put it in a resource's metadata under `schema` and use schema_resource in the step instead.
  - Formats (email, uri…) are not asserted; use a `pattern`. A page's JSON is read up to 20 000 characters; a larger document is reported as not read.
- [resource-availability-watch](../../src/marvin/services/automation/recipes/resource-availability-watch.json) — **Resource availability watch** · verified-current · `schedule`  
  Every morning, each resource of a type with a URL has its page checked; one that doesn't answer or says it's sold out sends a notification.
  - `find` looks for the phrase on the page ignoring case (Sold Out, SOLD OUT).
  - It notifies every morning while a resource stays unavailable — it reports a state, not a change.
- [project-milestone-report](../../src/marvin/services/automation/recipes/project-milestone-report.json) — **Project milestone report** · verified-current · `entry_updated`  
  When a project is marked finished, its log entries (the ones whose field names it) and its linked materials are gathered and an AI drafts a project report.
  - A log entry belongs to the project when its field holds the project's slug (`data: {project: ${entry.slug}}`).
  - Materials are the resources linked to the project, in its order (`entry: ${entry.id}`).
- [knowledge-gap-finder](../../src/marvin/services/automation/recipes/knowledge-gap-finder.json) — **Knowledge gap finder** · verified-current · `manual`  
  The published pieces of a collection are gathered and an AI proposes three to five topics it's missing, saved as a draft backlog.
  - Up to 100 pieces, in the collection's order; the AI sees each title, summary and link.
- [meeting-notes-to-tasks](../../src/marvin/services/automation/recipes/meeting-notes-to-tasks.json) — **Meeting notes to tasks** · verified-current · `entry_created`  
  New meeting notes have their commitments pulled out; once an editor approves, they become a draft task list.
  - An approval step parks the run; Automation → Approvals and a push ask the editors; the steps after it read ${steps.ok.output.decision}.
- [release-notes-compiler](../../src/marvin/services/automation/recipes/release-notes-compiler.json) — **Release notes compiler** · verified-current · `manual`  
  Entries changed since a date (relative, like -14d) are gathered and an AI groups them into release notes, saved as a draft entry.
  - Up to 50 entries, most recently changed first; the AI sees each title, summary and link.
- [intake-triage](../../src/marvin/services/automation/recipes/intake-triage.json) — **Intake triage** · verified-current · `form_submission_received`  
  A new form submission is triaged by AI — what it asks, which of your queues, how urgent, and the questions to ask back with a draft reply — then sent to Needs review with that as the reason.
  - The submission's text is sent to the workspace's AI provider — say so in the form's privacy note.
  - Nothing is sent to the requester: the reply is a draft in metadata.triage.reply_draft.
- [failure-repair-desk](../../src/marvin/services/automation/recipes/failure-repair-desk.json) — **Failure repair desk** · verified-current · `on_error` (`automation_failed`)  
  When any workflow run fails on an entry and the integration's error policy did not handle it, the entry is sent to Needs review with the workflow name and error as the reason.
  - The on_error trigger listens to `automation_failed`; the failed run names its entry as `event.trigger_entity_type/id`, which the entry step targets explicitly (`entity_id`).
  - A “repair task” in an external tool is one more step away: add an n8n `trigger_workflow` step (see editorial-task-maker).
  - The native `workflow_failed` alert (Automation → Notifications) already emails/pushes admins once per incident; this recipe adds the in-content flag.
- [publication-ledger](../../src/marvin/services/automation/recipes/publication-ledger.json) — **Publication ledger** · verified-current · `entry_published`  
  Every publication of the configured type records who published, the run's correlation id, the URL and slug in the entry's metadata; the run history holds the per-step record.
  - “Expose execution history” exists natively: GET /api/automations/{id}/executions (+ /{execution_id}) lists runs, steps, outputs and retry chains; `run` here is the correlation id shared with the event log.
  - There is no timestamp template; the run history and event log carry the time.
- [archive-packager](../../src/marvin/services/automation/recipes/archive-packager.json) — **Archive packager** · verified-current · `manual`  
  Run it with a collection: its published entries — each with its attached files and facts — are bundled in collection order into a ZIP with a manifest.
  - Each entry is a folder: its files and entry.json (its facts and text); manifest.json lists everything.
  - Run inputs: the Run button asks for the collection.
- [personal-project-radar](../../src/marvin/services/automation/recipes/personal-project-radar.json) — **Personal project radar** · verified-current · `schedule`  
  Every Monday, each project draft untouched for two weeks gets two or three small next actions from the AI, as a review request.
  - `updated_before: -14d` is a relative date, read when the run starts.

### Event-driven extensions

- [blocked-publication-rescue](../../src/marvin/services/automation/recipes/blocked-publication-rescue.json) — **Blocked publication rescue** · verified-current · `entry_scheduled_publish_blocked`  
  When a scheduled publish is held (unmet requirements, expiry, or approval-only publishing) the entry is sent to Needs review with the exact reason and an editor is notified with a link.
  - entry_scheduled_publish_blocked is sent once per distinct reason (and again after an edit), not every 5 minutes — so this does not spam.
  - Marvin already pushes this event to people with the app (services/push_notifications.py); this recipe adds the in-content flag and a channel notice.
  - `event.waiting_for` is `requirements` or `approval`; `event.reason` is the one-line explanation, `event.issues` the list.
- [form-intake-desk](../../src/marvin/services/automation/recipes/form-intake-desk.json) — **Form intake desk** · verified-current · `form_submission_received`  
  A public submission to the configured entry type is stamped with intake facts, sent to Needs review for triage, and the owner is notified with the message.
  - To classify submissions (spam, category, sentiment) as they arrive, use form-submission-sorter, which sorts with an AI step; this desk stays free of AI.
  - Marvin already creates the entry (status inbox, or needs_review when protection flagged it) and pushes form_submission_received to people with the app.
  - Legacy Forms (the Forms table) also send this event, but with no entry — the `entry.entry_type` condition keeps the recipe to submittable entry types.
- [form-submission-sorter](../../src/marvin/services/automation/recipes/form-submission-sorter.json) — **Form submission sorter** · verified-current · `form_submission_received`  
  A new submission is classified by AI — its category, whether it is spam, its sentiment, whether it needs a reply — recorded on the entry, and sent to Needs review when it looks like spam or needs action.
  - The submission's text is sent to the workspace's AI provider — say so in the form's privacy note.
  - The classification is the AI's opinion: spam is sent to Needs review, never trashed. A submission that is neither spam nor needs action stays in Inbox with metadata.classified for a view or a later workflow.
  - It reads ${form_submission.*} (the submission as the public form saved it); the classify-form-submission step finds it itself.
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
- [integration-health-companion](../../src/marvin/services/automation/recipes/integration-health-companion.json) — **Integration health companion** · verified-current · `integration_attention_needed`  
  When a connection needs attention, a repair task is drafted for it — once per connection and error code while the task is open; Marvin's own alerts (with reminders) still reach your channels.
  - Marvin's alerts are unchanged: the Notifications page still sends the alert, its reminders and the “working again” note; this recipe adds the task beside them, so nothing is duplicated.
  - The task is a draft: the person who fixes the connection archives it. `integration_attention_resolved` is triggerable too, for a second workflow that closes tasks.
- `connection-recovery-log` — **Connection recovery log** · supported-after-configuration · subscription: `integration_attention_resolved`  
  When a connection that needed attention works again, the recovery is delivered to every channel that got the alert (native) and, optionally, recorded by an external log sink.
  - The recovery notice itself is native (services/integrations/errors.py `resolved_channel_rows`): nothing to configure for the channels that delivered the alert.
- [webhook-repair-desk](../../src/marvin/services/automation/recipes/webhook-repair-desk.json) — **Webhook repair desk** · verified-current · `webhook_delivery_failed`  
  When an outgoing webhook fails after its retries, a repair task is drafted for it on this workspace's own entries — once per webhook while the task is open.
  - The webhook's own delivery log (Automation → Webhooks → Log, or GET /api/groups/webhooks/{id}/logs) is the repair context; the task names the webhook and the event it couldn't deliver.
  - The publisher never announces a failed delivery of `webhook_delivery_failed` itself, so a webhook subscribed to it can't make this fire again.
- `scheduled-task-watchdog` — **Scheduled task watchdog** · supported-after-configuration · subscription: `scheduled_task_failed`  
  A failing scheduled task alerts once per incident and announces its recovery; the task's history is the repair context.
  - The alert is native, one per incident. A workflow can start on `scheduled_task_failed` (the workspace's own tasks; a platform task belongs to no workspace) and reads `${event.task_name}`, `${event.error_message}` and `${event.consecutive_failures}`; it would run on every failed run, so gate it on `event.consecutive_failures`. A workflow run on a schedule that fails reports through `automation_failed` (the `workflow_failed` kind), not here.
- `ai-spending-heads-up` — **AI spending heads-up** · supported-after-configuration · subscription: `ai_budget_threshold_reached`  
  When the workspace crosses its AI budget warning percentage, admins get an email with the spend and limit.
  - A workflow can start on this event (`${event.current_value}`, `${event.limit_value}`, `${event.percent}`). “Propose cheaper options” is a concept (would need the model list and pricing as event fields).
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
- [resource-attachment-notes](../../src/marvin/services/automation/recipes/resource-attachment-notes.json) — **Resource attachment notes** · verified-current · `entry_resource_attached`  
  When a resource is linked to an entry, the AI writes a short note on what it brings to that entry (material, technique, supplier), kept in the entry's metadata.
  - A custom AI step (`op: "custom"`): its own prompt and output fields; the answer is checked against them.
- [entry-schema-impact-report](../../src/marvin/services/automation/recipes/entry-schema-impact-report.json) — **Entry schema impact report** · verified-current · `entry_type_updated`  
  When an entry type's fields change, its entries that no longer pass its rules are listed in a notification, each with the rule it breaks.
  - It checks the entries against the type as it is now (after the change), up to 1,000 of them; up to 50 are listed.
  - Those entries keep their content; saving one asks for the fix.
- [asset-attachment-social-kit](../../src/marvin/services/automation/recipes/asset-attachment-social-kit.json) — **Asset attachment social kit** · verified-current · `asset_attached_to_entry`  
  When an image is attached to an entry, the AI looks at it and drafts a social caption plus square and story crop suggestions, kept in the entry's metadata.
  - A custom AI step (`op: "custom"`): its own prompt and output fields; the answer is checked against them.
- [new-member-welcome](../../src/marvin/services/automation/recipes/new-member-welcome.json) — **New member welcome** · verified-current · `member_added`  
  When someone joins the workspace they get a welcome email addressed to them — hello by name, the role they joined as, your note on where to start, and a button for their role (the workspace for anyone who can write, the site for a reader). Sent once per person.
  - The member is addressed by their user id (${member.id}); the email goes to the address on their account, never to one typed into the workflow. A recipient who is no member of the workspace fails the step.
  - Two steps, one for each kind of member: anyone above a reader gets a button to the admin app (`${site.app_url}`, the configured FRONTEND_URL), a reader gets one to the public site (`${site.url}`). A button is left out when its address isn't set.
  - `once_per: welcome:${member.id}` makes the welcome once per person, ever — a member removed and added again isn't welcomed twice. Drop it for a welcome per join (the same event handled twice still sends once).
  - The email is the markdown body set in the workspace's email layout (its own, else Marvin's default); invited members already get Marvin's own invitation email, which this doesn't replace.
  - Community welcome pack drafts a welcome from the start-here collection with an AI; this one sends a fixed note.
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
  - Interval, cron (in its time zone) and once schedules all fire.
  - The schedule's own run has no event: `${event.*}` is empty and conditions are skipped (a `target` still applies).
- [archive-entry-from-webhook](../../src/marvin/services/automation/recipes/archive-entry-from-webhook.json) — **A webhook call finds an entry by slug and archives it** · verified-current · `incoming_webhook`  
  An external system POSTs `{"slug": …}` to an incoming webhook URL; the named entry is archived, or sent to review with the error when it can't be.
  - `webhook: any` matches every incoming webhook of the workspace; name one slug to scope it.
- [trash-unattached-images](../../src/marvin/services/automation/recipes/trash-unattached-images.json) — **Trash every unattached image** · verified-current · `manual`  
  A manual run moves every image that no entry uses into the Trash, where it can be restored until the Trash is emptied.
  - A bare `trash` step acts on the current item: its entity_type follows the target.
  - Dry-run it first: POST /api/automations/{id}/run?dry_run=true lists the assets it would touch.
  - Versions made from an image still in the library (crops, sizes, conversions) are not unattached: they go with their original.
- [restore-trashed-resources](../../src/marvin/services/automation/recipes/restore-trashed-resources.json) — **Restore all resources in the Trash** · verified-current · `manual`  
  A manual run takes every trashed resource back out of the Trash.
  - `trashed: true` is the only way a target reaches the Trash; every other query leaves trashed rows out.
- [asset-upload-announcement](../../src/marvin/services/automation/recipes/asset-upload-announcement.json) — **Post new uploads to a chat channel** · verified-current · `asset_uploaded`  
  Every upload is announced in a chat channel with its type, name, MIME type and public URL.
  - `${asset.url}` is the public URL when the storage provider serves one, otherwise empty.

## Capability gaps

| Id | Capability | Priority | Recipes blocked | Acceptance |
|---|---|---|---|---|
| `create-entry` | Create-entry action | P0 | 3 | Delivered 2026-10-11: an entry step `op: "create"` (entry_type slug, title, data, metadata, status inbox|draft) makes a schema-validated entry, returns entry_id/slug, sends entry_created at depth+1, previews in a dry run, and makes it once per event (key: correlation id + workflow + target + step, kept in metadata.automation_created). |
| `social-adapters` | Social publishing adapters | P1 | 2 | Publishing delivered 2026-10-19: the social.post capability (text, images, alt, link, dry_run → posted, post_id, url, network), always behind an Approval step, an integration step with no `integration` posts to every connected network, `per_network` overrides the arguments for one, and a library asset becomes its public URL; each network is its own plugin (Instagram, Facebook Page, Bluesky, Mastodon). Left: drafts and polls as a provider action (poll-companion) and metrics actions that collect numbers from a network (campaign-scoreboard) — no plugin offers either yet. |
| `collection-scope` | Collection-scoped steps | P1 | 1 | A step can read a collection's entries (`${collection.entries}`) and an operation can run over that set to produce one output (summary, roundup). Partly delivered 2026-10-12: a `collect` step reads a collection's entries in its own order (`collection` + sort `position`) for one step to use; with an AI or `repeat` step over its rows, that is the roundup (2026-10-12/13); left only: `${collection.entries}` bound directly on collection events (a `collect` step reads the same set today). |
| `comments` | Comment events | P2 | 1 | comment_added/updated/deleted have an emitter that carries entry_id and the comment text, are triggerable, and hydrate `entry.*`. |
| `custom-operation` | Free-form AI operation | P0 | 1 | Delivered 2026-10-11: an operation step `op: "custom"` carries its own prompt (${…} templates) and output_schema (a JSON Schema object); `see` adds the item, its attachments, images, the workspace persona; the answer is checked (one retry) and is the step output; write_back maps it onto the entry (summary, tags, metadata.<key>), asset or resource; budget, approval mode and min_role apply as for built-in operations. Named, reusable workspace operations are a later phase. |
| `media-adapters` | Image, file and audio processing adapters | P1 | 1 | Slice 3 delivered 2026-10-12: media ops extract_text (a PDF's text layer; scanned pages and pictures by the vision model, image.read_text), pages (PDF pages as pictures, pypdfium2), find_sensitive and redact (faces, plates, personal text by the vision model, pixelated in a new copy). Slice 2 delivered 2026-10-12: a media step's render op fills an HTML/CSS template (built-in: card, quote, poster, trading-card, meme, side-by-side, comic-4, newspaper — or the step's own html) with text and pictures and screenshots it with headless Chromium into a new asset with lineage; the page runs no script and reaches no network. Slice 1 delivered 2026-10-12: a `media` step (resize, crop with subject focus, convert, grade, inspect, palette) saves NEW assets with lineage (derived_from, derivation, workflow, step, correlation id), never modifies originals, reuses an identical derivation, and attach_as links them to the run's entry; an integration action with an image.* capability keeps its images as assets (generated_by, prompt, model) so runs carry references. Also 2026-10-12: zip (files + manifest.json) and printed renders (format pdf; the guide template). Provider edits 2026-10-12: an integration step's `source` hands an image.edit action the picture (image_b64) and keeps the result as a version of it; OpenAI Images v0.3.0 has `edit`. Left: TTS. |
| `asset-resource-targets` | Assets and resources as workflow subjects | P1 | 0 | Delivered (2026-10-08/11): asset_*/resource_* events bind `asset.*` / `resource.*`; targets take entity asset|resource; an operation step on an asset sees its image and writes back through a `write_back` field map. Delivered 2026-10-12: the entries linked to a given asset or resource (`asset` / `resource` query keys). Delivered 2026-10-12: `checksum` (and `exclude`) in an asset query; `asset.checksum` in a run. Derived-asset lineage is part of media-adapters. |
| `branches` | Conditional steps (if/else) | P0 | 0 | Delivered 2026-10-11: any step takes `when` conditions evaluated against steps.* / previous.* (same operators); false records it as skipped (not failed), later references read None, and the dry run shows the verdicts. |
| `custom-events` | Custom emit_event names | P2 | 0 | Delivered 2026-10-18: a workspace registers `custom.<name>` events (Settings → Automation → Custom events, PUT /api/groups/custom-events/{name}) with typed payload fields (string, number, boolean, date); an Emit event step sends one with a templated `payload` held to those fields; a workflow can start on it, webhook/email/integration subscriptions can name it, the editor, Events pages, describe_event and the authoring guide list it; each hop carries reaction_depth + 1, so a chain stops at MAX_REACTION_DEPTH. |
| `data-change-detection` | Data-field change detection | P1 | 0 | Delivered 2026-10-18: entry_updated (and the publish, unpublish, archive, trash and restore events) name every changed field of the entry's type as `data.<key>` in `changed_fields`, with `before.data.<key>` / `after.data.<key>`; `changed`, `changed_from`, `changed_to` and `${event.before.data.price}` read them. Bounded, not opt-in: a short scalar (≤ 160 characters) is carried by value, a long text (a body), list, object or secret-like field name reads `‹elided›` — still named, so “the body changed” works; 100 names and 25 values per event. |
| `fetch` | HTTP fetch step | P1 | 0 | Delivered 2026-10-12: a `fetch` step ("Check a web address") — `url`: GET/HEAD through the guarded client (public hosts, re-checked on redirects, 2 MB cap) → status, ok, content_type, title, text, json, and `find` phrases (any case) → found; `links`: the links in a text checked a few at a time → checked, broken, broken_count, text. A dead link is output, never a failed step; a dry run doesn't fetch. |
| `form-classification` | Form-submission classification from workflows | P0 | 0 | Delivered 2026-10-18: a run on a form submission — a form_submission_received event, or any event on an entry of a submittable type — binds `${form_submission.*}` (id, form, form_slug, data.<field>, status, submitted_at, flagged, review_reasons: the entry the public form saved, or a legacy Forms row), and an operation step with op classify-form-submission reads it by itself (entity_type and entity_id default to the run's submission). Its answer — category, confidence, is_spam, sentiment, tags, action_required — is `${steps.<id>.output.<key>}` for a `when` or a template; a dry run previews with a stand-in answer and asks no AI. describe_event and the authoring guide list the fields. |
| `idempotency` | Per-step idempotency keys | P0 | 0 | Delivered 2026-10-18: a webhook or integration step with a templated `idempotency_key` that already made that call (same workflow, same destination, same key) within `idempotency_window_hours` (default 24, 1–720) is skipped and its recorded output reused, marked `idempotency: {duplicate: true}`; two concurrent duplicates deliver once (the first claims the key before it calls); a failed call gives the key back so retries still make it; a dry run says `would: call` or `would: skip (duplicate)`. Kept in `workflow_step_idempotency` as a hash; the Prune Workflow Runs task drops ended windows. It dedupes identical calls: it does not coalesce different keys. |
| `iterate-aggregate` | Iterate / aggregate over a target set | P1 | 0 | Delivered 2026-10-12: a `collect` step ("Gather items") runs an entry/asset/resource query (a target's keys) and returns rows (each as ${entry.*}/${asset.*}/${resource.*}), count, total and text (a plain list for an AI prompt), up to the target cap; a render step's list images take the rows whole (grid, moodboard). Linked items (2026-10-12): `entries` (the entry a field names), `asset` / `resource` (the entries using one), an asset/resource query's `entry` (what an entry holds, in its order) and `role`, and sort by `position` (a collection's own order). Delivered 2026-10-13 (0e7c993b): a `repeat` step runs 1–5 inner steps (an AI step included) once per item of a list or a collect step's rows, keyed per item so a re-delivered event repeats nothing; at most 25 items, no wait/approval/repeat inside. Nothing left. |
| `joins` | Parallel branches and joins | P1 | 0 | Delivered 2026-10-18: a `parallel` step ("Parallel branches") runs 2–5 named branches of 1–5 steps (no wait, approval, repeat or parallel inside) one after another in the order written, each reading what ran before it but not its siblings; `join` all (default) or any (the first branch to succeed wins, the rest are skipped); `on_branch_failure` fail (the step fails when the join isn't met; under all the first failing branch stops the rest) or continue (the step reports `satisfied`, `failed`, `text` and each branch's status for a `when`). The merge is by name in written order (`branches.<name>` {status ok|failed|skipped, error, steps, output}, `order`), so it never depends on which branch finished first; branches' steps are keyed per branch so a create inside runs once per event and count against the workspace's steps-per-workflow limit; a dry run previews every branch. Branches run in-process, not concurrently. |
| `manual-params` | Manual / MCP run parameters | P1 | 0 | Delivered 2026-10-12: a manual trigger's `inputs` (name, label, type text | number | choice | entry, options, required, default) — asked by the Run button's form, passed in the run API's body or run_workflow's `inputs`, checked against the declarations, read as ${input.<name>}; an entry input is the entry the run acts on. |
| `member-email` | Member-addressed email | P2 | 0 | Delivered 2026-10-18: an `email` step ("Email a member") — `to` a member's user id or email (${member.id}, ${member.email}, an entry field), `subject` and `body` (templates; markdown, set in the workspace's email layout and sent through its SMTP profile), optional `heading`, `button_text` + `button_link`, `once_per`. The recipient must be a member of the workspace — an outside address, a member of another workspace only, or a word fails the step, nothing is mailed. Sent once: the same event handled twice, a retry or a re-run sends nothing more (a ledger, `workflow_email_sends`; a failed send gives its claim back); `once_per: welcome:${member.id}` sends that person the step's email once, ever. The step needs an admin author, and fails with no SMTP; a dry run renders the email (would_send) and sends nothing. Role-appropriate links: a `when` on ${member.role}, `${site.url}` (the site) and `${site.app_url}` (the admin app). Left: writing to an address that isn't a member's (a fixed outside recipient stays an email subscription's `specific` recipient), and member_added still carries no email for subscriptions. |
| `metrics` | Metrics windows and experiments | P2 | 0 | Delivered 2026-10-18: a `metric` step ("Record a metric") records a number against a `metric` (slug), optional `variant` and `subject`, and a `window` — day, week (ISO) or month in the workspace's time zone, or one named outright (2026-10-18, 2026-W42, 2026-10); one observation per key, so recording again replaces the value and a rerun never double-counts. `op: "read"` lists observations back (rows, count, total, text headed "Observations, not conclusions:"). A dry run writes nothing. Settings → Automation → Metrics and GET /api/groups/metrics/observations list them (filters: metric, variant, subject, window range); an admin can remove one. No comparison or significance is computed, and no scheduled task trims them. Left: collecting the numbers from a network (social-adapters). |
| `ops-triggers` | Operational events as workflow triggers | P2 | 0 | Delivered 2026-10-18: ai_budget_threshold_reached/_exceeded, integration_attention_needed/_resolved, webhook_delivery_failed and scheduled_task_failed (the workspace's own tasks; a platform task belongs to no workspace) are triggerable under the editor's Operations heading, their payload fields read as `${event.<field>}` (describe_event and the authoring guide list them). A workflow is never woken by a failure its own run caused: the engine's running-workflow guard covers what a run does itself, and a failed delivery that runs after the run joins the delivered event's chain (correlation id, reaction depth), where a workflow with a run in it sits out. The independent fallback is Settings → Automation → Notifications, which needs no workflow. |
| `relative-dates` | Relative dates and cron schedules | P1 | 0 | Delivered 2026-10-12: every date key of a query (created/updated/published_after|before) takes a relative date (-7d, -12h, -2w, +3d, now, today), read when the run starts; an unreadable date fails the query instead of widening it. Cron schedules compute next_run_at in their time zone and fire (services/cron.py). |
| `sandbox` | Schema validation / sandbox handler | P2 | 0 | Delivered 2026-10-18: a `schema_check` step ("Check against a schema") — `document` (usually a fetch step's `${steps.<id>.output.json}`, or any template; text holding a JSON object or array is read as JSON) against `schema` (inline, or a template giving one) or `schema_resource` (a resource whose metadata.schema holds it), Draft 2020-12 → valid, errors [{path, message}] (max_errors, default 20, at most 50), error_count, truncated, text. A document that doesn't fit is output, never a failed step, unless `fail_on_invalid`; a malformed inline schema is refused when the workflow is saved; documents over 100 KB are reported, not checked; a dry run checks when it has a document. Left: running anything (a sandbox proper) and graph checks beyond a schema (reachability over cycles). |
| `snapshots` | Entity snapshots and restore | P2 | 0 | Delivered 2026-10-18: a `snapshot` step captures an entry's title, summary, description, data, metadata, status, collections and attached asset references into `entry_snapshots` (reusing the latest when identical; 20 kept per entry) and a later `restore` step (or `POST /entries/{id}/snapshots/{id}/restore`) puts content, collections and assets back through the entry service, so the normal events fire; status only when asked, through the publish gate, never into or out of the Trash; AUTHOR+ like any entry write; a dry run previews the diff. External publications (a newsletter sent, a webhook delivered) are not restorable and the entry page has no snapshots list yet. |
| `waits` | Durable waits and delays | P1 | 0 | Delivered 2026-10-13: a `wait` step — `for` (30m, 12h, 3d, 2w) or `until` a date/datetime with `offset` and `at`, in the workspace's time zone, calendar arithmetic across clock changes — parks the run (workflow_waits, the run's snapshot incl. its inputs); a minutely sweep resumes it with the entry as it is then; the entry in the Trash or the workflow switched off/changed cancels it; a moment already past goes on at once (late); a year at most. |
| `workflow-approvals` | Approval step inside a workflow | P1 | 0 | Delivered 2026-10-11: an `approval` step parks the run (snapshot in workflow_approvals), asks members at its role (push, Automation → Approvals, app badge), resumes from the next step with ${steps.<id>.output.decision} (approved | denied | expired | stale — the entry changed after it was asked), expires hourly, and lets integration actions marked requires_approval run in an approved run. Also delivered: one-tap Approve/Deny on the push when every later step can be undone in Marvin (2026-10-11, befe2ef0); `choices` (the approver picks one: `choice`, `choice_index`), length conditions, cancelling a waiting run (2026-10-13, f12b80c1); `image` shown with the question, and a picture's decision stamped on its asset (2026-10-13, 68d8392a / 6c99c7f4); the wait limit is a workspace setting (2026-10-14, 70ac6143). |
