# Playbooks

A **Playbook** is a written procedure an agent loads when a task calls for one: how your team writes a bench note, how to handle a refund, what a release checklist looks like. Playbooks use the open Agent Skills format (a `SKILL.md` file, optionally with reference files), so a skill from another tool imports as a Playbook and a Playbook exports as a skill folder.

Only a **published** Playbook steers an agent, and only an **Admin** can publish one.

## What it does

**What a Playbook is.** An entry of the internal `playbook` type: it is edited on its own page, never listed with your content, and has the usual drafts, history and Trash. Its fields are the standard frontmatter plus the instructions:

| Field | Notes |
|---|---|
| Name | lowercase words joined by hyphens, at most 64 characters. It is the entry's slug, so it is unique in the workspace (the Trash counts), and it is how an agent asks for the Playbook |
| Description | at most 1024 characters. The one line the agent reads in its catalog: what it does and when to use it |
| Instructions | markdown. A warning shows past 500 lines (the standard's advice), never a block |
| License, Compatibility | optional. Compatibility is at most 500 characters |
| Allowed tools | optional, see [allowed-tools](#allowed-tools) |
| Manual only | see [Manual-only](#manual-only) |

**How an agent uses one.** A run's instructions list the published Playbooks (name and description, at most 50 lines; `list_playbooks` shows the rest). When a request matches one, the agent calls `load_playbook` with its name and gets the instructions, then follows them with the tools it already has. A Playbook never gives an agent more tools or permissions. Its reference files come back as a list of paths; the agent reads one with `read_playbook_file` only when the instructions point to it. A draft, a trashed Playbook and another workspace's look the same as a made-up name: nothing to load.

A loaded Playbook stays in effect for the rest of that Ask conversation, with its current published text, and drops out if it is unpublished. Agents cannot read Playbook entries as entries (`get_entry` and `find_entries` leave them out), so a draft's text never reaches them.

### The editor and page

**Settings › AI › Playbooks** lists every Playbook outside the Trash with its status, whether it is manual-only and when an agent last used it. **New** and each row open the editor: the fields above, **Save draft**, and for an Admin **Publish** and **Unpublish**.

- **Editor**: can create Playbooks, edit drafts and send them for review. Cannot publish, schedule, or change one that is published (403 with the reason).
- **Admin and above**: publish, unpublish, edit published Playbooks, trash them.

The editor page also shows **Used recently**: the runs that loaded this Playbook (the agent, when, and a link to the conversation if it is yours; an Admin sees every link).

Under an Ask reply the **Used:** line names the Playbooks that steered it, then the tools it called.

### Import

**Import** on the Playbooks page takes a `SKILL.md` or a zip of a skill folder; **Import from GitHub** takes a link to a public skill folder or its `SKILL.md`. Either way the result is a **draft**: never published, so an Admin reads it first.

- **Files.** A zip keeps its reference files with their paths (`references/tone.md`). Files under `scripts/`, or with an executable-looking extension, are kept and flagged, and nothing ever runs them. Symlinks, `__MACOSX`, `.git` and `.DS_Store` are skipped (the review lists them).
- **Format.** Unknown frontmatter keys are kept and written back on export. `disable-model-invocation: true` becomes Manual only. Invalid YAML that real skills often contain (an unquoted colon in a description) is read leniently.
- **Name taken.** Refused with 409 instead of renaming silently, because an agent asks by name and an export must give the name back. Send another name with the import.
- **GitHub.** The link is pinned to the commit it names at import time and the commit is recorded on the draft; the review shows "Imported from repo, path, pinned to commit abc1234" with a link. Only github.com is fetched, anonymously (GitHub allows 60 requests an hour; an import takes two). A repository over 30 MB must be uploaded as a zip.
- **Limits.** 10 MB upload, 5 MB a file and 25 MB in all once unpacked, 500 entries in the zip, 100 reference files. A zip with `..`, absolute or drive paths, or a password is refused whole; nothing is extracted to disk.

Reference files are stored as assets of their own kind. They stay out of the Assets library, search, smart collections and the asset tools, and are reachable only through their Playbook.

#### The review panel

A draft that came from an import shows a review panel above the editor. It is a prompt to read the Playbook, not a security check, and says so. It lists:

- **Tools** the Playbook asks for, and which of them Marvin has (see [allowed-tools](#allowed-tools)), or that it does not narrow anything;
- **Links** it points at: URLs, and files with whether they are in the package;
- **Files** with their size and whether the instructions mention them, and **scripts** flagged;
- **Warnings** from a keyword check: credential or secret wording, token-shaped values (masked before they are stored), and wording that sends data to an outside address (at most 50 shown);
- **Skipped** files with the reason, and the frontmatter keys Marvin does not use.

The review is stored on the entry (`metadata.importReview`), so it is still there when you come back to publish.

### From an integration

An [integration](integrations.md) can ship Playbooks of its own: what makes a good Buttondown issue, how to read a failed Cloudflare Pages build, how a Mastodon post is counted. They are listed on the integration's card under **Content › Optional** with the kind "Playbook", and are never required.

- **Add** (an Admin, on the card) makes a **draft** with its reference files and a review panel that says "Installed by the Buttondown integration". Nothing is published: an Admin reads it and publishes it on this page, like any other draft. The row on the card then reads "Draft: review and publish" and links here.
- **Names.** An integration's Playbook name starts with the provider's slug (`buttondown-newsletter-issue`; underscores in the slug become hyphens, so `cloudflare_pages` gives `cloudflare-pages-failed-build`). A name already used by anything else in the workspace (a Playbook of your own, any entry, something in the Trash) is **refused, never renamed or taken over**; the card shows the reason in place of **Add**.
- **Updates.** When the integration ships a newer version, the card shows **Update**, with the same states as a workflow (update available, edited here, edited and update available). Update replaces the text and the reference files, keeps the Playbook's id and status, and puts the old version in its history. If it is published, agents use the new version at once. A Playbook you changed asks first, because Update replaces your changes. The text, the description and the reference files count as changes; the status and the history do not.
- **What it installed.** The integration's card lists its Playbooks (a draft shows as "draft"), linking here filtered to that integration (`?from=integration:<id>`). Each one is labelled "From Buttondown" on this page.
- **Removed integration.** The Playbook stays, and a published one keeps working. It is labelled "From a removed integration" and is not part of "Delete all of these". Adding the provider again re-attaches it: it is listed under the new connection's **What it installed** and loses the label. **Update** on the card records the new connection on it.
- **Agents.** A published integration Playbook is in every agent's catalog like any other, whether or not the integration is switched on. Its `allowed-tools` name Marvin's own tools and only narrow what an agent may use. An integration's actions are reached through that integration's workflows, so these Playbooks say which workflow to run by its slug.

An older Marvin that does not know the kind skips the Playbook and loads the integration's other content.

### Export

**Export** on a saved Playbook downloads a zip in the standard layout: `<name>/SKILL.md` and the reference files at their paths. It exports the saved version, not unsaved edits, in any status. Marvin-only settings travel under the frontmatter's `metadata` (`marvin-manual-only`), next to the standard `disable-model-invocation`, so other tools ignore them. Importing the zip gives the Playbook back.

### Per-agent settings

On the **Agents** page, a custom agent has a **Playbooks** section:

- **All** published Playbooks (the default) or **Only these**: a chosen set, which narrows the catalog, `load_playbook` and `read_playbook_file` for that agent. A chosen name may be a Playbook still being written.
- **Always load**: up to three Playbooks put in full in the agent's instructions for every run, without a `load_playbook` call. They must be in the chosen set, published and not manual-only (422 otherwise). The prompt preview warns when they add more than about 12,000 characters (3,000 tokens) to every run.

The built-in agents (`marvin`, `ask`, `builder`) see all published Playbooks and always-load none.

### In a workflow

A workflow's [Run an agent](workflows.md#run-an-agent) step can name up to three published Playbooks (`playbooks`), system ones included, loaded in full for that run on top of the agent's always-load ones. Naming a [manual-only](#manual-only) Playbook there loads it: the step is the person choosing it. Marvin's own `compose_entry` and `revise_entry` don't load Playbooks, so the step's message should tell the agent to write the text itself and save it with `create_draft` or `update_draft`; otherwise the Playbook's voice rules are lost.

### Done when: an agent checks its work

A Playbook can end with a **Done when** section: a `## Done when` heading (also "Done-when" or "Definition of done") and a few
short bullet points that can be checked, such as "the draft has a title, a body and at least one tag". The editor's **Add a Done
when section** button appends one.

An agent with **Check its work before finishing** on (Agents → Edit → Model and access; a workflow agent step has the same
box) checks its work when it stops calling tools, before it answers:

- Marvin looks for gaps itself, without asking the model: a tool whose last answer was an error, and a draft written in the
  run that still can't be published (what blocks it is what `create_draft` / `update_draft` report as warnings).
- Once, it asks the agent to go through the Done when items of the Playbooks in effect (always-load ones, ones the thread
  remembers, ones loaded in the run), checking each with its tools or pointing to a result, and to end its answer with a
  short "Checked:" list.

Anything left goes back to the agent and it carries on, at most twice, and only while a step of its budget is left. Gaps
still open when it answers are listed under the answer ("Still to do"). What was checked is stored with the run (AI
Executions shows it under **Checked its work**; a workflow step's output has `check`). The switch is off by default, so
nothing changes until you turn it on.

### Manual-only

A Playbook marked **Manual only** is left out of every agent's catalog and loads only when the person names it in their latest message: its name appears as whole words, in any case, with hyphens, underscores or spaces between them (`Refund Policy` and `refund_policy` name `refund-policy`; `refund-policies` does not). The agent's own output and tool results never count. A workflow's [Run an agent](workflows.md#run-an-agent) step that names it in `playbooks` loads it too, and so does a person driving the tools directly (MarvinMCP, the remote MCP server, the invoke route): `list_playbooks` shows it there with `manualOnly: true` and `load_playbook` loads it by name. An agent's own run needs the message to name it. A run that stopped to ask your approval keeps the message that started it, so naming the Playbook still works after you approve.

### allowed-tools

A Playbook can list tools in `allowed-tools` (space-separated, as the standard writes it). While it is in effect (loaded, or always-loaded) the agent can use only the tools it lists, plus the Playbook tools themselves. The agent is told which tools it is limited to when it tries another.

- **Union.** Several Playbooks in effect each add their list: the agent may use any tool any of them names. Loading a second Playbook never takes away what the first needs.
- **Capped by the agent.** The limit only removes tools. It can never give an agent a tool its own settings, role or permission matrix do not allow.
- **No Marvin tool, no narrowing.** A list that names no tool Marvin knows (a Claude Code skill's `Bash(git:*) Read`, for example) narrows nothing, so an imported skill cannot lock an agent out. Names with a qualifier (`Tool(...)`), an `mcp__server__` prefix or a `marvin_` prefix are matched to the Marvin tool; unknown names are ignored. An unrestricted Playbook loaded later does not lift an earlier limit.

The import review shows each token and whether it matched.

### Proposals

An agent that sees a correction people keep making, or a better way to do a task, can propose it instead of changing anything:

- a **new** Playbook with `create_draft` (entry type `playbook`), saved to the Inbox;
- a **change** to a published one with `propose_playbook_change`: a separate Inbox draft named `<name>-change` that holds the live content with the proposed differences and names the Playbook it replaces. Errors if the Playbook is not published or nothing differs.

The live Playbook is untouched; agents can never update, revise, archive or trash a published one, whoever they work for. An Admin reviews the draft and **publishes** it: publishing a change replaces the live Playbook's content (it keeps its identity and gets a normal history entry with the diff) and archives the change. If the Playbook was unpublished or removed in the meantime, publishing the change is refused (409); an Admin can clear its **Replaces** field to publish it as a new Playbook instead. A scheduled publish of such a stale change is skipped and logged, its schedule is cleared and the reason is kept on the draft (`metadata.scheduled_publish_failed`), so one stale draft does not stop the other scheduled entries. An agent that can draft (Editor or above, with `create_draft`) is always told about Playbooks: with some published, the catalog says when to propose one; with none yet, a short note says Playbooks exist and how to draft the first (name, description, body), so you can ask the bubble to *write a Playbook for our Bench Note voice* in a fresh workspace. An agent that can't draft gets nothing until a Playbook is published.

### Who may do what

| | Viewer / Author | Editor | Admin, Owner |
|---|---|---|---|
| Open the Playbooks page, import, export | no | yes | yes |
| Create and edit a draft | no | yes | yes |
| Publish, schedule, unpublish, edit or trash a published one | no | no | yes |

The same rule holds for AI revise and write-back (an Editor's AI operation does not write onto a published Playbook) and for workflows: a workflow step that publishes, unpublishes, archives, trashes, restores or sets data on a Playbook needs its author to be an Admin now, since a workflow runs with its author's current role.

### System Playbooks

Some procedures nobody should have to install. **System Playbooks** are written by Marvin and its plugins and offered in **every** workspace automatically: no Add, no draft, no review. They are read-only, labelled **System · Marvin**, **System · Social** or **System · <plugin>** (for example **System · S3 storage**), and updated with the release that ships them. A plugin's are removed when the plugin is uninstalled.

They are not rows in your workspace. Marvin reads them from the installed packages, so they are not in your entries, trash, history or backups; only your switches are saved, and a workspace export carries them as `systemPlaybooksOff`.

- **Where they show.** Settings › AI › Playbooks has a **System** section, grouped by label: the name, the description, a **Manual only** and an **Allowed tools** badge where they apply, a switch, **View** and **Copy**. **View** opens a read-only page with the text, its files, the version, where it comes from and where it was used lately. The integration's card says "Also gives every workspace: <name> (System Playbook, read-only)" and never offers it as an Add.
- **Who sees it.** Agents see a system Playbook like one of the workspace's own: after them in the catalog, in a chosen set only when the set names it, in an always-load list when it is not manual-only (never platform-wide), and an `allowed-tools` narrows as it does for any Playbook. A workspace's own Playbook with the same name comes first. Run traces and the use lists record it as `system:<name>` with its version.
- **Manual-only by default.** A system Playbook is manual-only unless its frontmatter says `disable-model-invocation: false`. `marvin-alt-text` is the one listed in every catalog; `social-auto-reply-rule` and `s3-workspace-bucket` load when someone names them.
- **Switching off.** An Admin switches one off for the workspace (`PUT /groups/playbooks/system/{name}`), and a platform super admin can switch one off for the whole server (**Admin › System Playbooks**). Off is absent everywhere: the catalog, `list_playbooks`, `load_playbook`, `read_playbook_file`, chosen sets, always-load lists and the tool limit. The row says **Off for this workspace** or **Off for this platform**, and an agent's settings show it as "(off)". A switch is kept by name, so it survives the plugin being uninstalled and installed again.
- **Names.** A new Playbook of your own (the editor, an import, Add on an integration card, or an agent's `create_draft`) can't take the name of a system Playbook: it is refused with "copy it instead". A Playbook you already had with that name **shadows** the system one in your workspace: the row says "Hidden: your Playbook <name> has this name".
- **Copy to customise.** **Copy** (an Admin) makes a **draft** Playbook of your own from it, with its text and files, named without the prefix (`marvin-alt-text` gives `alt-text`; a taken name is refused, never suffixed) and reviewed as "Copied from System · Marvin 1.42.0". The copy is yours: editable, exportable, with no update link. Once the copy is **published** it replaces its original in your workspace, and unpublishing or trashing it brings the original back. When the original changes later the copy shows a hint ("1.40.0 → 1.42.0", **View it**, **Mark as seen**); nothing is merged, you read the new version and edit your copy.
- **Read-only.** `propose_playbook_change` on a system Playbook, or a draft whose `replaces` names one, is refused and points to Copy.
- **Platform admin.** **Admin › System Playbooks** lists them by source with the version, the badges, how many workspaces switched each off, the server switch, and a **Couldn't load** list (a bad name, a script, over the size caps, a name another source already holds). **Admin › Plugins** shows "N system Playbooks" on a plugin's row.

A plugin declares them with SDK 0.16.0 (`playbook_blueprint(..., scope="system")` in a provider's `system_playbooks`, or a storage or AI plugin's `playbooks`; Marvin's own live in `src/marvin/system_playbooks/<area>/<name>/`). The names start with the plugin's slug and a hyphen (`s3-workspace-bucket`) or the area (`marvin-`, `social-`).

**The Rules.** Marvin checks the ones a program can (the SDK's `check_playbook(scope="system")` and Marvin's loader, which skips a bad one and lists it under Couldn't load):

1. A plugin's `guide.md` stays the reference for building workflows. A skill covers doing a job and points to it (`read_doc` the page `plugins/<provider>.md`); it never restates actions or recipes.
2. The manual explains what a feature is. A skill is a procedure (steps, checks, what a good result looks like) and links the page.
3. Workflow authoring stays with `workflow_authoring_guide` and the Builder: no "how to set up a workflow" skill, or at most 20 lines that call the guide and `draft_workflow` (a longer one is refused).
4. Instructions say who, skills say how. A system skill never sets voice or tone ("if this workspace has a voice Playbook in your list, load it") and never says who the agent is.
5. Manual-only by default (no key means manual-only); `disable-model-invocation: false` only for broadly useful ones.
6. `allowed-tools` is rarely right. It is allowed (narrowing is a safety feature) but warned about, and the admin page shows it.
7. Write it yourself: a drafting skill saves with `create_draft` / `update_draft`. `compose_entry` / `revise_entry` in `allowed-tools` is refused; in the body it is warned about.
8. Slugs only: a UUID-looking token is refused, since ids differ in every workspace.

## Where

- **Settings › AI › Playbooks** (`/workspace/settings/ai-playbooks`, Editor and above); the editor at `/new` and `/{id}`.
- **Settings › AI › Agents** for each agent's Playbooks section.
- **Settings › AI › Playbooks › System**; **Admin › System Playbooks** (super admins).
- Agent tools: `list_playbooks`, `load_playbook`, `read_playbook_file`, `propose_playbook_change`.

## API

Under `/api/groups/playbooks` (Editor and above):

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `` | The list: `entryTypeId` and items with `name`, `description`, `status`, `manualOnly`, `updatedAt`, `lastUsedAt`. Creates nothing |
| POST | `/type` | Make the `playbook` entry type (idempotent), before the first save |
| GET | `/{id}/uses` | The runs that loaded the Playbook, newest first, at most 20 |
| GET | `/{id}/export` | The skill folder as a zip |
| POST | `/import` | Multipart `file` (and optional `name`): a draft from a `SKILL.md` or zip. 201, 400, 409 or 413 |
| POST | `/import-github` | JSON `{url, name?}`: a draft from a GitHub link. 201, 400, 404, 409, 413, 429 or 502 |
| GET | `/system` | The system Playbooks with `state` (`on`, `off`, `off_server`, `hidden`, `replaced`), `label`, `version`, `manualOnly`, `allowedTools`, `suggestedCopyName` |
| GET | `/system/{name}` | One in full (`body`, `files`, `fingerprint`, `warnings`), read-only |
| GET | `/system/{name}/uses` | The runs that loaded it, newest first |
| PUT | `/system/{name}` | Admin. `{enabled}`: switch it on or off for this workspace |
| POST | `/system/{name}/copy` | Admin. `{name?}`: a draft copy. 201, 400, 409 |
| POST | `/{id}/upstream-seen` | Admin. Mark a copy's changed original as seen (204) |

`GET/PUT /api/admin/system-playbooks[/{name}]` (super admins) lists them by source with the server switch and how many workspaces switched each off, and sets the server switch.

The list's items also carry `fromIntegration` (`source`, `name`, `integrationId`, `removed`) for a Playbook an integration shipped, and null for the rest, and `copiedFrom` (`name`, `label`, `version`, `currentVersion`, `upstreamChanged`) on a copy of a system Playbook. An integration's Playbooks are added and updated through the [blueprints](blueprints.md) routes, not here.

The editor saves through the ordinary entries API (`/api/platform/entries`), so its role rules (the 403 above) apply.

## Settings

An agent's `playbooks` field (`{"names": [...] | null, "always": [...]}`) and `checkWork` (true / false, default false) on the
Agents API; a workflow agent step's `check_work`.

## Related

- [Agents and Ask](agents-and-ask.md)
- [Marvin as an MCP server](marvin-as-mcp-server.md)
- [Trash](trash.md)
