# Marvin as an MCP server

Marvin serves MCP two ways: a **remote server** built into the API, which an assistant signs in to (no token to store), and the `@inneropen/marvin-mcp` package, which exposes one workspace over stdio with tokens.

## Remote server: sign in instead of a token

**Address:** `https://api.iwobble.com/mcp` (dev: `https://api-dev.iwobble.com/mcp`). It is on when Admin → Site Settings → Remote MCP is on; **Profile → Command line & MCP** then shows the address and the steps.

**Connect:**
- **claude.ai and Claude Desktop:** Settings → Connectors → Add custom connector, paste the address, Connect.
- **Claude Code:** `claude mcp add --transport http --scope user marvin https://api.iwobble.com/mcp`, then `/mcp` → marvin → Authenticate.
- **ChatGPT:** Settings → Apps & Connectors → Create, paste the address. Developer mode gets every tool; normal mode uses only `search` and `fetch`.

The assistant opens Marvin's consent page (behind Cloudflare Access): you sign in, pick **one workspace**, and choose **Read-only** (the default) or **Read & write** (Editor or above). Each approval is a connected app, listed with Disconnect on Profile → API Tokens.

**One connector per workspace:** add `https://api.iwobble.com/mcp/w/<workspace-slug>` instead (Profile → Command line & MCP shows yours). It is a resource of its own: the consent page offers that workspace only (the form can't change it), and the token it issues works at that address and nowhere else, not at `/mcp` and not at another workspace's address, even one you belong to. A token from plain `/mcp` doesn't work there either. Use it to keep, say, Mash & Burn and Grace's site as separate connectors without picking at consent. Renaming the workspace keeps the old address working (a former slug still resolves) and the connection with it; a slug that later names a different workspace never inherits the old token. Its discovery metadata is at `/.well-known/oauth-protected-resource/mcp/w/<slug>` and answers for any well-formed slug, so it can't be used to find out which workspaces exist. A connected app on a workspace address shows "its own address" in the lists. `/mcp` works exactly as before.

**What a connection gets:** Marvin's registry tools under the same rules as the local package with a personal token (role, the workspace's "External MCP hosts" switch, Marvin's permission matrix for its main agent, the AI budget, the bulk-write gate). A Read-only connection sees and runs read tools only. On top of the registry:

| Tool | For |
|---|---|
| `create_draft`, `update_draft` | Read & write: the assistant writes the entry itself and Marvin saves it, so no AI provider of Marvin's is needed. `create_draft` takes the type's own fields (refusing unknown keys and wrong types, with the reason) and lands an inbox draft with a review link. `update_draft` changes only the fields given on an inbox, draft or needs-review entry, applied or staged for review per the workspace's approval policy. Both are shared registry tools, so Marvin's own assistant can use them too. |
| `compose_entry` | Read & write: Marvin's own AI writes a new draft from a brief, with the workspace's voice and related content. It lands in the inbox with a review link; nothing is published. |
| `search`, `fetch` | ChatGPT's connector pair: search entries, assets and resources; fetch one in full by the id search returns. |
| `show_image` | the picture itself (at most 1024 px), with its name, alt text and link, and an MCP Apps viewer (below). Without a viewer, claude.ai shows the image inside the tool step, not in the reply; ChatGPT drops image results (reported, unverified). |

**Image viewer (MCP Apps):** `show_image` names a viewer, `ui://marvin/image-viewer` (`text/html;profile=mcp-app`, in `_meta.ui.resourceUri`, plus the older flat `_meta["ui/resourceUri"]` key). A client that supports the MCP Apps extension fetches that page with `resources/read`, draws it in the conversation and hands it the tool result, so the picture appears in the reply instead of inside the tool step. The result itself is unchanged (a text block with the asset's details and the image block), so a client without the extension shows it as before. The `mcp` package here (1.28.1) has no Apps API of its own, but it passes `_meta` on tools, resources and their contents through, and the extension is only metadata plus a resource, so the server implements the spec (2026-01-26) directly: the page does the `ui/initialize` handshake, draws the first image block with the asset's alt text, sizes itself (`ui/notifications/size-changed`), follows the host's light or dark theme and opens "Open in Marvin" through the host (`ui/open-link`). It needs nothing outside the host's default sandbox (the picture arrives as a `data:` image; no network, no other origin, no library) and carries no workspace data. **Checked:** the metadata and resource through the MCP SDK's own models, and the page in a browser against a stand-in host. **Not checked:** how claude.ai or ChatGPT render it; that depends on each host honoring the extension, and `tools/list` logs whether a client advertised it (`io.modelcontextprotocol/ui`) so a real connection settles it.

Plus the seven prompts below and resources (`marvin://workspace`, `marvin://collections`, `marvin://entry-types`, `marvin://entries/{slug}`, …).

**Limits:**
- **Photos in the chat can't reach Marvin as files.** claude.ai and ChatGPT don't pass a chat's attachments to tools. Upload them in Marvin and ask the assistant to attach them, or let it send a small copy as base64 `data` to `import_asset`.
- 120 requests a minute per connection (429 with `Retry-After` beyond that).
- Sessions live in the backend's memory: a deploy ends them and the assistant starts a new one on its own.

Sign-in, tokens and the audit events are in [Sign-in and tokens](../auth-and-tokens.md#mcp-and-oauth).

## Local package (stdio, tokens)

The `@inneropen/marvin-mcp` package exposes one Marvin workspace to any MCP client (Claude Desktop, Claude Code, ChatGPT and others) over stdio.

## What it does

`marvin-mcp` is a thin bridge: it reimplements nothing and calls the Marvin API through `@inneropen/marvin-sdk`. With only a site client token it serves published content read-only. With a user token it also projects the backend's tool registry, AI operations and MCP-enabled workflows as tools, so the client's own model can act inside the workspace under your role.

!!! warning "Stale docs in the repo"
    The package `README.md` and `docs/CAPABILITY_INVENTORY.md` describe an earlier read-only, hand-wired tool set (`marvin_list_entries` and friends, no user token); this page is written from `src/`.

**Tool families** (names as the client sees them):

| Family | Needs | Comes from |
|---|---|---|
| `marvin_describe_capabilities`, `marvin_get_workspace` | site token | fixed; `marvin_get_workspace` returns workspace identity and public site settings |
| `marvin_compose_entry` | user token | fixed; `entryType`, `brief`, `assetIds` (first is the hero; only the first four go to the vision model), `modelOverride`. Creates an `inbox` draft, never publishes |
| `marvin_<tool>` | user token | every registry tool that declares the `mcp` source, whose `min_role` you meet and that Marvin's permission matrix doesn't block, fetched from `GET /api/ai/tools` at startup and invoked via `POST /api/ai/tools/{name}/invoke` with `{args}` |
| `marvin_op_<slug>` | user token | every AI operation from `GET /api/ai/operations` whose `invocation_sources` include `mcp`; input `{entityType?, entityId?, input?}`. Slugs matching `delete`, `destroy`, `remove`, `publish` or `admin` are skipped |
| `marvin_wf_<slug>` | user token (ADMIN to list) | each enabled automation whose `definition.trigger.type` is `"mcp"`; runs it as authored, no input |

Registry tools projected today: `find_entries` (the shared entry query; see [Agents and Ask → Finding entries](agents-and-ask.md#what-it-does)), `get_entry`, `list_entry_types`, `get_entry_type`, `get_entity_history`, `search_content`, `workspace_overview`, `search_docs`, `read_doc` (this manual, see [Agents and Ask](agents-and-ask.md#what-it-does)), `view_image`, `read_attachment`, `list_collections`, `get_collection`, `get_collection_entries`, `list_resources`, `get_resource`, `list_tags`, `list_assets`, `get_asset`, `import_asset`, `revise_entry`, `add_embed` (staged as a suggestion), `preview_embed`, `attach_tag`/`detach_tag` (a call too big to run without asking — more than 20 links, or more than 5 tags across more than one target — is refused over MCP and writes nothing; narrow it or run it from the Ask page), `attach_asset`/`detach_asset`, `attach_resource`/`detach_resource`, `add_to_collection`/`remove_from_collection`, `archive_entries` (retire entries; a call that includes a published entry is refused over MCP, which cannot ask first), `trash_entries` (delete entries, assets and resources to the [Trash](trash.md), restorable; the same refusal for a published entry or an asset or resource a site shows), `restore_entries` (take them back out of the Trash), `list_events`, `describe_event` ("what happens when X?": give an event type or a hint such as `publish`; it answers what sends the event, everything that reacts to it, including what an integration installed and Marvin's built-in reactions, the events it leads to and is caused by, and when it last happened, from the same lookup as the Events pages; workspace events only, platform events for a super admin), `list_scheduled_tasks`, `get_scheduled_task_history`, `list_workflows`, `get_workflow`, `workflow_authoring_guide` (how to write a workflow, and this workspace's names), `draft_workflow` (create a workflow, switched off, from a checked definition; returns `editLink`), `update_workflow_draft` (revise one while it is switched off), `run_workflow` (running workflows is Ask first for Marvin, so a direct call is refused; run it from the Ask page or an agent conversation), `list_ai_executions`, `get_ai_execution`, `get_ai_settings`, `list_agents`, `suggest_agent`, `run_agent`. Writes need EDITOR or higher, and `list_scheduled_tasks`, `get_scheduled_task_history`, `list_workflows`, `get_workflow`, `workflow_authoring_guide`, `draft_workflow`, `update_workflow_draft`, `run_workflow`, `describe_event` and `get_ai_settings` need ADMIN, so a lower role doesn't see them; `compose_entry` in the registry does not declare `mcp`, so the fixed `marvin_compose_entry` is the only compose tool. Operations today: `generate-summary`, `generate-tags`, `improve-writing`, `generate-alt-text`, `describe-image`, `enrich-resource-metadata`, `answer-workspace-question` (AUTHOR+) and `classify-form-submission` (EDITOR+).

**Resources** (site token, published content): `marvin://capabilities`, `marvin://workspace`, `marvin://workspace/site`, `marvin://entries/{slug}`, `marvin://entry-types`, `marvin://collections`, `marvin://collections/{slug}`. `marvin://resources` and `marvin://resources/{slug}` (and the `list_resources` / `get_resource` tools) need a user token (a CLI login): the publishing API no longer serves resources or assets, so a site token alone doesn't offer them, and asset listing (`list_assets`, `get_asset`) is a user-token tool too.

**Prompts:** `create_site_page`, `prepare_release_update`, `audit_content_model`, `review_collections`, `review_assets`, `review_resources`, `review_workspace_structure`. They all instruct the model to draft, never to publish.

**Backend policy.** Every platform call is sent with `source: "mcp"`. The backend allows it only if the tool or operation declares `mcp` in its sources *and* the workspace's `invocation_sources` policy has not set `mcp` to `false`, then applies `min_role` from your token. A direct tool call (`marvin_<tool>`) stands in for the workspace's `marvin` agent, so it follows Marvin's permission matrix (Settings → AI → Agents → Marvin → **Permissions**) the way an agent run does: a tool Marvin may not use is refused ("… is switched off for Marvin in this workspace") and is not listed, and a tool that is Ask first for Marvin — `run_workflow` today — is refused too, because a direct call cannot pause for approval ("… run it from the Ask page or an agent conversation, where it can be approved"). An allowed tool still meets the bulk-write and ask-first refusals below. A refusal answers 200 with `{error, tool, category, policy, reason}` and runs nothing; MarvinMCP reports it as a tool error. Resulting AI executions carry `source: "mcp"` in the executions log. `run_agent` lets an MCP client converse with a named workspace agent. It answers in the **Professional** tone, which leaves the character out, unless the call passes `tone` (a tone slug such as `auto` or `playful`, which bring in the agent's own Character or else the workspace's) or the agent has a default tone of its own. There is no thread to pause on, so a tool marked Ask first in that agent's matrix is not bound (for `marvin` that includes running workflows and external MCP writes), and a call that would ask first anyway (a big bulk write, archiving a published entry) is refused. The workspace Approval Mode still decides whether AI-generated content is applied or staged as a suggestion. A tool that calls the workspace's AI provider (`search_content`, `revise_entry`, `view_image`, `run_agent`) is refused with 429 and the limit's message once the workspace is over its daily request or monthly cost limit (AI Settings → Usage & Limits); the other tools keep working. These gates live in one place, `services/ai/tool_gateway.py`, which the remote MCP server will use too.

## Where

- Package: `@inneropen/marvin-mcp` (source at `MarvinMCP/`, binary `marvin-mcp`). Transport: stdio only.
- Credentials: `~/.marvin/credentials.json`, written by `marvin login --site-token <token> --workspace <slug>` (the CLI), shape `{activeWorkspace, workspaces: {<slug>: {siteToken, userToken}}}`.
- Workspace side: **AI Settings** (`/workspace/settings/ai-workflow`, Invocation Sources → **External MCP hosts**) and **AI Executions** (`/workspace/settings/ai-executions`).

## How to use

1. Get a site client token for the workspace; for authoring, also a user token (a platform API token for your user).
2. Add the server to your client. Claude Desktop (`claude_desktop_config.json`) and Claude Code (`.mcp.json` in the project) share this shape:

```json
{
  "mcpServers": {
    "marvin": {
      "command": "npx",
      "args": ["-y", "@inneropen/marvin-mcp"],
      "env": {
        "MARVIN_API_URL": "https://marvin.example.com",
        "MARVIN_WORKSPACE_SLUG": "my-workspace",
        "MARVIN_SITE_CLIENT_TOKEN": "<API client token>",
        "MARVIN_USER_TOKEN": "<personal API token>",
        "MARVIN_MCP_LOG_LEVEL": "warn"
      }
    }
  }
}
```

   Claude Code one-liner: `claude mcp add marvin -e MARVIN_API_URL=... -e MARVIN_WORKSPACE_SLUG=... -e MARVIN_SITE_CLIENT_TOKEN=... -e MARVIN_USER_TOKEN=... -- npx -y @inneropen/marvin-mcp`.
3. Alternatively run `marvin login` and omit the token env vars: stored credentials win over env vars for the active workspace, so a fresh login takes effect even if the client cached an old token.
4. Restart the client and ask it to call `marvin_describe_capabilities`. Startup pre-fetches the operation, tool and workflow lists; if the backend is unreachable, reads and compose still register and the rest is skipped with a warning on stderr.
5. To expose a workflow, set its trigger type to `mcp` and enable it; it appears as `marvin_wf_<slug>` on the next server start.

!!! note
    The server announces itself as version `0.1.0` in the MCP handshake (`src/server.ts`) although the package is `1.1.0`.

## API

The bridge calls these backend routes; see [`../api/`](../api/index.md).

| Route | Used for |
|---|---|
| publish SDK (`site client token`) | workspace, site, entries, collections (the publishing API has no asset or resource routes) |
| platform SDK (`user token`) | `marvin://resources`, `marvin://resources/{slug}` and the asset and resource tools |
| `GET /api/ai/tools`, `POST /api/ai/tools/{name}/invoke` | registry projection and calls |
| `GET /api/ai/operations`, `POST /api/ai/operations/{slug}/execute` | operation projection and calls |
| `POST /api/ai/compose-entry` | `marvin_compose_entry` |
| `GET /api/automations`, `POST /api/automations/{id}/run` | `marvin_wf_*` (list is admin-gated; a 403 degrades to no workflows) |

## Settings

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `MARVIN_API_URL` | yes | — | base URL of the Marvin API |
| `MARVIN_WORKSPACE_SLUG` | yes, unless `activeWorkspace` is in the credentials file | — | workspace to expose |
| `MARVIN_SITE_CLIENT_TOKEN` | yes, unless stored by `marvin login` | — | read access to published content |
| `MARVIN_USER_TOKEN` | no | — | enables platform tools (registry, operations, compose, workflows) |
| `MARVIN_MCP_READ_ONLY` | no | `true` | parsed into config but not consulted by any capability today; the user token, not this flag, decides whether write tools exist |
| `MARVIN_MCP_LOG_LEVEL` | no | `warn` | `silent`, `error`, `warn`, `info`, `debug` (stderr) |

## Since

`@inneropen/marvin-mcp` 1.1.0 against Marvin 1.0.0-rc.137. Backend gating of `invocation_sources` per call: commit `09feb42` (per `tasks/marvin-assistant-architecture.md`). Direct tool calls following Marvin's permission matrix, and `GET /api/ai/tools` leaving out what it blocks: unreleased.

## Related

- [Agents and Ask](agents-and-ask.md) — the same registry and policy seen from inside the workspace, and how Marvin connects to *other* MCP servers.
- [Scheduled tasks](scheduled-tasks.md) — `marvin_list_scheduled_tasks` and `marvin_get_scheduled_task_history` read them.
- [Glossary](../glossary.md) · [API reference](../api/index.md)
