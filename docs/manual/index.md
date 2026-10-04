# Marvin

Marvin is a headless CMS. Every workspace has its own content model, automation, AI setup and API credentials; the admin UI, the platform API under `/api/platform/…` and the publishing API under `/api/publish/{workspace_slug}/…` are all scoped to one workspace at a time. This site is the manual for version 1.0.0-rc.186.

## What a workspace contains

| Area | What it is |
|---|---|
| Entry types and entries | You define entry types (field schemas); entries are the content. Each entry has one status: `inbox`, `processing`, `draft`, `needs_review`, `approved`, `published`, `archived`. New entries start in `inbox`. |
| Collections | Manual lists of entries, or smart collections whose membership follows rules (entry types, statuses, field conditions, rolling `published_within_days` / `created_within_days` windows), built visually and previewed with **Run Query**. **Visible to sites** decides whether the publishing API serves a collection. |
| Assets and resources | Uploaded files (local disk or S3) and external links, attachable to entries and served through the publishing API. |
| Forms | A submittable entry type is a form. A public submit creates an `inbox` entry and emits `form_submission_received`, guarded by rate limits, honeypot, CAPTCHA and submission protection. |
| Publishing API | Read-only endpoints for sites (`entries`, `collections`, `assets`, `resources`, `entry-types`, `site`), authenticated with an API client token. |
| Automation | Events and the event log, workflows (triggers, conditions, steps), incoming webhooks, outgoing webhooks and scheduled tasks. |
| Integrations and blueprints | Provider plugins with connections, actions and event subscriptions, plus blueprints that create the entry types, fields, collections, scheduled tasks, incoming webhooks, workflows and event subscriptions they need. |
| AI | Operations (summaries, tags, alt text, …), agents with a per-tool permission matrix, Ask threads, the Ask bubble with an optional animated character, a search index of published content, usage limits, and external MCP servers. |
| Admin | Platform overview, users, workspaces, installed plugins, backups, maintenance, submission protection defaults, the bubble-character library, system scheduled tasks. |

The admin sidebar shows **Dashboard**, **Ask**, **Content** (**Entries**, **Collections**, **Assets**, **Resources**), **Workspace → Settings** and **Profile**; super admins also get **Administration → Admin Settings**, which opens the platform admin at `/admin`. Its **Overview** has a card each for version and health, people, plugins, the last backup (flagged when there is none or it is older than 7 days) and scheduled tasks. Its sidebar groups the pages as **People & access** (Users, Workspaces, Roles), **Settings** (Site Settings, Email, Submission Protection), **Extensions** (Plugins, Character Library) and **Operations** (System, Scheduled Tasks, Backups, Maintenance), and ends with **Back to workspace**. This manual names those pages **Admin → group → page**, for example **Admin → Operations → Scheduled Tasks**. The **Entries** row carries a badge with the number of entries waiting in `inbox`. The top bar holds the activity bell, **Review Queue** (entries in `needs_review` or `approved`) and **Logout**. The dashboard's **Needs Attention** panel counts entries in the inbox (form submissions, AI drafts) and drafts awaiting review separately, each linking to its own entries filter, plus pending AI suggestions and failed runs from the last 7 days.

**On a phone.** At 920 px wide and below, the sidebar of the workspace admin and of the platform admin becomes a drawer behind a menu button (three lines, "Open navigation") in the top bar. It closes on the backdrop, Escape, a link, or widening the window, and keeps keyboard focus inside while open. On a phone the top bar's actions wrap under the title, pages do not scroll sideways (wide tables scroll inside their own box), the entry editor shows the form first and Entry Details after it, activity toasts stay inside the screen edges, and the Ask bubble rests bottom-left. Desktop layouts are unchanged.

**Activity toasts.** While the tab is visible, the admin polls `GET /api/platform/events/feed?since=` every few seconds and shows a toast for workflow runs and failures, incoming webhooks, site rebuilds queued and sent (with an "N changes" list of what each covers), failed webhook deliveries, site builds and deploys (started, completed, failed), failed scheduled tasks and AI operations, scheduled publishes that are waiting (the entry can't publish yet, or needs approval), AI budget warnings and limits, full search-index reindex runs, form submissions, and entries created, updated, published, unpublished or deleted by someone else. Failure and warning toasts stay until dismissed; the rest fade, but not while the pointer or focus is on them or a change list is open. Click the bell to cycle **Activity: all** → **Activity: failures only** (failures and warnings) → **Activity: off**; the choice is remembered per browser and changes nothing on the server. Two toasts update in place. A queued site rebuild shows "Site rebuild queued — building in about …" and becomes **Site rebuild sent** when it goes out; a workflow run shows "Workflow '…' is running…" (with the number of entries for a query run) and becomes its result when it finishes. A run that finishes before the next poll shows only its result. Workflow and failed scheduled-task toasts link to that workflow or task. Everything shown is already in the event log.

**Event log.** **Automation → Event Log** lists the newest 100 events. Each row names what its event is about (`entity_type` and `entity_id`) and links it to its admin page where there is one: an entry, asset, collection, resource, entry type, scheduled task, workflow, outgoing webhook, and the list pages for incoming webhooks, integrations, members, invitations and API clients. Other types show as plain text. A workflow run also names what triggered it, for example "from Entry 'Issue 12'". The entity chips filter the list by type, and the dashboard's activity list links each entity the same way. Site rebuild and deploy events (`site_rebuild_queued`, `webhook_triggered`, `site_deployment_*`) are about the workspace's deploy target: the one outgoing webhook, or integration action, wired to `webhook_triggered`. When there are several, these events name none. A deployment id reported by the host stays in the event's data.

!!! tip "What's new since July 2026"
    Forms became entry types, workflows and webhooks grew, agents and Ask threads arrived, and integrations gained blueprints. Read the summary in [What's new](whats-new/index.md).

## Start here

**Content teams**

- [Forms and submission protection](whats-new/forms-and-submission-protection.md)
- [Collections](whats-new/collections.md)
- [Agents and Ask](whats-new/agents-and-ask.md)

**Operators**

- [Operations](operations.md): health probes, images, Helm chart, scheduler, storage, retention, backups, settings
- [Auth and tokens](auth-and-tokens.md): sign-in providers, personal tokens, API clients, secrets
- [Scheduled tasks](whats-new/scheduled-tasks.md)

**Developers**

- [API reference](api/index.md) (rendered from [`openapi.json`](openapi.json)), the [SDK](https://inneropen.github.io/marvin/sdk/) and the [CLI](https://inneropen.github.io/marvin/cli/)
- [Publishing API](whats-new/publishing-api.md) and [Marvin as an MCP server](whats-new/marvin-as-mcp-server.md)
- [Workflows](whats-new/workflows.md), [incoming webhooks](whats-new/incoming-webhooks.md), [outgoing webhooks](whats-new/outgoing-webhooks.md), [integrations](whats-new/integrations.md), [blueprints](whats-new/blueprints.md)

## Repositories

| Repository | Contents |
|---|---|
| [InnerOpen/marvin](https://github.com/InnerOpen/marvin) | Server (FastAPI), admin frontend (Astro), Helm chart, this manual |
| [InnerOpen/marvin-sdk](https://github.com/InnerOpen/marvin-sdk) | `@inneropen/marvin-sdk` TypeScript client |
| [InnerOpen/marvin-cli](https://github.com/InnerOpen/marvin-cli) | Command-line client |
| [InnerOpen/marvin-mcp](https://github.com/InnerOpen/marvin-mcp) | MCP server that exposes a workspace to AI clients |
| [InnerOpen/marvin-astro](https://github.com/InnerOpen/marvin-astro) | Astro integration for sites built on the publishing API |
| `InnerOpen/marvin-integration-*` | Integration providers (Slack, Instagram, Apprise, OpenAI Images, Square, Cloudflare Pages, Buttondown, …) and the integration SDK |

See the [glossary](glossary.md) for the vocabulary used across these pages.
