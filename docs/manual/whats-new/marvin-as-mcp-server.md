# Marvin as an MCP server

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

Registry tools projected today: `find_entries` (the shared entry query; see [Agents and Ask → Finding entries](agents-and-ask.md#what-it-does)), `get_entry`, `list_entry_types`, `get_entry_type`, `get_entity_history`, `search_content`, `workspace_overview`, `search_docs`, `read_doc` (this manual, see [Agents and Ask](agents-and-ask.md#what-it-does)), `view_image`, `list_collections`, `get_collection`, `get_collection_entries`, `list_resources`, `get_resource`, `list_tags`, `list_assets`, `get_asset`, `import_asset`, `revise_entry`, `add_embed` (staged as a suggestion), `preview_embed`, `attach_tag`/`detach_tag` (a call too big to run without asking — more than 20 links, or more than 5 tags across more than one target — is refused over MCP and writes nothing; narrow it or run it from the Ask page), `attach_asset`/`detach_asset`, `attach_resource`/`detach_resource`, `add_to_collection`/`remove_from_collection`, `archive_entries` (retire entries; a call that includes a published entry is refused over MCP, which cannot ask first), `trash_entries` (delete entries, assets and resources to the [Trash](trash.md), restorable; the same refusal for a published entry or an asset or resource a site shows), `restore_entries` (take them back out of the Trash), `list_events`, `describe_event` ("what happens when X?": give an event type or a hint such as `publish`; it answers what sends the event, everything that reacts to it, including what an integration installed and Marvin's built-in reactions, the events it leads to and is caused by, and when it last happened, from the same lookup as the Events pages; workspace events only, platform events for a super admin), `list_scheduled_tasks`, `get_scheduled_task_history`, `list_workflows`, `run_workflow` (running workflows is Ask first for Marvin, so a direct call is refused; run it from the Ask page or an agent conversation), `list_ai_executions`, `get_ai_execution`, `get_ai_settings`, `list_agents`, `suggest_agent`, `run_agent`. Writes need EDITOR or higher, and `list_scheduled_tasks`, `get_scheduled_task_history`, `list_workflows`, `run_workflow`, `describe_event` and `get_ai_settings` need ADMIN, so a lower role doesn't see them; `compose_entry` in the registry does not declare `mcp`, so the fixed `marvin_compose_entry` is the only compose tool. Operations today: `generate-summary`, `generate-tags`, `improve-writing`, `generate-alt-text`, `describe-image`, `enrich-resource-metadata`, `answer-workspace-question` (AUTHOR+) and `classify-form-submission` (EDITOR+).

**Resources** (site token, published content): `marvin://capabilities`, `marvin://workspace`, `marvin://workspace/site`, `marvin://entries/{slug}`, `marvin://entry-types`, `marvin://collections`, `marvin://collections/{slug}`, `marvin://resources`, `marvin://resources/{slug}`.

**Prompts:** `create_site_page`, `prepare_release_update`, `audit_content_model`, `review_collections`, `review_assets`, `review_resources`, `review_workspace_structure`. They all instruct the model to draft, never to publish.

**Backend policy.** Every platform call is sent with `source: "mcp"`. The backend allows it only if the tool or operation declares `mcp` in its sources *and* the workspace's `invocation_sources` policy has not set `mcp` to `false`, then applies `min_role` from your token. A direct tool call (`marvin_<tool>`) stands in for the workspace's `marvin` agent, so it follows Marvin's permission matrix (Settings → AI → Agents → Marvin → **Permissions**) the way an agent run does: a tool Marvin may not use is refused ("… is switched off for Marvin in this workspace") and is not listed, and a tool that is Ask first for Marvin — `run_workflow` today — is refused too, because a direct call cannot pause for approval ("… run it from the Ask page or an agent conversation, where it can be approved"). An allowed tool still meets the bulk-write and ask-first refusals below. A refusal answers 200 with `{error, tool, category, policy, reason}` and runs nothing; MarvinMCP reports it as a tool error. Resulting AI executions carry `source: "mcp"` in the executions log. `run_agent` lets an MCP client converse with a named workspace agent; there is no thread to pause on, so a tool marked Ask first in that agent's matrix is not bound (for `marvin` that includes running workflows and external MCP writes), and a call that would ask first anyway (a big bulk write, archiving a published entry) is refused. The workspace Approval Mode still decides whether AI-generated content is applied or staged as a suggestion.

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
| publish SDK (`site client token`) | workspace, site, entries, collections, assets, resources resources |
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
