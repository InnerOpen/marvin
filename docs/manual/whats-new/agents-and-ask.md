# Agents and Ask

Named agents with a per-tool permission matrix, plus an Ask page that keeps conversations, citations and live tool steps on the server.

## What it does

Three built-in agents exist in every workspace (they are code, not rows, so nothing is seeded):

| Slug | Kind | Tools | Notes |
|---|---|---|---|
| `marvin` | persona | every tool your role allows | the default agent and the router: it can hand a question to another agent; in-workspace writes are allowed, workflow runs and external MCP writes ask first. Listed under the workspace's **Assistant name** |
| `ask` | persona | `search_content`, `workspace_overview`, `search_docs`, `read_doc`, `suggest_agent` | grounded answers only; cites the entries it used; can refer you to another agent but never runs one |
| `chat` | model | none | plain conversation; tells you to use Ask or Marvin for content questions |

The `marvin` agent carries the workspace's assistant name (AI Settings → **Persona**), so after a rename the Ask page's agent picker, the bubble's `/agents` list, MCP `list_agents`, hand-offs and the `chat` agent's "use the … agent" pointer all use the new name; the slug stays `marvin`.

Admins can define more on the **Agents** page. An agent is a definition with these fields: `kind` (`persona` = instructions + tools, run through the tool loop; `model` = a plain completion, no tools), `system_prompt`, `model_override`, `tool_allowlist` (hard filter; `null` = no restriction), `min_role` (who may talk to it, 1–5), `sources`, `enabled`, `allow_writes`, `tool_policy`, `icon`, `suggestions` (up to 8 suggested prompts), `default_register` (a tone slug: `auto`, `professional`, `playful` or one of the workspace's own [tones](#tones); an unknown slug is a 422) and `handoff_hint` (one line telling the router when to hand a question to this agent). Slugs may not shadow the built-ins.

Every persona run gets a workspace preamble that says which workspace it is in, that "the RAG / knowledge base / index" means the workspace content, which bound tool answers which kind of question, and which external MCP servers are connected. A reply that only promises to check something ("give me a moment") is nudged once to act instead. When you name a connected MCP server ("check the vault"), the agent answers from that server's tools itself and does not hand the question to another agent unless you name that agent, since the others may not see the server. An agent with no external MCP tools bound says it cannot reach an outside source rather than presenting workspace results as coming from it.

**Hand-offs and referrals.** `marvin` sees a roster of the other agents you may talk to (their description and "Hand off when…" line). When you name an agent, ask for its voice, or the question matches its hint, `marvin` calls `run_agent`, then answers in its own voice and names the agent it asked. The specialist runs with its own matrix on a child thread and cannot hand off further. Other agents cannot hand off (the `agents_run` row defaults to Block except on `marvin`); they can call `suggest_agent`, which records a referral the answer shows you. Executions started inside an agent run carry `parent_execution_id` in their metadata.

**Permission matrix.** Every bindable tool belongs to one category (`entries_read`, `entries_author`, `links`, `library_read`, `assets_import`, `automation_read`, `automation_run`, `insights`, `docs_read`, `agents_read`, `agents_run`, `ai_ops`, `mcp_read`, `mcp`, `mcp_destructive`, `other_read`, `other_write`). `tool_policy` maps a category id or tool name to `allow`, `ask` or `block` (shown as Allow, Ask first, Block). Resolution order for one tool: allowlist, then a tool-level entry, then a category-level entry, then the category default:

- reads allow;
- `agents_run` (hand-offs) allows only on `marvin`;
- writes on a workspace agent ask first when **Allow writes** is on and are blocked when it is off;
- on `marvin`, writes allow except `automation_run`, `mcp` and `mcp_destructive`, which ask first.

A write is never bound for a caller below AUTHOR, whatever the matrix says, and that holds for `ask` too.

**Ask first.** An `ask` tool is bound, but when the model calls it the run parks on its Ask thread (status `awaiting_approval`) and the page shows a card with one checkbox per pending call: **Approve selected** or **Deny all**. Approved calls run, denied ones tell the model you declined, and the run continues on the same thread and execution (`POST /api/ai/threads/{id}/resume`; a missing decision counts as a deny, and only the thread's owner may decide). Where there is no thread to park on — an MCP `run_agent` call, a hand-off child — an `ask` tool is not bound, so it behaves like Block. Decisions emit `approval_granted` / `approval_rejected` events.

**Big bulk writes ask first.** `attach_tag`, `detach_tag` and `import_asset` with `attach_to` size each call before running it: targets × items is the number of links it would make. A call of more than 20 links, or of more than 5 tags (or images) across more than one target, pends as an Ask-first call even where the matrix allows the tool outright and whatever the approval mode. The approval card shows a summary such as "Attach 12 tags to 19 assets (228 links)" and lists the targets and items. Where the run cannot park (no thread, an MCP `run_agent` call, a hand-off child), the tool writes nothing and tells the model to work in smaller steps or to ask you in a conversation where you can approve it.

**Tagging.** Agents are told to choose tags per item from what that item is, never to attach a whole tag vocabulary wholesale, and to tag images with `generate-tags` one asset at a time. `generate-tags` describes the asset or resource it is given and, for an image asset on a vision-capable model, sends the image itself; its optional `vocabulary` input lists existing tags to reuse where they fit.

**Interrupted runs.** An agent run is one request, so a restart that kills the process mid-run (a deploy past its grace period, an out-of-memory kill, a crash) used to leave its execution `running` forever. When the server starts, executions still `running` from an earlier process are marked `failed` with "Interrupted: the server restarted while this run was in progress.", and the run's thread gets a short reply saying it was interrupted and that anything changed before the restart is kept, which the bubble picks up as the answer. Runs parked on an Ask-first approval are not touched; they resume on any process. Deploys first let runs finish (see [Operations → Helm chart](../operations.md#helm-chart)).

**Approval mode is a different thing.** The matrix decides what an agent may *do* (tag, attach, run a workflow). The workspace **Approval Mode** (see [Settings](#settings)) decides whether AI-*generated content* lands on a record without a person: it covers every AI write-back — an operation's write-back, revise, a workflow operation step with `write_back`, and the alt text compose writes onto assets. Held-back output waits as a suggestion to accept.

**Finding entries.** `find_entries` uses the same entry query as a workflow's "Run on a query of entries", an entry step's `entity_query`, and the bulk `filter` of `attach_tag` / `detach_tag` (up to 1,000 targets), so a filter works the same everywhere. All keys are optional:

| Key | Meaning |
|---|---|
| `entry_type` / `entry_types` | type slug(s) |
| `status` / `statuses` | the **publish** status (`inbox` … `archived`); a value that is not one (usually a field's value) returns a note instead of a silent 0 |
| `fields`, `metadata` | exact match on the type's own fields or on metadata, `{field_key: value}`; typed-in text such as `true` or `12` matches checkbox and number values |
| `where` | `[{field, op, value}]`; `field` is a field key or `metadata.<key>`; `op` is `eq`, `neq`, `in`, `contains`, `exists`, `missing`, `gt`, `gte`, `lt`, `lte`. Comparisons read number-like text, so `"$1,170"` compares as 1170 |
| `query` | title or slug contains |
| `tags`, `collection` / `collections` | any of these (slug or name) |
| `has_images`, `has_assets`, `has_resources` | attachment filters |
| `created_`, `updated_`, `published_` + `after` / `before` | ISO dates or datetimes (UTC) |
| `sort` | `{by, direction}`; `by` is `title`, `created_at`, `updated_at`, `published_at` or a field key (numeric when the values are number-like; empty values last) |
| `group_by` | a field key, `publish_status` or `entry_type`: counts per value over the whole match |
| `limit`, `offset` | page size (default 10, max 200) and offset |

In `where`, `sort` and `group_by` a bare key is always the type's own field (a type may have its own `status` field); use `publish_status` for the entry's lifecycle status. `include_fields` / `include_metadata` put those values on each row. The result has `count` (the true total), `returned`, the rows and `groups`; `where`, field sorts and `group_by` read at most 5,000 candidate rows, and the result says so when that bound is hit.

**Linking to entries.** Marvin only knows where your site shows an entry if you tell it: set the workspace's **Canonical URL** (Settings → General) and a **Page URL pattern** on the entry type (see [Publishing API → Entry page URLs](publishing-api.md#entry-page-urls)). Then `find_entries`, `get_entry`, `get_collection_entries` and `search_content` give each entry of that type a `url`: absolute when the Canonical URL is set, otherwise the site path. Agents are told to link entries with that `url` exactly, to prefer the absolute form in anything that may be emailed, and never to write placeholder links such as `[Title](#)`; an entry without a `url` is written as plain text and the reply says it couldn't be linked. An unpublished entry still gets its `url` (where it will live), and its `status` says it isn't live yet. `compose_entry` and `revise_entry` follow the same rule: put the `url`s in the brief, or the entries are named without links. Nothing changes for a workspace that sets neither.

**Ask.** The Ask page is the agent chat. A run with `thread_id: "new"` opens a server-side thread; passing an id continues it and its stored turns become the history. Threads are yours only (admins see every thread in the workspace); you can reopen, rename and delete them. The **Threads** panel lists all of them across agents, newest activity first, each labelled with its agent (the main agent under the assistant name), so a conversation started in the bubble shows up there too; a hand-off's specialist thread is indented under the thread that made it. **This agent only** narrows the list to the agent picked above (remembered per tab); for a specialist that includes its hand-off threads, each noted "from a hand-off in …" with the parent thread's title. Runs return `threadId` and `sources` (citations extracted from the run's own `search_content` results). If the client mints a `client_run_id`, it can poll live `thinking` / `tool_call` / `tool_result` events while the POST is in flight; the page shows them as a step timeline. A file you attach is uploaded as an asset and stays with the conversation for every later turn.

Two read-only tools support this: `workspace_overview` (entries by type and status, collections, assets, resources, tags, embedding-index coverage, and a `structure` listing every workflow, scheduled task, incoming and outgoing webhook, MCP server, integration and agent by name and slug) and `view_image(asset, question?)`, which asks the vision model about an image and writes nothing back to the asset (only a `tool:view_image` execution row for cost accounting). `run_workflow` matches a workflow by slug, name or id, case-insensitively, and lists the workflows that exist when nothing matches.

**Marvin's manual.** `search_docs(query, limit?)` searches this manual and returns the best-matching sections with their page, heading, anchor, a snippet and the published link; `read_doc(path, section?)` returns a page, or one section by anchor or heading, as markdown. They read the manual bundled with the running version (not the published site, which can be a deploy ahead or behind), rank by keywords with heading and title boosts (no AI cost), and say so plainly when the manual is not bundled. Both are in the **Read Marvin's documentation** row (`docs_read`), allowed by default for every agent including Ask. When they are bound, the preamble tells the agent to answer how-to questions about Marvin from the manual, cite the page's link and use its exact screen labels instead of guessing.

**The bubble.** The Ask bubble in the admin wears the workspace persona: the **Assistant name** and **Bubble icon** from AI Settings (an emoji, or an image URL that wins over the emoji; blank means "Marvin" and 🤖). Its agent conversations are server threads, one per agent (the default agent, or one picked with `/use`), so they appear under **Threads** on the Ask page and the server, not the browser, holds the agent's memory. A run keeps going if you navigate away: the next page shows the thinking placeholder and picks the answer up from the thread, and stops waiting after 10 minutes with a link to the conversation. **Clear** starts a new thread. When an Ask-first tool parks the run, the bubble says it needs your go-ahead and links to that thread on the Ask page (`/workspace/settings/ai-ask?thread=<id>`), where you approve or deny it. The other bubble commands (`/ask`, `/chat`, `/tools`, `/agents`, `/use`, `/help`) do not use a thread. The bubble keeps its threads, a run in flight, the agent picked with `/use` and the transcript per workspace (in the tab's session storage), so a tab that switches workspaces never sends one workspace's thread to the other. If a remembered thread is gone (deleted on the Ask page, so the server answers 404), the bubble forgets it and sends the message again on a new thread. The bubble rests at the bottom-left of the window. Drag it anywhere: it remembers the spot in this browser as distances from the nearest edges, and stays on screen when the window is resized or a phone rotates. Double-click it to send it back to the corner.

**Bubble lines.** Between answers the bubble speaks canned lines: a greeting when the panel opens, a tagline rotating under its name, a line while it works, an opener for an error, and emotes such as *smiles*. Under AI Settings → **Persona**, **Bubble lines** holds the workspace's own set, one list per kind, one line per row. When you save a **Voice / tone** (a new or changed one, a new assistant name, or any voice while there are no lines yet), one AI call writes the lines in that voice; it runs in the background, so the save returns at once and the card says *Writing lines from the persona…* until they arrive. The call uses the workspace's provider and model, counts against **Usage & Limits** like any other run, and appears under **AI Executions** as `generate-bubble-lines` (trigger `settings`). If it is refused (a limit is reached, AI is off) or the model's answer is unusable, the previous lines stay and the card says why. Editing the lists and clicking **Save lines** (or **Save Settings**) marks them *Edited*: a later voice change leaves edited lines alone, and only **Regenerate from persona** replaces them (it asks first). **Clear** goes back to the built-in lines; so does clearing the voice, for lines that were generated. An empty list falls back on its own, to the lines shown greyed in its box. Which lines the bubble speaks, per list: the workspace's own; otherwise Marvin's while the assistant is named Marvin, whatever its voice; otherwise, for a renamed assistant, a plain neutral set — a renamed assistant never speaks Marvin's lines.

**Bubble character.** Under AI Settings → **Persona**, **Bubble character** replaces the round icon with an animated character, one animation per state. The picker is a row of cards, one of which is outlined as the current choice: **None — the icon**, one card per pack in the platform's character library (below) showing the pack's idle animation, and **Own upload**, which shows your idle animation once there is one. Keyboards and screen readers get it as a plain radio group. For your own, click **Upload character…** and choose a .zip or GIF, WebP or PNG files. Files are recognised by their content, never their extension, and SVG is never accepted; one upload holds at most 20 images, 5 MB each and 20 MB in all, and other files are skipped and listed. An image with an opaque solid background (a box around the character, common in generated packs) has the background connected to its edges made transparent, and the picker lists the files it changed; the rest of the image is kept exactly. Files stored before uploads did this can be cleaned in place by an operator (see [Operations → Storage](../operations.md#storage)). Each file's name (without extension, case ignored, `_` and spaces read as `-`) picks its state:

| State | Label in the picker | File names, best first | Plays when |
|---|---|---|---|
| `idle` | Idle | `idle` | nothing else is happening; required |
| `idle_variant` | Idle fidget | `look-loop`, `look`, `look-around` | once now and then while idle, 20–40 seconds apart |
| `greeting` | Greeting | `waving`, `wave`, `greeting` | the panel opens |
| `thinking` | Thinking | `review`, `thinking`, `think` | a message is sent, before the agent's first step |
| `working` | Working | `running`, `working`, `run` | the agent's steps are running |
| `waiting` | Waiting for approval | `waiting`, `wait` | the run is parked on an Ask-first approval |
| `success` | Success | `jumping`, `jump`, `success`, `idle-jump-idle` | the answer arrives |
| `error` | Error | `failed`, `error`, `fail` | the run fails |
| `move_left`, `move_right` | Dragging left, Dragging right | `running-left`, `move-left`, `walk-left`; `running-right`, `move-right`, `walk-right` | the bubble is dragged that way |

Greeting and success play for about two seconds and error for four, then the character goes back to idle; the newest event always wins. When two files claim one state, the one matching the earlier name wins. Files named anything else are kept, unassigned: each state's row has a dropdown of every file in the pack, so any file can play any state, and the picker lists the files no state uses. With no file named for idle, the first image plays as Idle until you pick another. Idle can be changed but not cleared. A state with no animation of its own falls back to Idle (dragging tries Working first); the row's thumbnail is dimmed and its dropdown reads "— default (falls back to …)". Changes save as you make them, with no **Save** needed. The images are stored as workspace assets; replacing the character, switching to a library pack or to **None** (after a confirmation) deletes exactly the assets it created. Viewers who prefer reduced motion see a still of each state's image and no fidget or drag motion. If an image will not load (its asset was deleted, say), the bubble shows its icon instead.

**Agent characters.** On **Agents**, an agent's own character is under **Edit → Bubble character**, below Icon and Name; the **Character** button on its card opens the same picker without opening Edit. The cards there are **None — the workspace's character**, each library pack and **Own upload**. A new agent gets a character once it exists (the **New agent** form says where to find it). The bubble shows the character of whoever is talking: after `/use <agent>` that agent's, until `/use marvin`, and during a hand-off the delegate's while it works, until the answer lands. An agent's character covers what it covers: a state it lacks plays the workspace's, and with no character on either the bubble shows its icon. Built-in agents have no character of their own; they show the workspace's.

**Character library.** A platform super admin installs packs once, under **Admin → Extensions → Character Library** (`/admin/character-library`), and any workspace or agent can pick one. **Add a pack** takes a name (blank uses the .zip's name) and the same kind of upload. Each pack has a card where you can **Rename** it (its slug stays), give it new files with **Replace files…**, pick its states, or **Delete** it. Everyone using a pack gets its new files, name and picks. A workspace cannot change a library pack's animations; it uploads its own instead. The card says who uses the pack. **Delete** on an unused pack asks to confirm. On a pack in use it names the users and asks whether to delete it anyway: if you confirm, they are unlinked first (a workspace falls back to its icon, an agent to the workspace's character), then the pack and its files are removed. A pack's files belong to no workspace (see [Operations → Storage](../operations.md#storage)).

**External MCP servers.** Register HTTP (streamable) or SSE servers (stdio is not supported) with an optional **Auth secret** (a workspace secret slug sent as a Bearer token). Servers start disabled and expose nothing until you allow tools (deny by default). **Choose tools** runs `tools/list` and returns each tool's `readOnlyHint` / `destructiveHint`; bound tools are named `mcp__<server>__<tool>` and sorted into the `mcp_read`, `mcp` (writes, or no hints) or `mcp_destructive` rows from those hints, so a read-only agent can reach a server's read tools. The **External MCP tools** master switch on the MCP Servers page (`external_mcp_enabled`) must be on. A tool call waits up to `MCP_TOOL_TIMEOUT_SECONDS` (default 45) before the model is told it failed, and a result longer than `MCP_TOOL_RESULT_MAX_CHARS` (default 20,000) is cut, with a note asking the model to narrow the call.

**Search index.** `search_content` and grounded Ask answers read an embedding index of the workspace's published entries, resources and assets (icons and logos with nothing but a name and tags are left out). Publishing or editing a published entry indexes it, and unpublishing, archiving or deleting it takes it out, so drafts, inbox and archived entries are never searchable. A save that leaves the indexed text unchanged (a workflow writing metadata, say) does not re-embed. **Reindex now** on the Ask page rebuilds the whole index in the background, so you can leave the page: chunks are embedded in batches, unchanged items are skipped, and drafts and archived entries left over in the index are purged. The card shows chunks held, items indexed out of indexable items, the run's progress and the last run's summary; while a run is going the button is disabled and a second request gets 409. The finished run emits `ai_embeddings_reindexed` with indexed, skipped and failed counts and the first error, which shows as a **Search index** activity toast. The `ai_reindex_embeddings` scheduled task uses the same path. Reindexing needs EDITOR or higher and a provider with embeddings.

## Where

All under **Workspace Settings → AI**:

- **Agents** (`/workspace/settings/ai-agents`) — built-in agents with their effective permissions, your agents, create/edit/delete, the matrix editor.
- **Ask** (`/workspace/settings/ai-ask`, also "Ask" in the sidebar; `?thread=<id>` opens a thread) — agent picker, Threads and Tools panels, tone, attachment, dictation, suggested prompts, approval cards, the **Search index** card with **Reindex now**.
- **MCP Servers** (`/workspace/settings/ai-mcp-servers`).
- **AI Settings** (`/workspace/settings/ai-workflow`), including the **Usage & Limits** card and **Persona → Bubble character**. **AI Executions** (`/workspace/settings/ai-executions`): status, tokens and cost.

Platform super admins: **Admin → Extensions → Character Library** (`/admin/character-library`).

## How to use

1. On **AI Settings**, turn on **AI Features**, choose a **Credential Mode** (Platform or Workspace), a provider and model, an **Approval Mode**, and the **Invocation Sources** you want. Under **Persona**, optionally set the assistant name, bubble icon, bubble character and voice; under **Tones**, the default tone and any tones of your own. Under **Usage & Limits**, optionally set a monthly cost limit, a daily request limit and an output-token cap.
2. On **MCP Servers**, turn on **External MCP tools** and add servers if agents should use them.
3. On **Agents**, click **+ New agent**: icon, name, slug, description, "Hand off when…", instructions, suggested prompts, model, kind, default tone, "Who may talk to it", **Allow writes**, **Enabled**. Adjust the Tools matrix per group or per tool (Inherit, Allow, Ask first, Block). New agents are read-only until you turn on Allow writes, and a write still needs the caller to be AUTHOR or higher. Click **Character** on an agent's card to give it a bubble character of its own.
4. On **Ask**, pick the agent, type or dictate a question, optionally attach a file. Open **Threads** to reopen an earlier conversation, from any agent or the bubble; **Tools** shows the effective matrix for you. Approve or deny any "Before I continue, approve these actions" card.
5. Review usage on **AI Executions** (status, tokens, estimated cost per execution). Agent runs show as `agent:<name>` with the agent's current name, so renaming the assistant renames its history; hovering shows the stored `agent:<slug>`, which is what filters match. A model with no known price shows its cost as unknown (—) rather than Free; self-hosted providers cost nothing. The month at a glance is on **AI Settings → Usage & Limits**.

## API

All under `/api/ai`; role gates as noted. Full reference: [API reference](../api/index.md).

| Method and path | Purpose |
|---|---|
| `GET /agents`, `GET /agents/{slug}` | list / read agents (built-in + workspace) |
| `POST /agents`, `PATCH /agents/{slug}`, `DELETE /agents/{slug}` | define / edit / delete (ADMIN+; built-ins cannot be edited) |
| `GET /agents/catalog` | categories and every bindable tool, including MCP tools discovered right now |
| `GET /agents/{slug}/permissions` | effective matrix for the caller (`rows[].tools[].decision`, `reason`) |
| `POST /agents/{slug}/run` | run an agent; body `AIAgentRequest` (`message`, `history`, `register`, `thread_id`, `client_run_id`, `entity_type`, `entity_id`, `model_override`, `max_steps`, `source`, default `agent`; the Ask page sends `ask_page`) |
| `POST /agent` | the default `marvin` run (AUTHOR+) |
| `GET /agents/runs/{run_id}/progress` | `{status, events, threadId, executionId, error}` for a run started with `client_run_id`; 404 = nothing recorded |
| `GET /threads?agent=&limit=&children=` | my threads (admins: all); `children=true` brings along the specialist threads their hand-offs opened, with `parentTitle` (`limit` counts the listed threads, not the children) |
| `GET /threads/{id}`, `PATCH /threads/{id}`, `DELETE /threads/{id}` | read with messages and `pending`; rename; delete |
| `POST /threads/{id}/resume` | decide a parked run's calls (`decisions: {call_id: "approve"}`, anything else denies) and continue it; `source` defaults to `agent` (the Ask page sends `ask_page`); 409 when nothing is waiting |
| `GET /agent/tools` | the tools the loop would bind for you right now |
| `POST /agents/{slug}/character`, `DELETE /agents/{slug}/character` | ADMIN+, workspace agents only. Upload the agent's own character (multipart `files`; the response adds `ignored`, `idleGuessed` and `cleared`) / remove it, so the agent shows the workspace's again |
| `PUT /agents/{slug}/character/states`, `PUT /agents/{slug}/character/library` | ADMIN+. `{state, file}` plays one of its files for a state (`file: null` clears it) / `{pack}` (id or slug) switches it to a library pack. `AgentRead.character` holds the result |
| `GET/POST/PATCH/DELETE /mcp-servers`, `POST /mcp-servers/{id}/test` | external server CRUD and tools/list probe |
| `POST /embeddings/reindex` | EDITOR+. `scope: "workspace"` starts a background reindex (`{status: "started"}`; 409 while one runs); `entity_type` + `entity_id` reindexes one item inline; `force: true` re-embeds unchanged items |
| `GET /embeddings/status` | `chunks`, `items_indexed`, `indexable`, `models`, `running` (`{started_at, done, total}` or null), `last_run` |

Usage against the limits is `GET /api/groups/ai-settings/usage` (see [Usage and limits](#usage-and-limits)).

The workspace's bubble character is under `/api/groups/ai-settings`; `GET /api/groups/ai-settings` returns it resolved (a library pack as its states) in `assistantCharacter`, plus `agentCharacters` (`{agent slug: states}`) for the bubble:

| Method and path | Purpose |
|---|---|
| `POST /character` | ADMIN+. Upload (multipart `files`: a .zip or images); replaces the character. Returns the character with `states`, `files`, `missing` (states without an animation), `ignored`, `idleGuessed` and `cleared` (files whose solid background was made transparent) |
| `PUT /character/states` | ADMIN+. `{state, file}`: play one of the character's files (its name or asset id) for a state; `file: null` clears the state so it falls back. 422 for a library pack |
| `DELETE /character` | ADMIN+. Back to the icon; the character's own assets are deleted |
| `GET /character/catalog` | the states and the file names each one picks up |
| `GET /bubble-lines` | the bubble lines: `bubbleLines` (`{greetings, taglines, thinking, errors, emotes}` or null for the built-in lines), `bubbleLinesSource` (`generated` / `edited`), `bubbleLinesUpdatedAt`, `bubbleLinesWarning` (why the last generation failed) and `bubbleLinesGenerating`. `GET /api/groups/ai-settings` carries the same fields for the bubble |
| `PUT /bubble-lines` | ADMIN+. The five lists; saves them as edited. Blank rows are dropped; every list empty means the built-in lines; more than 50 lines in a list or a line over 200 characters is a 422 |
| `DELETE /bubble-lines` | ADMIN+. Back to the built-in lines |
| `POST /bubble-lines/generate` | ADMIN+. Write the lines from the saved persona again, in the background (202), replacing edited ones. 422 without a persona or with AI off, 429 at a usage limit |
| `GET /character/library`, `PUT /character/library` | list the library's packs (any member) / `{pack}` (id or slug) to use one (ADMIN+; your own upload's assets are deleted) |

The library itself is `/api/admin/character-packs` (platform super admin): `GET` lists packs with `usedBy`; `POST` adds one (multipart `name`, `files`); `POST /{pack}` replaces its files; `PATCH /{pack}` renames it (`{name}`); `PUT /{pack}/states` picks a state's file; `DELETE /{pack}` deletes it; while it is in use it answers 409 naming the workspaces and agents, unless `?force=true`, which unlinks them first. `{pack}` is the pack's id or slug.

Progress and the reindex run state are process-local: with more than one backend replica a progress poll can miss and returns 404, which clients treat as "no live steps". A restart drops a running reindex's progress, never the embeddings already written.

## Settings

| Setting (`PATCH /api/groups/ai-settings`, ADMIN+) | Values | Effect |
|---|---|---|
| `enabled` | bool | master switch for AI in the workspace |
| `credential_mode`, `provider`, `model`, `secret_ref` | `platform` / `workspace` / `disabled` | where the API key comes from (`secret_ref` is a workspace secret slug, never a raw key) |
| `approval_mode` | `suggest-only` (Suggest only), `allow-draft-update` (Allow draft update), `allow-automatic-update` (Allow automatic update) | whether AI-generated content is applied or staged as a suggestion. Allow draft update applies only to entries in `inbox` or `draft` (assets and resources count as drafts). Unset or unknown stored values behave as suggest-only; the API rejects any other value with 422 |
| `invocation_sources` | `{source: bool}` | a source is allowed unless set `false`; unset allows all (see below) |
| `external_mcp_enabled` | bool, default `false` | whether agents may bind allowlisted external MCP tools |
| `assistant_name`, `assistant_icon` | text; emoji (up to 16 characters) or image URL | the bubble's name and icon; blank = "Marvin" and 🤖 |
| `assistant_character` | `{"states": {state: image URL}}`, `{"library": pack id or slug}` or `null` | the bubble character: re-map the states of your own upload, switch to a library pack, or remove it. Uploads go through `POST /api/groups/ai-settings/character` |
| `persona_prompt` | text | the voice, appended to the system prompt. Blank = Marvin's built-in voice while the assistant is still named Marvin (the full Marvin character, quoting the bubble's own lines so chat and bubble sound alike); a renamed assistant with a blank persona gets a neutral voice. Saving it (or `assistant_name`) writes the bubble lines from it unless they were edited — see **Bubble lines** above |
| `default_register` | a tone slug (`auto`, `professional`, `playful` or a [custom tone](#tones)); unknown or hidden → 422 | how work product reads: Auto keeps the voice for chat but writes reviews and copy plainly; Professional drops the persona; Playful applies it everywhere. Precedence for a named agent: a per-call `register` other than `auto`, then the agent's default tone, then this setting |
| `budget_config` | `max_cost_per_month_usd`, `max_requests_per_day`, `max_tokens_per_request` | the limits on the **Usage & Limits** card; see below. Saving the form keeps budget keys it does not show |
| `logging_config`, `moderation_config` | | prompt/response logging and moderation (**Advanced Settings**) |
| `AI_AGENT_MAX_STEPS` (app setting) | int | tool-dispatch budget per run (default 6); server clamps to 12 |

**Invocation sources.** Each AI call reports which surface it comes from, and the workspace can switch a surface off. The AI Settings page lists the sources that callers actually send (`GET /api/groups/ai-settings/sources`):

| Key | Label | Sent by |
|---|---|---|
| `editor` | Entry editor | inline AI actions in the entry editor |
| `bubble` | the assistant name plus "bubble" (Marvin bubble by default) | the floating Ask bubble on every admin page |
| `ask_page` | Ask page | the Ask page and named agents run from it, including resuming a paused run |
| `automation` | Workflows | a workflow's AI-operation step, including form- and schedule-triggered workflows |
| `mcp` | External MCP hosts | `marvin-mcp` and other MCP clients |
| `api` | API | direct calls to the operation endpoints |

With **bubble** off the bubble does not appear; with **Ask page** off the sidebar's **Ask** link is hidden and the Ask page says Ask is switched off, with a link to Invocation Sources for workspace admins. Each can be off while the other stays on.

`agent` is agent chat from anywhere: the default `source` of `POST /agent`, `POST /agents/{slug}/run` and `POST /threads/{id}/resume` for API and SDK callers, and what the bubble and Ask page calls run as once they pass the check (so operation, agent and tool sources and the executions log say `agent`). It has no toggle of its own: it is off when both **bubble** and **Ask page** are off, or when a stored policy sets `agent` to `false`. Before the split, `agent` was the single "Ask Marvin" toggle; a stored `agent: false` still switches both surfaces off, and the upgrade migration rewrites it to `bubble: false, ask_page: false`. `forms`, `actions` and `scheduled` remain valid keys (old policies may store them) but nothing sends them, so they have no toggle. The source is reported by the caller, so this is feature gating, not a security boundary: per-user authorization is the role check.

### Tones

A tone is how a run's work product reads, separate from the voice (how the assistant addresses you). The **Tones** card on AI Settings lists the built-ins — **Auto** (voice for chat, plain for work), **Professional** (plain everywhere, no persona) and **Playful** (the persona applies to everything) — and the workspace's own. Pick the **default** with the radio button; untick **Show** to leave a tone out of the pickers (the default can't be hidden; a hidden tone still works for agents and parked runs that already use it). Built-ins can be hidden but not edited or deleted. Changes save as you make them; only workspace admins and owners can change tones, while anyone may pick one per request.

**Add tone** takes a **Name** (1–60 characters, unique, not a built-in's), an optional **Description** shown in the pickers, **Instructions** (1–1500 characters of free text) and what to do with **the persona**:

| Persona rule | Effect |
|---|---|
| Frame only | the persona greets and frames; work product follows the tone's instructions |
| Everywhere | the persona applies to everything, alongside the instructions |
| Drop the persona | no persona for the run — the safest choice for client-facing copy, since weaker models blur "everywhere" |

**Preview prompt** shows exactly what the tone adds to the system prompt with this workspace's persona, and a rough token count — it is sent with every agent step. A workspace can have up to 20 tones. A tone's slug is made from its name when it is created and never changes, so renaming a tone keeps every agent and default that points at it. A tone that agents default to can't be deleted: the save fails (409) naming the agents — pick another default tone for them first. Deleting the default tone needs a new default.

**Where a tone applies.** For a run, the first that names a tone wins: the request's tone (the Ask page's **Tone**, the bubble's `/tone`, an action such as "Review & suggest"; for a named agent a request's `auto` doesn't count), then the agent's default tone, then the workspace default, then Auto. A slug that names no tone (deleted since, or imported) is skipped with a warning in the log rather than failing the run. Hand-offs carry an explicit tone to the specialist. Compose and revise drafts use the tone too, but an entry type's own voice (its recipe's `enrichment.voice`) wins; with no voice the draft gets the tone's instructions (and the persona under an *Everywhere* tone; Auto and Professional leave drafts plain, Playful writes them in the persona). The agents' `compose_entry` / `revise_entry` tools use the workspace default.

**The bubble.** `/tone` lists the tones; `/tone <name or slug>` sets one for the rest of the browser session and shows it as a **Tone** chip above the conversation (× clears it); `/tone default` goes back to the workspace's.

| Method and path (`/api/groups/ai-settings`) | Purpose |
|---|---|
| `GET /tones` | any member: every tone (built-ins first) with `builtin`, `hidden`, `usedBy` (agent slugs), plus `defaultTone` and the limits |
| `PUT /tones` | ADMIN+: `{tones: [{slug?, name, instructions, persona: frame\|everywhere\|drop, description?}], hidden: [slug], defaultTone?}` replaces the custom tones and hidden list; 422 for an invalid list, 409 (`detail.tones: {slug: [agents]}`) when a removed tone is still an agent's default |
| `POST /tones/preview` | `{slug}` or a draft `{name, instructions, persona}` → `{clause, tokens}` |

Workspace export and import carry `tones` and `hiddenTones` with the AI settings; an import re-validates them and, if they don't validate, keeps the built-ins only.

### Usage and limits

The **Usage & Limits** card on AI Settings shows this month's estimated spend against **Monthly cost limit (USD)**, today's runs against **Max requests per day** (with a meter each, and the date the month resets), and a **Top this month** table of the operations and agents that cost the most (runs, tokens, estimated cost). **Max output tokens per request** caps each model call; blank uses the app default (`AI_DEFAULT_MAX_TOKENS`). A blank limit means no limit.

| Limit | Measured | At the limit |
|---|---|---|
| `max_cost_per_month_usd` | estimated cost of completed runs since the 1st of the month (UTC) | new AI runs are refused (429) until the month resets |
| `max_requests_per_day` | runs started since midnight UTC, failed ones included | new AI runs are refused (429) until midnight UTC |
| `max_tokens_per_request` | output tokens per model call | the call is capped, not refused |

The request and cost limits are checked before operations, compose, revise, agent and chat runs (Ask, the bubble, hand-offs, resuming a parked run) and workflow AI-operation steps; a step over a limit fails with the reason. Crossing `AI_BUDGET_WARNING_PERCENT` of the monthly limit (default 80; 0 turns the warning off) fires `ai_budget_threshold_reached`, reaching it fires `ai_budget_exceeded`, and a provider call refused for lack of credit fires `ai_provider_quota_exceeded`; each shows as an activity toast that stays until dismissed. Costs are estimates from Marvin's price table, embedding calls for the search index are not counted, and the provider account's own balance is not visible to Marvin.

`GET /api/groups/ai-settings/usage` returns the same numbers: `limits`, `warning_percent`, `level` (`ok`, `warn`, `over`), `month_cost_usd`, `month_tokens`, `month_runs`, `month_percent`, `today_runs`, `day_percent`, `resets_on` and `by_operation` (up to 8 rows with `operation`, `label`, `runs`, `tokens`, `cost_usd`).

### OpenAI and other providers

The official OpenAI API is called through OpenAI's Responses API for chat, tool calls and structured output, so any chat model takes the same length limit and can call tools while it reasons. An OpenAI-compatible server (the OpenAI provider with a custom base URL) and Azure OpenAI use Chat Completions. No provider sends a temperature unless `AI_DEFAULT_TEMPERATURE` is set, so each model uses its own default. If a server still refuses a parameter (a configured temperature, `max_tokens` where it wants `max_completion_tokens`, tools while reasoning), Marvin retries with the fix named in the 400 and remembers it for that model until the process restarts. The OpenAI model picker leaves out models that cannot chat (embeddings, speech, image, moderation and similar).

## Since

Agents, the matrix, Ask threads and live steps: 1.0.0-rc.70–rc.77 (commits `75d4410f`, `de56ba94`, `49d1aae1`, `4cafa466`, `8929438c`, `7ab55c2d`, `5e835709`, `699540fd`). Router hand-offs and referrals: rc.98–rc.100. Ask first with resume: rc.107. Workspace inventory in `workspace_overview` and forgiving workflow lookup: rc.108. `parent_execution_id`: rc.106. Unknown cost for unpriced models: rc.110. Blank persona = default voice: rc.133. Approval mode covers every write-back; `agent` as the Ask Marvin source: rc.134. Bubble name and icon: rc.135. `find_entries` field filters: rc.136; the shared entry query: rc.138. The main agent named after the assistant: rc.140. Background, batched, incremental reindex and `GET /embeddings/status`: rc.141. Published entries only in the search index, unchanged saves skipped: rc.142. Usage & Limits, limits on workflow AI steps, budget toasts, external-source answers, `MCP_TOOL_TIMEOUT_SECONDS` / `MCP_TOOL_RESULT_MAX_CHARS`, `agent:<name>` in executions and the `agent` source labelled with the assistant name: rc.146. OpenAI parameter learning: rc.147; tool calls through the Responses API when a model asks: rc.148; official OpenAI through the Responses API and no default temperature: rc.149. Bubble conversations in server threads and `?thread=` on the Ask page: rc.150. Bubble character: rc.153. Character library, agent characters, and bubble threads kept per workspace: rc.156. Character cards in the picker: rc.157. Solid backgrounds cleared from uploads, and deleting a library pack in use: rc.159. An agent's character in its Edit form: rc.160; the card's **Character** button alongside it: rc.161. Big bulk writes ask first, image-aware tagging and interrupted runs marked failed: rc.162. Every agent's threads on the Ask page, hand-offs nested: rc.163. `search_docs` / `read_doc`: rc.166. Entry `url`s in agent tools: rc.172. The bubble resting bottom-left: rc.174. The full default Marvin voice and bubble lines written from the persona: rc.180. Separate **bubble** and **Ask page** invocation sources: rc.185.

## Related

- [Marvin as an MCP server](marvin-as-mcp-server.md) — the other direction: exposing this workspace to Claude and other MCP clients.
- [Scheduled tasks](scheduled-tasks.md) — the `automation_read` tools read task history.
- [Glossary](../glossary.md) · [API reference](../api/index.md)
