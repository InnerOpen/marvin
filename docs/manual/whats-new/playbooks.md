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

### Export

**Export** on a saved Playbook downloads a zip in the standard layout: `<name>/SKILL.md` and the reference files at their paths. It exports the saved version, not unsaved edits, in any status. Marvin-only settings travel under the frontmatter's `metadata` (`marvin-manual-only`), next to the standard `disable-model-invocation`, so other tools ignore them. Importing the zip gives the Playbook back.

### Per-agent settings

On the **Agents** page, a custom agent has a **Playbooks** section:

- **All** published Playbooks (the default) or **Only these**: a chosen set, which narrows the catalog, `load_playbook` and `read_playbook_file` for that agent. A chosen name may be a Playbook still being written.
- **Always load**: up to three Playbooks put in full in the agent's instructions for every run, without a `load_playbook` call. They must be in the chosen set, published and not manual-only (422 otherwise). The prompt preview warns when they add more than about 12,000 characters (3,000 tokens) to every run.

The built-in agents (`marvin`, `ask`, `builder`) see all published Playbooks and always-load none.

### Manual-only

A Playbook marked **Manual only** is left out of every agent's catalog and loads only when the person names it in their latest message: its name appears as whole words, in any case, with hyphens, underscores or spaces between them (`Refund Policy` and `refund_policy` name `refund-policy`; `refund-policies` does not). The agent's own output and tool results never count. Agents run from MCP or the API, which have no such message of their own, never load one. A run that stopped to ask your approval keeps the message that started it, so naming the Playbook still works after you approve.

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

The live Playbook is untouched; agents can never update, revise, archive or trash a published one, whoever they work for. An Admin reviews the draft and **publishes** it: publishing a change replaces the live Playbook's content (it keeps its identity and gets a normal history entry with the diff) and archives the change. If the Playbook was unpublished or removed in the meantime, publishing the change is refused (409); an Admin can clear its **Replaces** field to publish it as a new Playbook instead. A scheduled publish of such a stale change is skipped and logged, its schedule is cleared and the reason is kept on the draft (`metadata.scheduled_publish_failed`), so one stale draft does not stop the other scheduled entries. The agent's instructions say when to propose only when the workspace already has a published Playbook and the agent can draft.

### Who may do what

| | Viewer / Author | Editor | Admin, Owner |
|---|---|---|---|
| Open the Playbooks page, import, export | no | yes | yes |
| Create and edit a draft | no | yes | yes |
| Publish, schedule, unpublish, edit or trash a published one | no | no | yes |

The same rule holds for AI revise and write-back (an Editor's AI operation does not write onto a published Playbook) and for workflows: a workflow step that publishes, unpublishes, archives, trashes, restores or sets data on a Playbook needs its author to be an Admin now, since a workflow runs with its author's current role.

## Where

- **Settings › AI › Playbooks** (`/workspace/settings/ai-playbooks`, Editor and above); the editor at `/new` and `/{id}`.
- **Settings › AI › Agents** for each agent's Playbooks section.
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

The editor saves through the ordinary entries API (`/api/platform/entries`), so its role rules (the 403 above) apply.

## Settings

An agent's `playbooks` field (`{"names": [...] | null, "always": [...]}`) on the Agents API. Nothing else is configurable.

## Related

- [Agents and Ask](agents-and-ask.md)
- [Marvin as an MCP server](marvin-as-mcp-server.md)
- [Trash](trash.md)
