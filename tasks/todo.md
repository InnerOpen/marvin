# Marvin Agents v1 (2026-09-13)

Design: brain vault `20-Projects/Marvin Agents.md`. v1 scope (Jared, 2026-09-13): agents as first-class
workspace objects, kinds `persona` + `model`, seeded system agents, bubble picker, MCP projection.
First user agent: `workshop` (read-only, brand voice) for `mash-burn-co`. Threads/memory = v2, workflow kind = v3.

## Plan
- [x] Model `WorkspaceAgentModel` (`workspace_agents`): group_id, slug, name, description, kind, system_prompt,
      model_override, tool_allowlist (JSON list), default_register, min_role, sources (JSON), enabled, created_by.
      Unique (group_id, slug). Alembic migration via `task py:migrate`.
- [x] Schemas `AgentCreate/Update/Read` (camelCase wire), kind Literal["persona","model"].
- [x] Repo registered in `get_repositories` (mirror webhooks/api_clients).
- [x] Routes `/api/ai/agents`: list (merges **virtual system agents** `marvin`, `ask`, `chat` — no rows, no seeding),
      get, create/patch/delete (role-gated), `POST /agents/{slug}/run` (AIAgentRequest body).
- [x] Execution: refactor `run_agent` so the loop tail is shared; persona = system prompt + register + context,
      tools = `_build_agent_tools` ∩ allowlist; model kind = plain completion. Execution row `agent:<slug>`.
- [x] MCP projection: registry tools `list_agents` + `run_agent(agent, message, history?)` (source mcp) so
      MarvinMCP/n8n can converse with any agent with zero MCP changes.
- [x] Frontend bubble: `/agents` (list) + `/use <slug>` (switch; persisted in localStorage) → runAgent posts to
      `/agents/{slug}/run`; default stays `marvin`.
- [x] Backup export/import carries `workspace_agents`.
- [x] Tests: schema validation, system agents listing, allowlist filtering, role gates, run via ScriptedProvider.
- [x] pytest (full suite) + Biome/astro green; committed `75d4410f`; pushed; CI green; rolled out 2026-09-13 22:10 UTC (migration applied, routes verified).
- [ ] Seed `workshop` on mash-burn-co after rollout (script for Jared to run as admin).

- [x] Added after the n8n settings review: per-agent `allow_writes` (default off) on top of the allowlist; caller still needs AUTHOR+.

## RAG vocabulary + workspace overview (2026-09-13, after the image fix)
Jared asked Chat and workshop "summary of what's in the RAG": Chat guessed Red/Amber/Green; workshop keyword-searched "RAG".
- [x] `workspace_preamble(name, tool_names)` — injected first in `_run_agent_core` for every persona run: which workspace,
      what the content is, that "the RAG / knowledge base / index" means it, and which bound tool answers which question.
- [x] `workspace_overview` read-only tool (library_read): entries by type+status, collections, assets, resources, tags, index coverage.
      `ask` may use it (allowlist + prompt updated).
- [x] `model_agent_system_prompt()` shared by the agent `model` kind and `/chat`: names the RAG synonyms, says it can't see them,
      points to Ask/Marvin instead of guessing.
- [x] Tests: registration/category, preamble content + tool gating, ask allowlist, model prompt, DB-backed overview counts.
- [x] Full suite green; `7ab55c2d` pushed; backend rolled out 2026-09-13; overview verified in the pod (62 entries / 18 collections / 53 assets, index coverage per type). Jared to re-ask the RAG question.

## Act-don't-announce + MCP routing + Ask link (2026-09-13, later)
- [x] Loop nudge for deferrals (once); tests for nudge/once/no-tools/regex.
- [x] Preamble: act-don't-announce + connected MCP servers list.
- [x] Sidebar Ask quick link (top group), Settings active-state excludes it.
- [x] `699540fd` built; backend + frontend rolled out 2026-09-13. Jared re-asked: worked (2026-09-13).
- [x] MCP hints (`8929438c`): client keeps readOnlyHint/destructiveHint; rows mcp_read / mcp / mcp_destructive; discovered tools in catalog + permissions; server test returns hints. Rolled out 2026-09-13; verified in the pod.
- [x] cloudflare-mcp: token (iwobble account) lacked user:read/account:read scope; Jared fixed the scopes 2026-09-13 — tools/list now returns docs, search, execute.

## Review
- Shipped v1 as designed plus `allow_writes` (from the n8n settings review). Caller-role bound: an agent never exceeds the user.
- Kept `/api/ai/agent` byte-for-byte in behaviour by extracting its tail into `_run_agent_core`; named agents reuse it.
- Deliberate v1 limits: `run_agent` (MCP) binds registry tools only (no AI ops / external MCP); no threads, so no "ask first".
- Gotchas: perl `s|…|…|` with `|`/`@` inside replacements mangled three edits (use Python for multi-line code edits);
  Pydantic v2 validators can't be shared by attribute assignment (define per class); bare `python -c` imports hit the
  dev Postgres driver — verify via pytest; the venv lacks psycopg2 so migrations are hand-written here.
- Next: allow/block permission matrix with tool categories; seed `workshop` (admin script ready).

# Marvin Agents v1.5 — permission matrix + admin pages (2026-09-13, "ok" from Jared)

Three pieces: (1) backend policy model + matrix, (2) `ai-agents` management page, (3) `ai-ask` becomes the
agent chat page. Ask-first stays v2 (threads).

## Plan
- [x] Tool categories: `services/ai/tools/categories.py` (id, label, writes) + name→category map; `ToolSpec.category`
      resolved via helper (no edits to the builtins). AI ops → `ai_ops`, external MCP → `mcp`.
- [x] Agent `tool_policy` JSON (`{category|tool: allow|block}`) — model column + migration, schema, exporter/loader.
- [ ] Service: `resolve_policy(spec, name, category, read_only, role)` → allow|block + reason; `_restrict_tools` uses it
      (allowlist ∩ policy; write categories default to `allow_writes`; role still caps).
- [x] API: `GET /api/ai/agents/catalog` (categories + tools + ops), `GET /api/ai/agents/{slug}/permissions` (effective
      matrix for the caller). Tests.
- [x] Frontend `workspace/settings/ai-agents.astro`: list, create/edit (all fields), matrix (group default + per-action
      Allow/Block), delete; built-ins read-only. Nav entry.
- [x] Frontend `ai-ask.astro` rework: agent picker (default `ask`), transcript + history, register toggle, citations
      for `ask` (operation path), tools-used for others, reindex kept, "manage agents" link. Nav label → "Ask".
- [x] Bubble: `/agents` shows read-only/rw (allowWrites); effective matrix lives in Ask's Tools panel.
- [x] Image attachments: Ask keeps the attachment for the whole conversation (chip shown once); new read-only
      `view_image` tool (library_read) describes from pixels via the vision model, persisting only the execution row —
      read-only agents (workshop) can now answer "what is this?" without `describe-image`'s write-back.
- [x] Biome/astro check + full pytest green; `de56ba94` pushed; CI green; backend + frontend rolled out 2026-09-13 22:45 UTC; migration + routes + pages verified.

## Review
- Matrix is data-driven (categories.py + registry flags); the caller-role cap is enforced in resolve_policy, not the UI.
- Kept `ask` on the operation path in the chat page so citations stay exact; other agents use the run endpoint.
- Gotchas: SDK `assets.upload` requires `{slug, name}`; Astro scoped styles need `:global()` for innerHTML-rendered matrix rows; roll out BOTH deployments.
- Deferred: ask-first (needs threads), provider breadth adapter, extra operations (moderation, image/audio/video).

# Marvin Agents v2 — threads, live steps, ask-first (2026-09-14, plan approved)

Substrate first (server-side thread), then the two features that need it. Threads own-only (admins see all); Ask page only;
no token streaming (providers are sync). Each slice committed + rolled out on its own.

## Slice A — threads
- [x] Models `ai_threads` / `ai_thread_messages` (+ status/pending_json now, for C) + migration `f7b3c4d5e6a8` (up/down/up verified on SQLite).
- [x] Service `services/ai/threads.py`: resolve/create, history_rows, append_turn (truncated results; names only when log_outputs off), extract_sources, touch.
- [x] Controller: `AIAgentRequest.thread_id` ("new" opens, id continues, omitted = stateless); runs persist both turns, return `threadId` + `sources`; `GET/GET one/PATCH/DELETE /threads`.
- [x] Frontend: Ask page uses `threadId` (Threads panel: list/reopen/rename/delete); `ask` routed through `/agents/ask/run`, citations from the `search_content` step.
- [x] Tests `tests/test_ai_threads.py` (10, db_session); full suite green; Biome + astro clean; `49d1aae1` pushed, Docker Build green, both deployments rolled out 2026-09-14 ~00:50 UTC.

## Slice B — live steps
- [x] `run_agent_loop(on_event=)` (thinking / tool_call / tool_result; a raising listener never kills a run); `services/ai/run_progress.py` (process-local, owner-scoped, cap 100 + 10-min TTL); `client_run_id` + `GET /agents/runs/{id}/progress`.
- [x] Ask page: placeholder bubble with a step timeline polled every 700 ms, replaced by the answer; tests in test_agent_loop + test_run_progress.

## Backlog (from Jared, 2026-09-13)
- [ ] **Custom tones**: the three registers (auto / professional / playful) are code (`REGISTERS` + `_register_clause`);
      let a workspace define its own named tones (label + voice instructions) and pick them in Ask / agents / the bubble.

## Slice D — Marvin as router (hand-offs + referrals) — built 2026-09-30
- [x] `ToolContext.depth/source/delegate/referrals`; `agents_run.writes=False`; `suggest_agent` (agents_read, runs nothing);
      `run_agent` prefers `ctx.delegate` at depth 0, standalone MCP/API path returns `referrals` and binds `suggest_agent`.
- [x] `AgentSpec.handoff_hint` (+row/schema/seed/`ask` hint); `default_policy("agents_run")` = allow only for system `marvin`
      ("router default" / "hand-offs are off unless allowed"); `roster_block()` → HANDOFF_RULES or REFERRAL_RULES.
- [x] Threads: `parent_thread_id` (SET NULL, indexed), `child_thread_for`, `list_threads(include_children)` (`GET /threads?children=true`),
      `extract_handoffs`. Migration `a1c9d4e7f2b3` (batch mode, up/down/up verified on a fresh SQLite).
- [x] Controller: `_bind_agent_tools(depth)` → (tools, ctx), `run_agent` skipped at depth>0; `_run_agent_core(ctx, on_event,
      parent_thread_id, execution_meta)` appends the roster, opens a router thread before the loop (discarded if the run fails
      with no turns), hangs `_delegate_runner` on the ctx; responses + turn meta carry `handoffs`/`referrals`; child executions
      carry `parent_execution_id`/`parent_thread_id`; child max_steps 6 (cap 8); child events forwarded with `via`.
- [x] Frontend: `aiAgents.ts` types (Handoff/Referral/via/children); Ask page "Handed off: X ↗" (opens the child = `/use`
      continuation) and "Suggests asking X — reason · Continue →" (pre-fills, never sends); nested live steps "Asked <agent> …";
      Agents form "Hand off when…".
- [x] Tests: test_agents (+11), test_ai_threads (+4), test_agent_loop (+1), new test_agent_handoff (13). Full suite green.
- [x] Rolled out 2026-10-01 ~01:56 UTC (`2320057f`; Test Suite + Docker Build green first); migration applied on the pod; in-pod
      checks: head `a1c9d4e7f2b3`, columns + FK present, marvin `agents_run` allow / workshop block, roster rendered. Brain updated.
- [x] Live verification 2026-10-01: referral + Continue → (13:24–13:25 UTC), Marvin → workshop hand-off (13:52 UTC, after `fc4c1ae4`
      tightened the rules): child thread + `parent_execution_id` + `handoffs` meta all present. UI footer/child continuation: Jared's eyes.

## Slice C — ask first (done 2026-10-01)
- [x] `PolicyValue` gains `ask`; `resolve_policy` + role cap; `AgentTool.requires_approval`; loop pends ask calls, `ResumeState`; serialize/deserialize messages.
- [x] `_finish_agent_run` / `_park_agent_run` tails; awaiting_approval on thread/execution; `POST /threads/{id}/resume`; events approval_requested/granted/rejected (out of `_NO_EMITTER`).
- [x] Defaults: custom agents with writes on → every write category "Ask first"; Marvin asks for `automation_run`/`mcp`/`mcp_destructive`, allows the other writes. No thread (bubble, MCP, hand-off child) → ask = not bound.
- [x] New message on a parked thread = deny pending + clear + run (`PARKED_THREAD_ON_NEW_MESSAGE`, "reject" → 409 kept in code).
- [x] Migration `b2d5e8f1a3c4`: `ai_threads.status` String(16) → String(32) ("awaiting_approval" is 17 chars; Postgres would reject the first park).
- [x] Frontend: matrix "Ask first" (amber); approval card on Ask (checkbox per call, Approve selected / Deny all, replays on reopen, greys on a new message); live steps show waiting/declined rows; executions chip.
- [x] Tests: loop pend/resume/deny/re-park + serializers; park/pending/clear + column width; policy defaults; `tests/test_agent_approval.py` (controller park/resume/abandon).
- [ ] Rollout + pod check (see plan step 3–4).

### Follow-ups
- **C2** — carry a specialist's ask up to Marvin: a hand-off child that hits an ask-first tool returns "awaiting" from `run_agent`; the parent parks with a nested record; resume finishes the child first, feeds its answer back as the tool result, then continues Marvin. Design only.
- **Marvin-first picker** (separate commit): Ask page picker — Marvin first and default; then the workspace's agents; Ask and Chat under "Built-in" at the bottom (Chat hidden when the default model supports tools). No backend change.

# Trash — reversible delete (2026-10-01, Jared: "add that feature to todos")

Asked to delete inbox entries, an agent had no delete tool and staged no-op `revise_entry`
suggestions ("Deleted test inbox entry.") on 7 newsletter signups instead. Trash gives "delete" a
real, reversible home; only an admin empties it. Tool name is open (doesn't have to be `trash_entry`).

## Plan
- [ ] Entry status `trashed` + a system collection **Trash** 🗑️ in `WORKFLOW_COLLECTIONS` (smart on status, locked,
      internal; after Archive). Record the previous status + who/when in `metadata_json` so Restore returns it.
- [ ] Trashed entries hidden everywhere: publish API, search/embeddings, agent read tools, non-system collections.
      Tests per read path (a leak here is the real risk).
- [ ] Agent tool to move entries to Trash (non-destructive → no ask-first). `revise_entry` description: not for
      deleting, use the trash tool. Test: an agent asked to delete calls the trash tool, not `revise_entry`.
- [ ] Trash page/collection view: list with who/when, untick to keep, **Restore** and **Empty trash** (hard delete,
      workspace OWNER/ADMIN only). Events for trashed / restored / purged.
- [ ] Optional: system scheduled task to empty items trashed > 30 days (like `prune_scheduled_task_executions`).
- [ ] Build on the dev instance (dev.admin.iwobble.com) first — touches every content read path.

# Dev instance + Postgres (2026-10-01, Jared: "add that plan to the todos")

Someone else (Grace) now uses the live instance, so changes need somewhere to land before production. And
production's SQLite-on-NFS is the known weak point (the 2026-09-11 502s; backend pinned to one replica).

## Plan
- [ ] **Image tags first:** production tracks the moving `:develop` tag, so a dev instance on `:develop` would run the
      same code as prod. Dev follows `:develop`; production pins a release tag (CI already cuts `1.0.0-rc.N`).
      Promotion = bump prod's tag.
- [ ] **Postgres on the cluster:** install the CloudNativePG operator (OperatorHub); one small single-instance
      `Cluster` per environment. (No Postgres on ocp4 today — only Beaker's MariaDB.)
- [ ] **Chart:** wire `dbEngine: postgres` to the app's `POSTGRES_SERVER/PORT/USER/PASSWORD/DB` (Secret from the CNPG
      cluster). Keep the `marvin-data` PVC — it also holds uploaded assets; only the DB moves. Allow
      `replicaCount > 1` only then (and only once assets are on shared/object storage).
- [ ] **`marvin-dev` namespace:** Helm release on Postgres, `values-dev.yaml`, `:develop` tag, `pullPolicy: Always`.
- [ ] **Hostnames:** `dev.admin.iwobble.com` + `dev.api.iwobble.com` as Public Hostnames on the existing cloudflared
      tunnel → `marvin-dev` services (cross-namespace service DNS). Dev `noindex`/not for real users.
- [ ] **Full SQLite → Postgres data copy:** every table, not just workspace content (users, API clients, tokens,
      secrets, preferences, event/execution logs too). Create the schema with Alembic on Postgres, then copy
      table by table (pgloader, or a SQLAlchemy copy script in `scripts/`); per-table row counts must match.
      Rehearse on dev from a copy of the production file, never the live one.
- [ ] **Backups:** CNPG scheduled backups (base backup + WAL) to storage off the cluster's NFS, a tested restore,
      and keep Marvin's own backup export as a second, engine-independent copy. Check what backs up the
      production SQLite file *today* before touching it.
- [ ] **First feature through dev:** Trash (above).
- [ ] **Production cutover (planned downtime):** stop the backend → copy SQLite → prod Postgres → switch `dbEngine` →
      verify → pin release tag.
- [ ] **SQLite retired** (Jared: "not using sqlite"): no environment runs on SQLite after the cutover — dev and prod both
      Postgres, `values-iwobble.yaml` drops `dbEngine: sqlite`; the `.db` file leaves `marvin-data` (assets stay). The old `.db` is kept only
      as a cold, read-only copy for a set period, then deleted. (Local dev/tests may keep SQLite.)

# Square integration — sell artwork from the site (2026-10-02, Jared: "create a Square integration")

Goal: chosen `artwork` entries get a Buy button → Square hosted checkout → back to the site → the artwork flips to
sold. Square Catalog item with inventory 1, so an in-person card-reader sale at a show marks it sold too.
Research (2026-10-01): Square over Stripe — Grace already has an active Square seller account (readers); one
inventory for online + shows. PayPal (reusable links, RSA-signed webhooks) and Shopify (5% Starter fee) ruled out.

Shape: the provider is a thin Square API wrapper; Marvin **workflows** do the wiring (publish → create listing →
store ids; Square webhook → find entry by stored id → mark sold → close link → rebuild site). Same pattern as the
Buttondown loop, so every core piece below is reusable beyond Square.

## Core gaps (Marvin + SDK) — each reusable, each with tests
Done 2026-10-02 (local, not pushed): SDK `b9b33c8`; Marvin `cb4c520f` (http put/delete), `e906102a` (square signature scheme +
migration `c4e8a2f6b9d1`), `e0c5f0b4` (set_data), `ad70f341` (integration step). Full suite green. Builder learned both
new steps — it used to drop unknown step kinds on save and default unknown entry ops to "Publish".
- [x] **Incoming-webhook signature schemes:** `signature_scheme` on incoming webhooks (`hmac_sha256_hex_body` = today,
      `square` = base64 HMAC-SHA256 over notification URL + raw body, header `x-square-hmacsha256-signature`;
      leave room for `stripe`). Migration + schema + admin field. The notification URL must be the public one
      Square signs (configured on the webhook, not `request.url` behind the tunnel).
- [x] **`integration` workflow action kind:** run a workspace integration's action with templated args; result →
      `$steps.<id>.output` (so later steps can store returned ids). Respect `requires_approval`.
- [x] **`set_data` entry op:** validated merge into `data_json` (the artwork's `status` is a schema field; `set_metadata`
      can't override it because fields read data_json first).
- [x] **HTTP helper `delete` (+ `put`)** in the SDK protocol and core `MarvinHttpHelper` (Square deletes payment links
      with DELETE). SDK version bump.

## Provider — new repo `InnerOpen/marvin-integration-square` (from MarvinIntegrationTemplate)
Built locally at `~/code/MarvinIntegrationSquare` (`2d16ab7`, 68 tests, Square-Version 2026-09-16); no GitHub repo yet.
- [x] Config: `environment` (sandbox|production), `location_id`, `currency` (USD), `redirect_base_url`; secret = access token.
      `check()` = list locations.
- [x] Action `create_listing(slug, name, price, image_url?, shipping?)`: upsert Catalog item + variation (stock tracking
      on, NC tax from her dashboard), set inventory 1, create Payment Link (order line → `catalog_object_id`, qty 1,
      `ask_for_shipping_address`, `redirect_url`, `payment_note`=slug). Idempotency keys from the slug. Returns
      `variation_id, payment_link_id, checkout_url, order_id`.
- [x] Action `close_listing(payment_link_id)` (DELETE link). Optional `list_locations` for setup.
- [ ] Declared content: `artwork` gains `sellOnline` (opt-in) — or document it if the type is site-owned.
- [ ] Tests with a stubbed HTTP client; CI like the Instagram repo; add tarball to `values-iwobble.yaml` init container.

## Workflows (grace-martin-franklin workspace)
- [ ] `square-list-on-publish`: `entry_published`, `artwork`, `sellOnline` + price set → integration `create_listing` →
      `set_metadata {square_variation_id, square_payment_link_id, square_order_id, square_checkout_url}`.
- [ ] `square-sold-online`: incoming webhook `square` (`payment.updated`, `COMPLETED`) → entry by
      `metadata.square_order_id` → `set_data {status: sold}` → rebuild.
- [ ] `square-sold-in-person`: `inventory.count.updated` with quantity 0 → entry by `metadata.square_variation_id` →
      `set_data {status: sold}` → `close_listing` → rebuild.
- [ ] Rebuild = Cloudflare Pages deploy hook on Grace's CF project, as a workflow-type webhook.
- [ ] Dedupe on Square `event_id` (webhooks retry).

## Site (gracemartinfranklinart.com repo)
- [ ] Artwork page: **Buy** button when `status = available` and `square_checkout_url` is set; Sold badge otherwise.
- [ ] `/thanks` page (Square's `redirect_url`): "Thank you — Grace will be in touch about delivery."

## Verify
- [x] Square **sandbox** end to end on a local Marvin (Jared's developer account), 2026-10-02, via a temporary Cloudflare
      quick tunnel: Apply created the fields (+price) / webhook / 3 workflows; publish → `create_listing` (item, stock 1,
      link with redirect + $15 shipping, order on the catalog variation) → ids on the entry. A reader-style sale (inventory
      adjustment IN_STOCK→SOLD) → Square delivered `inventory.count.updated` → **real Square signature verified** →
      mark-sold → close-when-sold → link 404. 6 s end to end. Square sent 2 events for one sale; only one matched.
      Not tested: paying through the hosted checkout page (needs a card entered on Square's page — do by hand).
- [ ] Confirm by hand: a checkout through the link (sandbox test card) also lands at IN_STOCK 0 → sold; a sold-out link
      refuses checkout; which fee applies to API links.
- [ ] Provider nit: a second `close_listing` returns `already: false` (Square answered the repeat DELETE with 200).
- Square retired `location_id` on inventory *adjustments* at 2026-07-15 (→ `from_location_id`/`to_location_id`); the
  provider's PHYSICAL_COUNT still works at Square-Version 2026-09-16.
- [ ] Production: Grace's token + location, webhook subscription in her Square developer app, deploy hook. Via the dev
      instance first if it exists by then.

## Decisions (Jared, 2026-10-02)
- Opt-in per artwork: `sellOnline` boolean on `artwork`.
- Shipping: flat fee per artwork — `shippingFee` field, added to the Square order as a shipping charge.
- Build now on `develop`, tested locally + in Square's sandbox; roll out to the live server only when Jared says.
