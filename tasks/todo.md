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
- **C2** — carry a specialist's ask up to Marvin: **planned 2026-10-04, see "Slice C2" below.**
- **Marvin-first picker** — very low priority, probably won't implement (Jared 2026-10-04). (separate commit): Ask page picker — Marvin first and default; then the workspace's agents; Ask and Chat under "Built-in" at the bottom (Chat hidden when the default model supports tools). No backend change.

## Slice C2 — carry a specialist's ask up to Marvin (plan, 2026-10-04)

**Goal:** when Marvin hands off to a specialist and the specialist hits an ask-first call, the approval appears
in the user's conversation with Marvin (Ask page or bubble); approve/deny there resumes the child on its own
thread/execution, the child's answer becomes the `run_agent` result, and Marvin finishes with one answer.

**Today (origin/develop):** children never park — `_bind_agent_tools` (operations_controller ~:2080) only allows
parking at depth 0, so a child's ask-first tools simply aren't bound. `run_agent` runs synchronously in the loop
(`services/ai/agent.py` dispatch ~:204). Park/resume: `_park_agent_run` (~:1673) → `park_thread`
(`services/ai/threads.py` ~:207); `resume_thread` (~:1044) is owner-only. Abandon only at depth 0. Depth is 1
(specialists can't hand off further). No expiry. **To verify first:** the bubble's default Marvin (`POST /agent`,
~:769) binds tools with no agent spec, which may skip Marvin's permission matrix (ask-first `automation_run`/`mcp`)
— if so, bubble Marvin can't park at all (and isn't asking when it should).

**Design:**
1. A tool can defer: `ToolDeferred(child)` in `agent.py` → `PendingCall(kind="handoff", child=…)`; sibling calls still
   run; loop stops `awaiting_approval`; `ResumeState.outputs` feeds a child's result in as the tool output.
2. Child parks quietly on its child thread (`emit=False`, `pending_json.parent={thread_id, call_id}`); delegate
   raises `ToolDeferred`.
3. Parent parks with a nested record; decidable ids are paths (`c1/c7`); `flatten_pending()` gives one card with the
   parent's own asks and the child's, each tagged `via`.
4. Resume walks children first (`_resume_core` extracted, recursive): child finishes → output; child re-parks →
   parent re-parks without running; then the parent loop continues once.
5. Resuming on a child thread forwards to the root (one place decides).
6. Two specialists → both parked; same specialist twice → guard error result.
7. Abandon cascades down (new message on parent) and up (new message on a parked child); optional TTL
   `AI_PARKED_RUN_TTL_HOURS` (default off).
8. Permissions re-checked at decision time: owner of root + child threads, `may_talk` still passes, child tools
   rebound with the child's matrix at the caller's current role, "no longer permitted" if revoked. Never widened.
9. Audit: append-only `metadata_json.approvals` on each execution; approval events gain `via_agent`,
   `child_thread_id`, `decided_by`, `surface`, `reason`; fired once, on the root.
10. Live steps show "Waiting for approval: run_workflow · via Workshop".

**No migration** (JSON keys only). **API:** flattened `pending` with `via`; resume accepts path ids; `source`
bubble/ask_page. **UI:** Ask page card with "via" chips; bubble inline approve/deny card (required when the Ask
page is off — today that case is a dead end even for plain ask-first); `approval_requested` toast.

**Checklist:**
- [x] 0) bubble `POST /agent` binds Marvin's matrix and parks (`f040df49`, tests/test_bubble_agent_permissions.py)
- [x] 1) loop deferral — `ToolDeferred`, `PendingCall(kind="handoff", child)`, `ResumeState.outputs`; still-pending hand-off → re-park without a model call
- [x] 2) child parking — specialist binds ask-first under a thread-backed parent, parks quietly (`pending_json.parent`), delegate raises `ToolDeferred`
- [x] 3) nested record + `flatten_pending()` — recursive, path ids `c1/c7`, `via`/`viaName`/`viaChain`/`childThreadId`/`childExecutionId`
- [x] 4) recursive resume — `_resume_leg` / `_resume_child`, children first; resuming on a child thread forwards to the root
- [x] 5) abandon cascade (up + down, `parked_runs.end_tree`) + TTL `AI_PARKED_RUN_TTL_HOURS` (default 168; hourly task + lazy 409 on resume)
- [x] 6) permission re-checks — owner of every thread, `may_talk` per agent (else `no_longer_permitted`), tools rebound at current role (`NOT_PERMITTED_RESULT`)
- [x] 7) audit `metadata_json.approvals` (append-only) + events once on the root with `via_agent`/`child_*`/`decided_by`/`surface`/`reason`
- [x] 8) Ask page card (via chips grouped by origin, root switch, live-step wording)
- [x] 9) bubble inline card (+ "Open on Ask page" when that source is on, resume source `bubble`) + `approval_requested` toast (owner only; Ask off → opens the bubble)
- [x] depth setting `AI_HANDOFF_MAX_DEPTH` (default 1; recursion works for 2+, chain guard)
- [x] follow-ups: `GET /agent/tools` through Marvin's matrix with `asksFirst`; compose/revise use the run's tone (`ToolContext.tone_register`)
- [x] 10a) manual (Agents and Ask, Operations settings)
- [ ] 10b) rollout + Jared's walk-through

**Risks:** fixing the bubble matrix makes workflows/MCP writes start asking in the bubble (correct, visible);
stale child context on long waits; one request runs child + parent legs (session/rollback care); path ids must stay
stable across re-parks.

**Review (2026-10-04, branch `feat/agents-c2-carry-ask`):** built as planned; no migration. Commits: follow-ups
(`/agent/tools` matrix + run tone), backend C2, frontend, docs. Design notes: the parent's hand-off call stores a
*snapshot* of the specialist's pending calls (refreshed on every re-park) so `pending` flattens without loading child
threads; the child thread's own `pending_json` stays the source of truth for resuming it. A partially-settled resume
(parent's own calls decided while a specialist re-parks) runs the parent's approved calls once and re-parks without a
model call. Approval events: granted/rejected each carry only the calls with that decision (the decision map stays
complete); event-level `via_agent`/`child_*` are set only when every call in the event comes from one specialist.
Depth: platform setting (least churn); depth 2+ parks and resumes (tested), an agent already in the chain is refused,
each level still nests inside the parent's request. Expiry fires `approval_rejected` reason `expired`, no notification.
Tests: tests/test_agent_handoff_approval.py (loop + controller end to end over the real loop with a scripted provider),
plus updates in test_agent_approval/test_agent_handoff/test_bubble_agent_permissions/test_tones; frontend node tests in
lib/approvals.test.mjs, pending.test.mjs, toast.test.mjs. Full backend suite green; astro check = base (50). Browser
check on SQLite + fake Ollama: Ask page card with the via chip, bubble inline card → approve → answer, toast (Ask on →
link; Ask off → opens the bubble with the card). Not verified: a real model, Postgres, the "replaced by a newer
message" card state in a browser. Code review (subagent) found no critical bugs; fixed: a specialist failing before its own
resume starts is ended (`failed`) instead of left `awaiting_approval`; a hand-off the router may no longer make
(matrix/depth changed) does not resume the specialist; deciding on a specialist's thread is refused (409) when the root
waits on other actions too, so nothing unseen is denied. Known, left: `approval_granted` fires before the legs run, so
it can list a call that then ends `no_longer_permitted`/`failed` (the execution's audit has the truth); an orphaned
specialist park (parent failed after the child parked) blocks re-hand-offs to it until TTL or a message on its thread.

**Decisions (Jared 2026-10-04):** 1) yes — the bubble's Marvin follows Marvin's permission matrix and parks ask-first calls like the Ask page (test + fix done as a separate change first); 2) resuming on a child thread passes the decision up to the root; 3) yes — a new message on a parked child abandons the parent too; 4) parked runs expire (default TTL, e.g. 7 days, configurable), no notification on expiry for now; 5) approval events fire once on the root, plus an `approval_requested` toast popup; 6) the bubble always gets the inline approve/deny card (plus the Ask page link when the Ask page is on); 7) hand-off depth is configurable (workspace or platform setting) if it isn't too much churn, default 1.
forwards to parent (rec.) or 409? 3) new message on a parked child abandons the parent too (rec.)? 4) expiry off or
default (e.g. 7 days), notify on expiry? 5) events once on the root (rec.)? 6) bubble inline card always, or only
when the Ask page is off? 7) design for hand-off depth 2 now, or keep depth 1?

## Custom tones (Marvin Agents) (plan, 2026-10-04)

**Goal:** a workspace defines its own named tones — name, instructions, and a persona rule (frame only /
everywhere / drop persona) — usable as the workspace default, an agent's default, and per call (Ask page,
bubble). Built-ins `auto` / `professional` / `playful` stay (hideable, not deletable); every stored value keeps
working.

**Today (origin/develop):** `default_register` on workspace AI settings (unvalidated string) and on agents
(String(16), hard-coded tuple in `schemas/group/agent.py`). Prompt clause built in
`routes/ai/operations_controller.py` `_register_clause` (~:2338) and appended last to the system prompt at
:775/:982/:992/:1848/:1855; carried through park/resume (:1112/:1715) and hand-offs (:1835). Compose/revise pass a
register that authoring ignores (recipe voice wins; revise ignores the per-call value). Bubble has no picker.

**Design:**
- JSON on `workspace_ai_settings`: `tones` `[{slug, name, instructions, persona, description?}]` + `hidden_tones`.
- `services/ai/tones.py`: `ToneSpec`, built-ins in the same shape, `validate_tones`, `resolve_tone`,
  `tone_clause` (replaces `_register_clause`, same position; built-in output byte-identical — golden tests).
- Slugs fixed on rename; built-in slugs reserved; ≤20 custom tones; instructions ≤1500 chars (~375 tokens/step).
- Unknown/deleted slug at run time falls back (agent → workspace → auto) with a warning; on save → 422.
- API: `GET/PUT /api/groups/ai-settings/tones` (PUT admin; 409 if a removed tone is used by agents, `?reassign`),
  `POST …/tones/preview` (assembled clause + token estimate).
- UI: tones editor on AI settings, agent default select and Ask picker from the endpoint, bubble `/tone <name>`.
- Migration: add the two columns; widen `workspace_agents.default_register` to String(40) (Postgres would reject
  longer slugs); export/import carries tones.

**Checklist:**
- [x] tones module (`services/ai/tones.py`)
- [x] columns + migration (`a8d4b0f6c3e9`: `tones`, `hidden_tones`; agent `default_register` String(40))
- [x] controller swap (`_register_clause` / `_effective_register` / `_default_register` delegate to tones)
- [x] schema/validation (agent slug shape + 422 for an unknown tone; PATCH default 422)
- [x] endpoints (`GET/PUT /groups/ai-settings/tones`, `POST …/tones/preview`)
- [x] authoring wiring (entry-type voice wins, tone otherwise; revise honours the per-call tone)
- [x] export/import
- [x] UI (Tones card on AI settings, agent + Ask pickers, bubble `/tone` + chip)
- [x] docs (manual → Agents and Ask → Tones)
- [x] tests (validation, clause modes × persona, golden built-ins, fallback, 409, column length, round-trip,
  drafts precedence) — `tests/test_tones.py`, `frontend/src/lib/tones.test.mjs`

**Risks:** per-step prompt cost (shown in the editor); weak models may blur "everywhere" — steer client-facing
tones to "drop"; tone text is admin-only (same trust as persona); explicit tones propagate to hand-off specialists.

**Decisions (Jared 2026-10-04):** 1) tones apply to compose/revise drafts too, but the entry type's own voice (recipe `enrichment.voice`) takes precedence — the tone is used only where the entry type has no voice; 2) built-ins are hide-only, not editable; 3) the editor is a section on AI settings; 4) bubble gets a `/tone` command (no picker); 5) deleting a tone that agents use is blocked (409 listing the agents); 6) free-text instructions only for v1; 7) anyone can pick a tone per call, only admins create/edit tones.
settings or own page? 4) bubble `/tone` command enough, or a visible chip? 5) deleting an in-use tone: block or
reset agents? 6) free-text only for v1, or structured knobs (max length, no emoji)? 7) non-admins pick per call
(yes) / create personal tones (no)?

**Review (2026-10-04, branch `feat/custom-tones`):** built as planned. The controller keeps its method names
(`_register_clause` etc.) so call sites and the concurrent `POST /agent` work stay untouched; they now resolve
through `WorkspaceTones.resolve` (caller → agent → workspace → auto, unknown slugs skipped with a warning). Built-in
clauses are pinned byte-for-byte. `?reassign` was not built (decision 5: block only). The Ask page's tone picker
now leads with "Default (…)" and sends no tone for it, so the workspace default reaches the main agent there
(before, the page always sent `auto`). Drafts: Auto/Professional stay plain, Playful and *everywhere* tones bring
the persona, custom tones add their instructions; agent `compose_entry`/`revise_entry` tools use the workspace
default (the run's tone isn't plumbed into ToolContext). Not done: a browser walk-through of the new UI.

# Trash — dropped (Jared 2026-10-06)

Trash dropped (Jared 2026-10-06): Archive is the reversible delete; the original bug (agent had no remove tool)
fixed by `archive_entries`; hard delete stays human-only; hourly R2 backups cover mistakes.

- [x] `archive_entries` (branch `feat/archive-entries-tool`): up to 50 entries, same path as the entry page
      (EntryService.set_status, `require_can_edit_entry`), published entries ask first, own `entries_archive`
      matrix row; `revise_entry` + the agent preamble steer deletes to it. No AI hard delete.

# Dev instance + Postgres (2026-10-01, Jared: "add that plan to the todos")

Someone else (Grace) now uses the live instance, so changes need somewhere to land before production. And
production's SQLite-on-NFS is the known weak point (the 2026-09-11 502s; backend pinned to one replica).

## Plan
- [x] **Image tags first** (2026-10-06): production pins `image.tag=develop-<sha>` — the immutable images CI builds
      for every develop commit (release commits are `[skip ci]`, so `1.0.0-rc.N` has no image of its own).
      Promote with `scripts/deploy/promote-iwobble.sh <commit>` (checks both images exist, helm-upgrades with that
      commit's chart, waits for the rollouts); `helm history marvin -n marvin` is the deploy log, `helm rollback`
      the undo. `pullPolicy: IfNotPresent`. Dev will follow `:develop` once it exists.
- [x] **Postgres on the cluster:** CloudNativePG operator v1.30.1 installed (OperatorHub, `openshift-operators`, manual
      approval). One small single-instance `Cluster` per environment, rendered by the chart (below).
      No Barman Cloud plugin / cert-manager (Jared, 2026-10-06): backups are the hourly `pg_dump` only — no PITR by
      choice; how to add it later without moving data is in `docs/manual/postgres.md`. Storage: `managed-nfs-storage`
      is the only class; used (Jared: keep), with the risks and better options in the same page ("Storage").
- [x] **Chart (2026-10-06, branch `feat/postgres-dev`, not pushed):** `dbEngine: postgres` → `POSTGRES_*` from
      `postgres.existingSecret` or the CNPG `<cluster>-app` Secret (backend, combined mode, backup job);
      `templates/postgres-cluster.yaml` (`postgres.cluster.enabled`): Cluster (Postgres 17, initdb marvin/marvin,
      `resource-policy: keep`), no backup section. SQLite renders byte-identical (values-iwobble/-production/-staging/-k8s/defaults). Keep the
      `marvin-data` PVC (assets + `.secret`). Allow `replicaCount > 1` only once assets are on shared/object storage.
      Postgres 17, not 16 (Jared: keep): the image's `pg_dump` is Debian's 17 and its archives don't restore cleanly
      into 16, so the clusters and the CI Postgres job moved to 17 together (suite green on 17 locally).
- [x] **`marvin-dev` namespace:** `values-dev.yaml` built (split, `:develop` + `Always`, cluster `marvin-dev-pg`,
      2Gi assets PVC, routes `*-marvin-dev.apps.ocp4.iwobble.com` + `X-Robots-Tag: noindex`, plugins as prod,
      scheduler off, hourly backup to bucket `marvin-backups-dev` — one R2 token for both buckets, Jared's choice).
      To do: merge, Secret `marvin-r2-backup` (bucket `marvin-backups-dev`) from `pass`, `helm upgrade --install`,
      load production with `--pause-outbound`, first backup + restore test (runbook "The marvin-dev environment").
      Up 2026-10-06 (helm rev 1): cluster `marvin-dev-pg` healthy; loaded from production's latest hourly dump + config + assets (Job `marvin-load-prod-copy`: offsite_backup restore from `marvin-backups`, `pg_restore --clean --single-transaction`, then `--pause-outbound` → 74 rows paused). Admin `marvin-marvin-dev.apps.ocp4.iwobble.com`, API `marvin-api-marvin-dev…` (LAN). First backup to `marvin-backups-dev` OK.
- [x] **Hostnames** (2026-10-06): `admin-dev.iwobble.com` + `api-dev.iwobble.com` on the cloudflared tunnel (one level deep,
      so the free `*.iwobble.com` certificate covers them — `dev.admin.…` would need Advanced Certificate Manager).
      values-dev pins `publicApiUrl` + `corsOrigins` to them. Still to do (Jared): Cloudflare Access in front of both.
- [x] **Full SQLite → Postgres data copy:** `python -m marvin.scripts.sqlite_to_postgres` (in the backend image):
      alembic head, same revision both sides, every value checked against the Postgres column type first, then one
      transaction (truncate, drop FKs, copy, re-create FKs, reset sequences, verify counts + per-table content
      checksum); refuses a non-empty target without `--truncate`; `--dry-run`. Rehearsed locally on a copy of
      production (2026-10-06, PG 16 and 17, and inside the built image): 61 tables / 15,949 rows, 94 FKs, all
      checksums equal; the backend served entries, event connections, workflows and a workflow dry run on it.
      `--pause-outbound` / `--unpause` switch off (and later restore exactly) webhooks, integrations + subscriptions,
      workflows, email subscriptions, SMTP profiles, MCP servers, scheduled tasks and auto site rebuilds in a
      non-production copy (record table `marvin_outbound_pause`). To do: load dev with it.
- [x] **Backups:** the off-site job `pg_dump`s Postgres **hourly** (`postgres/marvin-<ts>.dump`, verified; retention
      48 hourly + 14 daily + 8 weekly; `postgresql-client` in the backend image) — ≤ 1 h data loss, no PITR by choice.
      Tested end to end against an S3 stand-in and a pg_restore. To do once dev is up: the **restore test** from R2
      (runbook "Restore test": dump → scratch Postgres 17 → per-table counts equal to live).
      Production verified 2026-10-06: hourly `pg_dump` to `marvin-backups/postgres/`, restore test into a scratch Postgres 17 matched 62/62 tables, 15,986 rows.
- [x] **Off-site backup (built 2026-10-06, branch `feat/offsite-backup`, not yet deployed):** answer to "what backs up
      production today" was *nothing* (`/app/data/backups` empty; the Backups feature exports workspace content only).
      Nightly CronJob `marvin-offsite-backup` (chart `backup.*`, on in `values-iwobble.yaml`, 03:15 America/New_York) runs
      `python -m marvin.scripts.offsite_backup` → R2 bucket `marvin-backups`: SQLite online-backup snapshot +
      `integrity_check` (`sqlite/`), `.secret` + `scheduler_state.json` + `templates/` (`config/`), incremental `assets/`
      mirror; 14 daily + 8 weekly retention; `restore` subcommand. Runbook: `docs/manual/offsite-backup.md`. Tested: unit
      tests + e2e against MinIO (backup under a live writer, re-run uploads 0 assets, restore matches).
      Still to do: create Secret `marvin-r2-backup` from `pass` (`marvin/r2/access-key-id`, `marvin/r2/secret-access-key`,
      `marvin/r2/endpoint`; bucket `marvin-backups`), deploy an image that has the script, `helm upgrade`, run a one-off
      job, then a test restore into a scratch dir. Postgres: `pg_dump` step built 2026-10-06 (see Backups
      below); `backup.prefix` for dev.
- [ ] **First feature through dev:** `archive_entries` (the agent's reversible delete, above; replaces Trash).
- [x] **Production cutover — done 2026-10-06** (Jared: "run it"). Phase 1 `691395d3` (rev 22): `marvin-pg` up while still on SQLite;
      in-cluster rehearsal copy OK (61 tables, 15,974 rows, ~1 min). Window 21:20:55–21:23:02 UTC (~2 min down): backend
      scaled to 0 → copy Job `marvin-sqlite-to-postgres` COPIED 61/61 ok, 0 problems, rev `011f6c720d1d` → promoted
      `e646afad` (rev 23, `dbEngine: postgres`, hourly backups). Smoke: reads/save/dry run/asset OK; first `postgres/` dump
      (7.4 MB) restored into a scratch Postgres 17: 62/62 tables, 15,986 rows, no differences. Rollback = `helm rollback
      marvin 22 -n marvin` (SQLite file untouched) — only sensible while Postgres has no new data worth keeping.
      Backend `Recreate` dropped the same day + `preStopSleepSeconds: 15`: a rolling restart measured 0/120 failed health checks (5s preStop dropped ~6s). Dev on Postgres is up (above).
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

# Grace go-live — Square from sandbox to production (2026-10-02, Jared: "make a todo")

State 2026-10-02: 129 of Grace's 131 available artworks are listed in Square's **sandbox** (bulk "Turn on Sell online"
workflow; 129 items, 129 links, no duplicates, 128 with the painting). Fevered Radiance and Manifolds… have no price.
Between Lives was listed before item pictures existed — it gets one on its next price/shipping change.

- [ ] **Reset-listings workflow** in the Square integration (`content.py`), manual + target `artwork` / Fields equal
      `sellOnline = true`: clear `square_listed_for` (and the `square_*` ids) so every artwork re-lists against the
      production token. One click at go-live; also useful after a token/location change.
- [ ] **Shipping policy** — every link is free shipping today (no `shippingFee` on 129 of 131). Grace decides a fee or a
      rule (e.g. by size); then a bulk "Set fields" workflow sets it, which re-lists each with the fee.
- [ ] **Production credentials**: Grace's production access token (`{{SQUARE_TOKEN}}` secret), environment
      `production`, her real `location_id` (list_locations), `redirect_url`.
- [ ] **Production webhook**: subscription in her Square developer app (`inventory.count.updated`) → the `square-events`
      incoming webhook URL; store the returned signature key as the webhook's secret.
- [ ] **Go-live order**: switch the integration to production → run Reset listings → watch the toaster → spot-check a
      link with a real card refund, or a $1 test item → clear the sandbox catalog.
- [ ] Optional: strip HTML from activity-toast failure details (a 404 page showed raw HTML) — Jared: not now.

# Builder — Marvin knows how Marvin works, and configures it with you (2026-10-02, Jared)

Jared: "Marvin, or the default agent, is the main one, and should know — or pass off to an agent — how to build
things like workflows… like you suggested doing all the link updates with a workflow and then explained it. That
would be nice to have built in, whether it reads documentation or something." Then: "Maybe a Marvin documentation
MCP? It should always be updated anyway." Continues the 2026-09-24 idea *"an agent that helps a user configure their
site"* (configure Marvin's behaviour — types, collections, tasks, workflows, integration content — never the site's code).

Today the agent can read structure and run workflows (`list_workflows`, `run_workflow`, `list_entry_types`, …) but
cannot create a workflow / entry type / collection / scheduled task, and has no access to how Marvin works — asked
"how do I bulk-turn-on Sell online?", it would guess.

## Design
- **Docs are the single source of what Marvin knows about itself** (`docs/manual`, versioned with the code), served
  from the files **bundled with the running version** — so the answer always matches what's deployed (a separate docs
  service reading the published site drifts a deploy ahead/behind).
- Two consumers of the same files: built-in agent tools, and **MarvinMCP** (so Claude Code/Desktop get "the Marvin
  docs MCP" with no new service to host).
- **Docs explain *how*; a live catalog says *what's here*** (this workspace's entry types + fields, connected
  integrations, the triggers/steps/ops/condition fields the editor offers right now). Builder uses both, so it can't
  invent a step that doesn't exist or a field the type doesn't have.
- **Safety:** Builder drafts, never runs. Created workflows are **disabled**; every create is **ask-first** in chat and
  shows the JSON it will write; it runs Preview and reports the count ("would touch 127 artworks") with a link to the
  editor. A person reviews, enables and runs. Writes go through the agent permission matrix; AI content still obeys
  Approval mode.
- **Teach while doing:** Builder explains what it built and why (Run on vs Only if, the 250 cap…), the way this session did.
- **Guided steps come first** (Jared, 2026-10-02: "you told me how to build it, and I was able to build it… even steps
  would be good based on their need"). Builder's first answer is numbered steps written for *this* workspace — the
  editor's exact labels, the user's real types/fields/values, what Preview should show, what to watch for — then
  "want me to draft it instead?". Needs no write tools; drafting is the opt-in second mode.
- **Labels must match the screen**: the catalog returns each item's UI label next to its internal name (`set_data` →
  "Set fields", target → "Run on a query of entries", `data` → "Fields equal"), and a CI check fails when a label the
  docs use no longer exists in the editor.

## Plan
1. [ ] **Unblock the manual** (prereq; Brain task "docs site — unblock and publish"). The staged docs never committed:
       gitleaks flagged a placeholder token at `docs/manual/whats-new/publishing-api.md:25`. **Jared decides the fix**
       (recommended: rewrite to `$MARVIN_SITE_TOKEN`), then commit, push develop, verify the docs site.
2. [ ] **Bundle the docs with the backend**: package `docs/manual/**/*.md` into the image (or a generated index at
       build time); a small docs service: list pages, read a page, search (title/heading/keyword ranking first;
       embeddings later if needed). Tests: every page loads; search finds the workflows page for "bulk update".
3. [ ] **Agent tools** `search_docs(query)` → ranked page/section snippets with paths; `read_doc(path, section?)` →
       markdown. Category `docs_read` (read, allowed by default). Marvin's preamble: "for how-to questions about
       Marvin itself, search the docs before answering; cite the page".
4. [ ] **MarvinMCP**: expose the same two tools (`marvin_search_docs`, `marvin_read_doc`) — no workspace token needed
       beyond the existing auth; docs are not workspace data.
5. [ ] **Live catalog tool** `describe_workflow_options` — the same payload the workflow editor uses (triggers, step
       kinds, entry ops, AI operations + their inputs, condition fields/ops) plus the workspace's entry types + fields
       and connected integrations + their actions.
6. [ ] **Doc-coverage CI check**: fail when a workflow trigger, step kind, entry op or AI operation has no mention in
       the manual — so a feature can't ship undocumented and Builder never meets something it can't explain.
6b. [ ] **Guided-steps mode (ship first)**: Builder answers "how do I…" with numbered, workspace-specific steps
       (exact UI labels from the catalog, real field names and typed values, expected Preview count, run warnings),
       ending with an offer to draft. Works with only docs + catalog + read tools. Catalog gains UI labels; CI label
       check (step 6) covers them. Verify with this session's Sell-online question: the steps must match what Jared
       built by hand.
7. [ ] **`draft_workflow` tool** (second mode, opt-in) (category `automation_author`, write, **ask** by default): validates the definition
       (same validator as the editor), creates it **disabled**, runs the target Preview, returns id + editor link +
       match count + any validation warnings. Never enables or runs.
8. [ ] **Builder agent** (system agent, persona kind): instructions = configure-not-code line, drafts-only, explain
       every piece, always Preview before suggesting Run, warn about long runs (synchronous; don't Run twice; no
       restarts mid-run). Tools: docs_read, catalog, entries/library read, automation_read, `draft_workflow` (ask).
       Marvin's roster gets a hand-off line: "how do I… / set up / automate / build a workflow / bulk-update…".
9. [ ] **Docs pages for this session's patterns** (they double as Builder's recipes): bulk update via Run on a query;
       Fields equal vs Only if; typed values (true/45); the 250 cap; long manual runs; rebuild debounce +
       `SITE_REBUILD_*`; activity toasts; Square listing + reset-listings; approval mode scope.
10. [ ] **Verify end to end**: ask Marvin in Grace's workspace "turn on Sell online for every available artwork with a
       price" → hand-off to Builder → it cites the docs, drafts the workflow disabled, Preview says N, explains it; I
       enable + Run. Same question from Claude Code via MarvinMCP returns the docs page.

## Later
- Phase 2: the same draft-and-ask tools for **entry types, collections (incl. smart rules), scheduled tasks** and
  integration blueprints (closes the 2026-09-24 Brain task).
- Phase 3: embeddings for docs search if keyword ranking falls short; per-workspace "house recipes".

# AI provider plugins — model vendors as site-wide plugins (2026-10-03, Jared: "make a backlog item")

**Status (2026-10-07):** started with OpenAI (Jared 2026-10-07: "move on to the OpenAI plugin after all is
validated"). SDK contract 0.8.0, core registry and the `marvin-ai-openai` package (openai + azure) are built and
tested locally on `feat/ai-provider-plugins` (core), `feat/ai-provider-contract` (SDK) and `feat/ai-provider-types`
(marvin-sdk); nothing pushed, no GitHub repo for the plugin yet. Other vendors not started. See "Review (OpenAI
slice)" below.

Why: one new model (gpt-6.1-sol) needed three core releases in a day (max_tokens renamed, tools refused while
reasoning, no price). The Responses API switch removed the per-model rules; what is left is vendor churn
shipping inside Marvin's release. Providers become plugins so a vendor fix is a plugin release.

## Decisions (Jared, 2026-10-03)
- **Every plugin is installed site-wide, by a platform admin only** — AI providers and integrations alike
  (Helm init container / admin, never a workspace). Workspaces only *configure*: an installed integration
  can be connected by any workspace; an installed AI provider can be chosen in any workspace's AI settings.
- Own plugin type — not an "integration": entry-point group `marvin.ai_providers`, its own SDK contract.
- **One package per vendor** (Jared, 2026-10-03).

## Plan
- [x] SDK: move the provider contract (`AIProvider`, `Message`, `ToolCall`, `ToolDefinition`,
      `CompletionOptions`, `CompletionResult`, `ImagePart`) into the plugin SDK; core re-exports for compatibility.
      (SDK 0.8.0 `marvin_integration_sdk.ai`: plus `Credential` declarations with masking, `ModelPrice`/`price_for`,
      capability flags, model defaults, `AIProviderPlugin`; conformance kit `ai.testing` over a `FakeTransport`;
      reference `FakeAIProvider` + `ScriptedTransport` in `ai.fake`. `services/ai/base.py` re-exports.)
- [x] Core: discover providers from `marvin.ai_providers`; factory, credential modes and capability flags read
      the registry; AI Settings' provider list and model picker come from it (nothing hard-coded).
      (`services/ai/registry.py`; `GET /api/ai/provider-types`; platform credentials from `<SLUG>_<KEY>`, platform
      model from `<SLUG>_MODEL` then the provider's default (one helper for the three copies), embedding default
      from the provider; choosing an uninstalled provider is a 422; startup refuses an unknown
      `AI_DEFAULT_PROVIDER`; Admin → Plugins lists kind *AI provider*.)
- [~] Prices live with the provider (see Pricing below), not in core's `pricing.py`. (Provider's table first, core's
      table as the fallback while the built-ins remain; the layered lookup below is still to do.)
- [ ] Packages, one per vendor: openai (+ azure, shares `openai_api`), anthropic,
      google (move to the `google-genai` SDK — `google-generativeai` is deprecated), ollama.
      (openai + azure: `marvin-ai-openai` 0.1.0 at `~/code/MarvinAIOpenAI`, local only. Others not started.)
- [ ] Baseline (decide: leaning no built-in; the chart installs openai by default). Tests use a fake provider.
      (For now core keeps all five built-ins and a plugin replaces one by slug — no flag day. Tests use the SDK fake.)
- [ ] Helm: tarballs in the same init container as integrations; admin page lists installed providers + versions.
      (Admin page done. Blocker before production: the init container also installs `openai`'s dependencies —
      `pydantic`, `pydantic-core`, `httpx`, `anyio` — into `/plugins`, ahead of the image's on `PYTHONPATH`.
      The chart should drop packages the image already has, as it does for the SDK.)
- Order (Jared 2026-10-06): storage plugins go first and build the shared plumbing (entry-point loader, chart
      `plugins.packages`, admin Plugins listing, SDK as a core dependency); see "Storage plugins + backup targets" below.
- [x] Docs: provider plugin authoring guide next to the integration one (`docs/AI_PROVIDER_PLUGINS.md`; SDK README
      section; the plugin's README).

### Review (OpenAI slice, 2026-10-07)
- **SDK** (`feat/ai-provider-contract`, 0.8.0): 123 passed, 2 skipped (the kit's capability skips on a bare
  provider); ruff clean. The kit runs on `FakeAIProvider` and on a provider with no optional capability.
- **Plugin** (`~/code/MarvinAIOpenAI`, `main`): 69 passed, 1 skipped (the live smoke test: no `OPENAI_API_KEY` in
  the environment, and pass wasn't read). The conformance kit runs three ways over a fake OpenAI server
  (`httpx.MockTransport` under the real `openai` SDK): official API (Responses), an OpenAI-compatible server (Chat
  Completions), Azure. Core's `test_openai_api.py` and the OpenAI/Azure tool-calling tests are ported. Azure shares
  `openai_api` (its Chat Completions shapes moved there too). One deliberate difference from core's Azure:
  `test_connection` now fails on a bad key (core's swallowed the error in `list_models` and always said
  "Connected"); the kit caught it.
- **Core** (rebased on develop `58a0ae0b`): full backend suite with the exact verify command: 3582 passed, 15
  skipped without the plugin; 3583 passed, 14 skipped with `marvin-ai-openai` installed (`uv run --no-sync`, else uv removes it) — the extra test
  checks the plugin's prices, settings, capabilities and models equal the built-ins it replaces. Frontend: 484 node
  tests pass; `astro check` 51 errors, none in the two pages touched (all pre-existing); biome clean on them.
- **SDK Quality Gate**: reproduced like CI (`pip install -e .[dev]` in a clean 3.12 venv, SDK 0.8.0 on top):
  `origin/develop` regenerates clean against marvin-sdk `main`; this branch adds `GET /api/ai/provider-types`
  (+115 lines, additions only), committed on marvin-sdk `feat/ai-provider-types` on top of `main` (which has the
  platform-alert types); a full regeneration from this branch matches that commit exactly.
- **Push order**: (1) SDK `feat/ai-provider-contract` → develop (core pins its commit `39c4920`, and the pin must
  resolve for CI); (2) marvin-sdk `feat/ai-provider-types` → main; (3) core `feat/ai-provider-plugins`; (4) create
  `InnerOpen/marvin-ai-openai` and push the plugin (its CI fetches the SDK at `39c4920`).
- **Open for Jared**: the plugin repo name (`InnerOpen/marvin-ai-openai` assumed); Azure stays in the same package
  (cheap: shares `openai_api`), and `AZURE_API_VERSION` is now a platform setting; the chart's dependency
  shadowing (above) before installing the plugin anywhere; whether the chart should install openai by default.

## Pricing — no hard-coded model list (part of the same work)
Today `pricing.py` is a table of exact model names: a new model shows cost "—", and its runs add $0 to the
monthly budget, so a cost limit silently stops counting for it.
No vendor publishes a per-token price API for its own models, so prices come from layered sources, highest wins:
1. Admin override per provider+model (site-wide — prices don't vary by workspace).
2. The provider plugin: a shipped price table, plus `fetch_prices()` where the vendor has a machine-readable list
   (Azure: the public Retail Prices API).
3. A price feed, refreshed daily: OpenRouter's public models API (per-token prices across vendors) or LiteLLM's
   maintained price JSON — a core pricing source, not per provider.
- [ ] Implement the layered lookup (cache the feed; never block a run on it).
- [ ] Reconcile with real spend where the vendor reports it: a provider capability `billed_costs(since)` using
      OpenAI's organization Costs API and Anthropic's cost report (both need an *admin* key, separate from the
      inference key; daily granularity). Show estimate vs billed on the usage card; the budget can use billed.
- [ ] Unpriced runs are visible, never silent: the Usage card shows "N runs this month have no price" with a
      link to set one; the budget warns that it can't count them; setting a price backfills `estimated_cost_usd`
      from the stored token counts.

## Persona vs tone, raw JSON collapsed, Ask chip (2026-10-04)
Jared: make persona vs tone clear; the entry editor's JSON fields are "distracting and for those that don't know
might feel too technical"; the Ask page shows an empty attachment chip.
- [x] Prompt: persona is a `Character:` block; a tone is `Tone (<name>):` followed by the precedence rule (the tone
      wins on formality, length and mood; the character keeps its identity and way of speaking). Frame scopes the
      character to addressing the user, everywhere says it covers work product, drop omits it. Built-ins keep
      their behaviour; wording pinned verbatim in tests/test_tones.py.
- [x] `/chat` resolves and applies the tone like Marvin (it appended the raw persona).
- [x] Drafts: same labels and rule; an entry type's voice still wins.
- [x] `POST /tones/preview` returns parts (character, fromTone, rule, personaSummary, hasPersona); the editor shows
      "From your Persona" / "From this tone" / "Which wins" and the persona rule in plain words.
- [x] AI settings copy (Persona = who your assistant is; Tones = how it delivers); manual Tones section.
- [x] Agent prompt: "notifier" (removed) → integrations and MCP servers, as the overview's structure block lists.
- [x] Entry editor + new entry: data JSON, Metadata (JSON) and placement metadata behind `<details>`; summary says
      what's inside; metadata opens itself after a refused save; open state remembered per browser.
- [x] Ask page: `[hidden]` overrides for the attachment chip, suggestions row and Speak button; source check.

### Review
Full backend suite, frontend tests, Biome and ruff green; `astro check` 50 errors, the same files and counts as
the base. Browser-checked on SQLite + astro dev (headless Chromium): preview parts for frame / everywhere / drop,
JSON panels collapsed, collapsed metadata still saved, invalid metadata reopens its panel, no empty Ask chip.

# CLI 3.1 — catch up with the API (plan, 2026-10-05)

**Goal:** make `@inneropen/marvin-cli` safe to script again and cover the two most-used new areas — workflows and
integrations — plus a real "rebuild the site" call. Jared 2026-10-05: plan batches 0–2 + the rebuild endpoint.

**Today (CLI 3.0.0 `8671977`, SDK 4.0.0 types from rc.197, core rc.198):** the CLI wraps 213 of 355 manageable API
operations (60%) and calls no dead endpoint. Missing entirely: workflows, integrations, blueprints, incoming webhooks,
tags, review/suggestions, SMTP, agents/threads, tones/characters. The 3.0.0 changelog points users at the Apprise
integration, which the CLI can't reach. Quality: ~114 write commands print "✓ Created…" to stdout before JSON
(`--output json | jq` breaks); 44 commands define an input `--json <payload>` that shadows the global `--json` output
flag; `-o <file>` on export/download shadows `--output <format>`; webhooks/invites/admin-groups lists return page 1
only; `secrets create/update --value` lands in shell history; README shows non-existent `marvin site/entries`
commands; 4 stale help texts; the coverage drift gate's snapshot is rc.189 (8 newer endpoints unclassified). There is
no core endpoint to rebuild a site — only the `request_site_rebuild` task/workflow step.

## Design
**Batch 0 — output hygiene (no SDK work):**
- All human messages (✓/progress/warnings) go to **stderr**; stdout carries only data. Deletes/removes/revokes emit
  `{"deleted": "<id>"}` (and `{"ok": true, …}` for run/test/rerun/import) in JSON mode; prose otherwise.
- Input payload flag renamed **`--data <json|@file|->`**; `--json <payload>` kept one minor as a deprecated alias
  (warns on stderr) that no longer forces JSON output. `-o <file>` → **`--out-file`** (old spelling kept as alias).
- `--page/--all` on webhooks, invites and admin groups lists; `limit/offset` on form submissions.
- `secrets create/update`: value from `--value-stdin` or an interactive prompt; `--value` still accepted with a
  warning.
- Fix the README (publish commands, platform/admin overview), the 4 stale help texts, and refresh the drift
  snapshot to rc.198 so new endpoints are classified.

**Batch 1 — `marvin workflows`** (SDK ready except samples): `list`, `get`, `create/update --data`, `delete`,
`enable/disable`, `validate`, `preview`, `run [--dry-run] [--entry-id|--event-id]`, `executions [--status] [--limit]`,
`execution <id>` (steps, handling, retry chain), `samples` (adds the SDK method). Named "workflows" as in the manual.

**Batch 2 — `marvin integrations`:** `list` (with **needs attention**), `get`, `providers`, `plugins`, `check`,
`resolve [--alert-id]`, `run <id> <action> --data`, `options <id> <action> <input>`, `errors <id>` (the policy table)
and `errors set <id> <code> --review/--no-review --alert/--no-alert` / `errors reset`, `alert-routing` show/set,
`subscriptions` CRUD, `create/update/delete`. SDK 4.1.0 adds the rc.197 methods: options, resolve, error-overrides,
alert-routing, provider logo URL helper, admin plugins.

**Core — one rebuild call:** `POST /api/platform/site/rebuild` (EDITOR; same role as publishing) → requests a
rebuild through the existing debounced site-rebuild path (`site_rebuild_requests`, honours
`SITE_REBUILD_QUIET_SECONDS`), returns `{requested: true, queued_at, reason}`; `GET /api/platform/site/rebuild`
→ last request/build status if known. Used by `marvin site rebuild`, available to n8n and the UI. Covered by the
route role guard.

## Checklist
- [ ] Core: rebuild endpoint + tests (role, debounce, no integration configured → clear 409) + manual + whats-new
- [ ] SDK 4.1.0: rc.197 integration methods, workflow samples, site rebuild; regenerate types; tests; release
      (trusted publishing)
- [ ] CLI batch 0: stderr messages + JSON delete/run outputs; `--data`/`--out-file` with aliases; pagination;
      secrets stdin/prompt; README + help fixes; drift snapshot rc.198. Tests: `create --output json | jq` parses
      for every write command (one table-driven test), alias warnings, stdin secret
- [ ] CLI batch 1: `workflows` commands + tests against the integration-test backend in `cli.yml`
- [ ] CLI batch 2: `integrations` commands + tests
- [ ] CLI: `site rebuild`
- [ ] Docs: CLI reference pages, CHANGELOG via semantic-release (`feat:` commits → 3.1.0), migration note for
      `--data`/`--out-file`
- [ ] Release: SDK 4.1.0 → CLI 3.1.0 (both trusted publishing); core rebuild endpoint ships first

## Later (3.2+)
Review queue (`entries list --status`, counts, apply/reject suggestions, dashboard attention); `blueprints`;
publish-date/expiry flags and `publish entries --tag/--slug/--updated-since`; incoming webhooks + tags; smart
collection preview/members; MCP servers, embeddings status, tools, compose/revise; agents + threads (approve
ask-first via resume); SMTP profiles, submission protection, roles matrix; tones/characters (probably never).

**Decisions (Jared 2026-10-05):** remove the deprecated `--json <payload>` alias in 4.0; rebuild endpoint role EDITOR.

# CLI 3.2 (plan, 2026-10-05)

**Goal:** finish the CLI catch-up: review queue, blueprints, publishing ergonomics, incoming webhooks + tags, and
smart collections. Jared 2026-10-05: batches 3–7 of the coverage audit ("Later (3.2+)" above, minus the
agents/MCP/SMTP/tones tail).

**Today (CLI 3.1.0 `392264b`, SDK 4.2.0 `6241d97`, core rc.199):** SDK types already match rc.199 (regenerated
with the gate's toolchain: no diff). The SDK already has `tags` (incl. asset/resource attach) and
`incomingWebhooks` CRUD + token, and `collections.reorder`; it lacks suggestion review, entry counts, the dashboard,
blueprints, signature schemes, collection preview/members, the publishing `tag/slug/updatedSince` filters and an
asset file download. Core checks: `GET /api/platform/entries` takes **no filters** (status/type/limit are
client-side); the publishing entries list **does** take `tag`, `slug`, `updated_since`; blueprints live under
`/api/groups/blueprints` (read: any member; apply/update: ADMIN); incoming webhooks are ADMIN, reads included.

## Design
**Batch 3 — review queue:** `entries list --status <s> --entry-type <slug> --limit N --suggestions` (filtered
client-side; the type slug resolves through `entry-types`), `entries counts`, `entries apply-suggestion|
reject-suggestion <id>`, the same on `assets` and `resources` (EDITOR), `entries approve-asset|reject-asset <entry>
<asset>` (suggested assets), and a top-level `platform dashboard` (the "needs attention" counts + recent activity
from `stats/dashboard`).

**Batch 4 — `platform blueprints`:** `list [--kind] [--category] [--source] [--integration-id]`, `categories`,
`get <slug> [--source]`, `apply <slug…> [--params|--data]` (one slug → single apply; several → bulk, params keyed by
slug), `update <slug> [--params]`. Apply/update need ADMIN.

**Batch 5 — publishing ergonomics:** `platform entries update --publish-at/--expire-at/--status` (merged into any
`--data`; `--publish-at ""` clears), `publish entries --tag/--slug/--updated-since/--expand full`, `publish asset
<slug> --download [--out-file]` (follows the file route's redirect).

**Batch 6 — `platform incoming-webhooks` + `platform tags`:** webhooks `list/get/create/update/delete`,
`mint-token` / `revoke-token`, `signature-schemes` (all ADMIN). Tags `list/get/create/update/delete`,
`attach/detach <tag> --entry|--asset|--resource <id>` (tag by id or slug; create AUTHOR, edits EDITOR, entry
tagging follows the entry's edit rule).

**Batch 7 — smart collections:** `collections preview --rules <json|@file> [--target-type] [--limit]`,
`collections members <id>`, `collections order --data '[{id, sortOrder}]'`, `--smart-rules <json|@file>` on
create/update (sets `isSmart`).

**SDK 4.3.0:** `entries.counts/applySuggestion/rejectSuggestion/approveSuggestedAsset/rejectSuggestedAsset`,
`assets|resources.applySuggestion/rejectSuggestion`, `workspaces.getDashboard`, a `blueprints` module (list,
categories, get, apply, applyMany, update), `incomingWebhooks.signatureSchemes` (+ signature fields on the type),
`collections.preview/members`, publish `entries.list({tag, slug, updatedSince})`, publish `assets.download`
(an HttpClient binary read that keeps 4.1's retry and empty-body rules).

## Checklist
- [x] SDK 4.3.0: methods above + tests; types regenerated (gate toolchain; no diff); `feat:` commits (also fixed
      platform `assets.getFile`, which returned undefined for every file since 4.1 → `assets.download`)
- [x] CLI batches 3–7 + tests per group; permissions table + help; coverage manifest (38 routes → covered) and
      snapshot refreshed to develop rc.199 with the integration SDK installed (8 new endpoints deferred)
- [x] Docs: reference pages per group (review, blueprints, incoming-webhooks, tags, smart collections,
      publishing); MIGRATION 3.2.0; `mkdocs build --strict`
- [x] Release: SDK 4.3.0 → relock CLI (`npm install @inneropen/marvin-sdk@^4.3.0`) → CLI 3.2.0 (trusted
      publishing). Both published 2026-10-05.

**Core gaps:** no endpoint missing. Found while smoke-testing against develop: `POST
/api/platform/tags/{tag_id}/assets/{asset_id}` and `…/resources/{resource_id}` always 500 —
`attach_tag_to_asset`/`attach_tag_to_resource` compare `asset.group_id`, but `repos.assets.get_one` returns
`AssetRead`/`ResourceRead`, which have no `group_id` (entry tagging and both detaches work). Fixed in
`fix(tags)`: the repos already scope both lookups to the workspace, so the comparison is gone. Nice to have:
server-side `status`/`entry_type`/`limit` filters on `GET /api/platform/entries` (the CLI filters the full list
today).

# Media embeds — paste a link, get a player (plan, 2026-10-05)

**Goal:** paste a YouTube, Vimeo, Bandcamp, Spotify, SoundCloud, Apple Music/Podcasts, Tidal or podcast
(Simplecast/Transistor) link and get a player — in the admin editor and on published sites. One generic feature:
provider allow-list + server-side oEmbed resolution with a cache + Marvin-built iframes. Named "media embeds" in code
("embed" already means vector embeddings: `IndexingReactionListener`, `services/ai/embeddings_registry.py`).

**Today (origin/develop `5eaf4737`; MarvinAstro main 1.1.1; RenderersCore 1.1.0-next.10; SDK develop 4.0.0):**
- Bodies are **markdown strings in `data_json`** — no blocks/shortcodes/embed concept. Field types:
  `schemas/platform/entry_type_schema.py` (13 types), validated in `services/content_validator.py::_validate_field`.
  Editor: `entries/[id].astro` → `SchemaForm.astro` → `schema-fields/MarkdownField.astro` (textarea + regex preview
  `parseMarkdown`, which also lets `javascript:` links through).
- **The publishing API returns raw markdown** (`publishing_controller.py` `_entry_to_list_item`,
  `get_published_entry`), so embed data must be structured and the site renders it. `site.seo` is the pattern for a
  site setting.
- Sites render via **MarvinAstro** `src/markdown.ts` (marked + GFM) and `f.markdown()` → `set:html`; Grace and Mash &
  Burn also call `renderMarkdown` directly in a few files. RenderersCore Page/ArticleRenderer `set:html` raw
  unconverted markdown (separate bug; not used for bodies by these sites).
- **No sanitisation of content HTML anywhere**; no CSP on the admin or either site.
- Safe outbound HTTP: `services/integrations/http_client.py` (`_guard`, `MarvinHttpHelper`). A second guard copy in
  `builtins_actions._public_url_error`; `services/ai/media/enrichment.py` fetches unguarded with redirects.
- Providers (checked 2026-10-05): oembed.com lists YouTube, Vimeo, Spotify, SoundCloud, Simplecast, Apple Podcasts;
  Tidal and Apple Music answer but aren't listed; Transistor unconfirmed; **Bandcamp has no oEmbed and bot-challenges
  server fetches** (works only from pasted embed code).
- MarvinAstro peers `@inneropen/marvin-sdk ^3.0.0` (SDK is 4.0.0).

## Design
1. **Authoring (one mechanism underneath):** a **bare provider URL on its own line** in a markdown field becomes an
   embed (older sites just show the link; `<url>` / `[text](url)` keeps it a link); an **"Embed" button** in
   `MarkdownField` (paste link *or* provider embed code → reduced to a canonical URL); a new **`embed` field type**
   (URL value, optional `providers` filter) for structured "the player" slots. No block editor.
2. **Provider registry** (`services/media_embeds/providers.py`, data only): host/path patterns → match; optional
   oEmbed endpoint; `frame_hosts`; iframe src template; allow-listed params; `allow`/`sandbox`; aspect ratio or fixed
   height. Most providers build `src` from the URL alone (works without oEmbed); oEmbed adds title/thumbnail, resolves
   short links and supplies ids not in the URL (Simplecast). YouTube always via `youtube-nocookie.com`; Vimeo `dnt=1`.
3. **Resolution** (`resolver.py`): normalise → match → build src → oEmbed via `MarvinHttpHelper` (256 KB, 5 s, UA
   `marvin-cms/embeds`). Provider `html` never stored/passed on; where an id lives only in it, parse the `src`, require
   an allow-listed host/path, rebuild. 401/403/404 → `unavailable` (link card).
4. **Cache:** platform-wide table `media_embed_cache` (url_hash unique, provider, kind, status, embed_src, title,
   author, thumbnail, dims, aspect, error, fetched_at, expires_at — ok 30 d, else 1 d). Filled by the editor resolve
   endpoint and a best-effort `MediaEmbedReactionListener` on entry create/update/publish (≤20 URLs); **publishing
   reads never call out**.
5. **Fallback link card** when no safe src: `<a class="marvin-embed-link">` with title + "on {Provider}".
6. **Security:** allow-listed providers only; iframes always rebuilt by one escaped builder (`title`, `loading=lazy`,
   `referrerpolicy=strict-origin-when-cross-origin`, per-provider `sandbox`/`allow`, `allowfullscreen` video only).
   Core publishes `site.embeds.frameSources` so sites can generate `frame-src` later.
7. **Privacy mode:** site setting `site.embeds.mode` = `direct` | `click_to_load` (+ `consent_text`). Click-to-load
   renders a facade (button + plain provider link; no remote thumbnail) — no third-party cookies before a click,
   consistent with the Brain note *Marvin Privacy and Cookie Settings*.
8. **Publishing API:** `embeds: {<url as written>: PublishedEmbed}` on entry + list item — structured fields
   (provider, kind video|audio|podcast|playlist, status ok|link|unavailable, title, iframe{src, allow, sandbox,
   aspectRatio|height}, link) plus Marvin-built `html` per the site's mode. Additive; stored markdown never rewritten.
9. **Sites:** MarvinAstro 1.2.0 `renderMarkdown(source, {embeds})` (paragraph hook: a paragraph that is exactly a
   URL with an `embeds` entry → `embed.html`), `f.markdown()` passes embeds, `f.embed(key)`, `EmbedLoader.astro`
   (facade → iframe on click, host-checked), own `MarvinEmbed` type, peer `^3 || ^4`. RenderersCore `Embed.astro`.
10. **Admin:** `POST /api/platform/media-embeds/resolve` (AUTHOR+, rate-limited) + `GET .../providers`;
    `MarkdownField` preview moves to marked + DOMPurify and shows resolved players; Embed dialog; `EmbedField`.
11. **Agent:** `add_embed(entry, url, field?, after_heading?)` (EDITOR; staged as a suggestion like `revise_entry`;
    idempotent) + read-only `preview_embed(url)`; exposed over MCP; compose/revise guidance.

**Migration:** `media_embed_cache` only.

## Checklist
- [x] Registry + matcher + src/attribute builders, per-provider URL-form tests incl. look-alike hosts rejected
- [x] Resolver (oEmbed via MarvinHttpHelper, src extraction with host/path check, statuses, recorded fixtures; verify
      Simplecast/Transistor/Apple Music endpoints first)
- [x] `media_embed_cache` model + migration; `MediaEmbedReactionListener`; shared URL extractor
- [x] Publishing: `PublishedEmbed`, `embeds` on entry/list item, `SiteEmbeds` (+ `frameSources`), `html` per mode;
      tests incl. no outbound call on read
- [x] `embed` field type (schema, validator, compose map, schema editor, `EmbedField.astro`, docs)
- [x] Admin endpoints + MarkdownField preview (marked + DOMPurify) + Embed dialog
- [x] Site settings "Embeds & privacy" section
- [x] Agent tools `add_embed` (staged) + `preview_embed`
- [x] Before enabling: count published entries with a bare provider URL on its own line (they'll change on rebuild) — **0** in every workspace (default 57 published, grace-martin-franklin 299, mash-burn-co 96; no published entry mentions a provider host at all), 2026-10-05
- [ ] SDK 4.1.0 (types + `PublishedEmbed`), MarvinAstro 1.2.0, RenderersCore `Embed.astro`
- [ ] Sites: Grace + Mash & Burn bump MarvinAstro, add `EmbedLoader`, pass `{embeds}` where they call
      `renderMarkdown` directly, base `.marvin-embed` CSS
- [x] Docs: manual, `whats-new/media-embeds.md`, `docs/publishing-api.md`
- [ ] Rollout: core → SDK → MarvinAstro → RenderersCore → sites; browser check of every provider in both modes

**Review (core, 2026-10-05, branch `feat/media-embeds`):** core items done — migration `a78a8895a6a1` (revises `d5b1e8a3c7f2`).
Providers verified with real requests: YouTube, Vimeo, Spotify, SoundCloud, Apple Podcasts, Apple Music (`music.apple.com/api/oembed`),
TIDAL (`oembed.tidal.com`), Simplecast (`api.simplecast.com/oembed` — the oembed.com-listed `simplecast.com/oembed` only redirects),
Transistor (`share.transistor.fm/oembed`); fixtures in `tests/fixtures/media_embeds`. Bandcamp stays embed-code only.
Contract additions agreed with the MarvinAstro side: figure `style="--marvin-embed-aspect:…"` / `--marvin-embed-height:…px`,
iframe attrs limited to src/title/allow/sandbox/referrerpolicy/loading (fullscreen via `allow`), `data-marvin-embed-attrs` includes `src`.

## Later
Generic oEmbed discovery fallback; Instagram/TikTok/X/Bluesky; consent-manager-aware facades; thumbnails proxied via
Marvin; CSPs from `frameSources`; markdown HTML sanitiser in MarvinAstro (+ fix RenderersCore raw `set:html`); one
shared SSRF guard (also guard `enrichment.py`); periodic cache refresh/pruning; caption/start-time options.

**Risks:** existing bare provider URLs change on the next build; provider schemes/sandbox needs drift; Bandcamp only
via embed code; Simplecast/Transistor unverified; too-strict sandbox silently breaks a player; facades need
`EmbedLoader`; raw `<iframe>` in markdown stays unsanitised (pre-existing).

**Decisions (Jared 2026-10-05):** 1) yes — bare-URL auto-embed on for markdown fields, `autoEmbed: false` per field,
after the existing-content count. 2) yes — default `click_to_load`. 3) **(b)** — `add_embed` stages a suggestion you
approve. 4) yes — `embed` field type in v1. 5) yes — platform-wide cache. 6) yes — separate `podcast` kind.
**RenderersCore:** keep the renderer concept; it becomes the site-side component library (Form, Embed, link card;
later the privacy-policy table) — fix Page/Article's raw markdown `set:html`, move the peer to SDK ^4, cut a stable
release. **Fold RenderersCore into MarvinAstro (Jared 2026-10-05)** — `@inneropen/marvin-astro/components`; RenderersCore deprecated.

**Open questions:** 1) bare-URL auto-embed on for every markdown field, with a per-field `autoEmbed: false`? (rec.
yes, after the existing-content count) 2) default privacy mode? (rec. `click_to_load`) 3) `add_embed` writes directly
or stages a suggestion? (rec. stage) 4) `embed` field type in v1? (rec. yes) 5) cache platform-wide? (rec. yes)
6) separate `podcast` kind? (rec. yes)

# Form submissions: one entry per person (dedupe in Marvin) (plan, 2026-10-05)

**Goal:** a repeat form submission from the same person updates their existing entry instead of creating a
second one. Scope is Marvin only (Jared 2026-10-05: Buttondown was cleaned out; "no need to worry about dedups
unless they're in Marvin").

**Root cause:** `routes/publish/forms_controller.py::_submit_to_entry_type` always calls `EntryService.create`;
an entry type has no notion of a field that identifies the submitter. Effects today (latent — prod has 0 dupes):
a second `newsletter` entry per repeat signup; if the first was already confirmed, the new one sits in Inbox forever
(no second "confirmed" webhook); both carry the same `buttondown_subscriber_id`, so collections double-count.

## Design
1. **Config:** `SubmissionConfig.match_field: str | None` (e.g. `"email"`) — a field of the entry type's schema
   (validated on save). Off by default; the Buttondown signup blueprint's entry type sets it to its email field.
   Entry-type editor: "Same person = same …" select in Submission settings.
2. **Lookup:** before create, normalise the submitted value (trim; lower-case for email-format fields) and find an
   entry of that type in the workspace whose `data_json[match_field]` normalises to it (newest first; ignore
   deleted/trashed). SQLite JSON lookup through the shared entry query; index not needed at current volumes.
3. **On a match:** update that entry instead of creating:
   - merge the new non-empty field values into `data_json` (the match field itself unchanged);
   - `metadata_json.submission`: keep the first `received_at`, add `last_received_at`, `submission_count += 1`;
   - status: unchanged, except `archived` → `inbox` (someone who left and signs up again is a new signup intent);
   - fires `entry_updated` (not `entry_created`); the visitor sees the same success message/redirect — never
     reveals that they were already on the list.
4. **Suspicious submissions never touch an existing entry:** if submission protection flags it, create a new
   `needs_review` entry as today (spam can't overwrite a real person's record); its review reasons note
   "matches existing entry <id>".
5. **Event:** `form_submission_received` gains `duplicate: bool` and `existing_entry_id`, `previous_status`.
6. **Buttondown blueprint:** signup workflow condition skips duplicates whose previous status was `published`
   (already confirmed) — a re-opened (`archived` → `inbox`) or still-pending one runs subscribe again, which
   Buttondown answers idempotently. Bump the integration's version; "Update" on the card picks it up.

## Checklist
- [x] Schema + validation (`match_field` must be a schema field) + entry-type editor control
- [x] forms_controller: normalise + lookup + update-or-create; suspicious → always create
- [x] Event payload fields; event catalog/docs
- [x] Tests: repeat → one entry + count 2 + same status; published stays published; archived → inbox;
      case/whitespace variants match; different email → new entry; suspicious repeat → new needs_review entry;
      match_field unset → old behaviour; visitor response identical in all cases
- [x] Buttondown content: `match_field` on the signup type's suggested config + duplicate condition; tests; 0.6.0
- [x] Manual: forms page ("one entry per person") + whats-new
- [ ] Rollout: core CI-gated restart; Buttondown push; Update the signup workflow in both workspaces; set
      `match_field: email` on both `newsletter` types (API, Jared's token) and verify with a repeat test signup

**Open questions:** 1) re-open archived (unsubscribed) entries to Inbox on a repeat signup? (rec. yes)
2) merge new field values into the existing entry, or keep the original values? (rec. merge non-empty)

**Decisions (Jared, 2026-10-05):** 1) yes — a repeat signup re-opens an archived entry to Inbox; 2) yes — merge
the new non-empty field values into the existing entry.

**Build notes (2026-10-05):** no blueprint kind can set an entry type's submission settings (`entry_fields` only
appends fields), so Buttondown 0.6.0 suggests `match_field: email` in the signup-type parameter help, the signup
workflow's description and its README; the Rollout step still sets it through the API. Marvin has no email field
type, so "email-format" means the submitted value looks like an email address (submission protection's regex).
Entries are hard-deleted (there is no trash), so a deleted entry can't match.

# n8n integration (plan, 2026-10-04)

**Goal:** n8n becomes a first-class place Marvin hands work to and hears back from. A workflow step triggers an
n8n workflow with signed, expiring auth. Failures carry n8n-specific codes that the provider's error policy
handles (retry / review / notify). The step editor picks the workflow from n8n's own list, and the card can read
an execution's status. n8n reports results back through a Marvin incoming webhook, and a smart collection shows what
failed. Nothing is shaped around the 2026-09-13 inquiry-desk test (Jared: "it was just a test — don't code around
it or for it"). n8n acting on
Marvin stays plain HTTP plus a personal token (documented), not a custom node, in v1.

**Today (origin/develop `67ad0763`, SDK 0.4.0; 0.5.0 on `feat/error-policy` `229eda4`):**
- Marvin → n8n already works with generic webhooks. The inquiry desk uses `event_driven` webhook `1fc99f25…`
  (`form_submission_received` → `http://n8n.n8n.svc.cluster.local:5678/webhook/marvin/inquiry`, static header
  `X-Marvin-Hook`). There is also the `workflow` webhook type and its "Call webhook" step (`actions/webhook.py`:
  15 s, no retries, response body → `$steps.<id>.output.body`). Gaps: no signing (the header *is* the secret); no
  error `code` (the SDK 0.5 policy only applies to integrations); no workflow picker; no execution read-back.
- SSRF: the integration HTTP helper (`services/integrations/http_client.py::_guard`) refuses private, loopback,
  link-local and reserved hosts, re-checks redirects and has **no allowlist**. The in-cluster svc and
  `n8n-n8n.apps.ocp4…` (LAN IP) are refused; `https://n8n.iwobble.com` resolves to Cloudflare from the backend pod
  and `/healthz` returns 200 (checked 2026-10-04), so v1 uses that. The generic webhook paths are weaker: the `webhook` step is raw httpx; the event bus uses
  `requests`, which follows redirects. The only check is save-time, literal-IP only, `PRODUCTION=true` only
  (`schemas/group/webhook.py`). That is why the in-cluster webhook works today.
- n8n → Marvin already works with no code. **Personal tokens** (`marvin_tk_`, `get_current_user`) act as the user
  with no scopes, so the "log in every run, JWT lives 48 h" pattern in the n8n designs is out of date. **Incoming
  webhooks** + the `incoming_webhook` trigger are "run a Marvin workflow with data". Also
  `POST /api/ai/agents/{slug}/run`, `/api/ai/operations/{slug}/execute`, `/api/platform/entries`. Gaps: a personal
  token works in the user's *active* workspace (`BaseUserController.group_id`); MarvinMCP is stdio-only
  (`src/index.ts`), so n8n's MCP Client node can't reach it; `POST /api/automations/{id}/run` is ADMIN and takes no
  input.
- Core stores **one credential per integration**. `{{SECRET}}` args resolve for Run action + workflow steps
  (`arg_secrets.py`), not for event subscriptions. Integration step outputs are stored in run history as returned.
- n8n facts: live instance `ghcr.io/n8n-io/n8n:latest` (2.38.7 on 2026-09-13), ns `n8n`. The public API
  (`X-N8N-API-KEY`, `/api/v1`) has workflows and executions (list, get, stop, retry) but **no run endpoint** — the
  Webhook node is the trigger. Webhook node auth: None, Basic, Header, JWT (HS256 passphrase); no native HMAC check.

## Design
1. **Package `marvin-integration-n8n`** (repo `InnerOpen/marvin-integration-n8n`, local `MarvinIntegrationN8n`,
   module `marvin_integration_n8n`, slug `n8n`, category destination), copied from Buttondown's layout:
   `provider.py`, `content.py`, `auth.py`, tests with the stub `_Http`. Depends on `marvin-integration-sdk>=0.5,<1`.
   Raises `IntegrationError(code, retry_after)`; on a core without the error engine that is still a `ValueError`
   with `.code`, so `on_failure` steps read `${error.code}`.
2. **Connection.** Credential `api_key`: the n8n API key, **optional** (without it the connection is
   "webhook-only"). Config: `base_url` (required; webhook + API base, e.g. `https://n8n.iwobble.com` — reachable
   from the backend pod via Cloudflare, checked 2026-10-04); `editor_url` (optional, links people click; defaults
   to `base_url`);
   `webhook_prefix` (default `webhook`); `default_auth` (`jwt` | `header` | `hmac` | `none`, default `jwt`);
   `auth_header` (header mode, default `X-Marvin-Hook`); `timeout_seconds` (default 15, max 30);
   `allow_test_webhooks` (default false; permits `/webhook-test/`). `check()`: with a key
   `GET /api/v1/workflows?limit=1` (401 → "API key rejected"); without one `GET /healthz`.
3. **Actions.**
   - `trigger_workflow`. Args: `path` (Webhook node path; relative, no scheme/`..`/`?`/`#`); `method` (POST | PUT |
     GET, default POST); `data` (object); `entry_id`, `meta` (optional, in the envelope); `auth` (overrides
     `default_auth`); `secret` (a `{{N8N_WEBHOOK_SECRET}}` reference, required unless `auth: none`); `test` (bool,
     refused unless allowed). Body serialised once and sent as bytes, so the signed bytes are the sent bytes:
     `{"marvin": {entry_id, meta, idempotency_key, sent_at}, "data": {…}}`. Headers `X-Marvin-Idempotency-Key`
     (`ctx.idempotency_key(path, entry_id)`, stable across one retry chain) and `X-Marvin-Timestamp`. Auth: `jwt` =
     HS256, no dependency, claims `iss=marvin`, `aud=<path>`, `iat`, `exp=iat+60`, `jti=<idempotency key>`,
     `body_sha256`, as `Authorization: Bearer …` (n8n's JWT Auth credential checks it — nothing to code in n8n);
     `header` = `<auth_header>: <secret>`; `hmac` = `X-Marvin-Signature: t=<ts>,v1=<hex HMAC-SHA256 of "{t}.{body}">`.
     Returns `{ok, status_code, path, response (JSON or text ≤2000 chars), execution_id, execution_url}`; never
     headers, token or secret.
   - `list_workflows` (needs the key): filters `active` (default true), `tag`, `name`; follows `nextCursor` up to 10
     pages, `excludePinnedData=true`; projects to `{id, name, active, tags, webhooks: [{path, method, auth,
     respond_mode, production_url}]}` from `n8n-nodes-base.webhook` nodes. The picker: run it from the card.
   - `get_execution` (needs the key): `execution_id`, `include_error` (default true) → `{id, status, workflow_id,
     started_at, stopped_at, retry_of, url}`; with `include_error` only `lastNodeExecuted` + the error message
     trimmed to 300 chars. Execution data is never passed through.
4. **Error codes + policy** (provider policy; read actions override `"*"` with `Handle()`):

   | code | when | Handle |
   |---|---|---|
   | `auth` | 401/403 from a webhook or the API | notify, retry on recovery ×3, then review |
   | `not_found` | 404: webhook not registered (inactive workflow / wrong path) | notify, retry (5m, 30m), then review |
   | `rate_limited` | 429 (honour `Retry-After`) | retry (30s, 2m, 10m), then notify + review |
   | `unavailable` | connect refused, DNS, 502/503/504, 500 with a non-n8n body | retry (1m, 5m, 30m, 2h), then notify + review |
   | `timeout` | read timeout; n8n may have run it | review, **no retry** (avoids double runs) |
   | `workflow_error` | 500 with n8n's `{"message": …}` | review only (n8n's error workflow already alerts) |
   | `rejected` | other 4xx (a Respond to Webhook node said no) | review |
   | `blocked` | SSRF guard refused the host | notify |
   | `invalid` | bad args/config | notify |
   | `response_too_large` | reply exceeded `INTEGRATION_HTTP_MAX_BYTES` | succeed (the request landed) |
   | `*` | anything else | review + notify |
5. **Workflow picker (v1).** The `trigger_workflow` step's `path` is a dropdown fed by `list_workflows` (active
   workflows with a Webhook node: name, path, method, auth). Core adds a generic option-source hint for integration
   action inputs (e.g. `x-marvin-options: {action: list_workflows, value: path, label: name}`) that the step editor
   and the Run action form resolve through the connection. Free text stays allowed (webhook-only connections, a
   workflow not yet active). Generic, so other providers can use it.
6. **Content (all created off; nothing required).** No send-side blueprints: people add a `trigger_workflow` step
   to their own workflow and pick the n8n workflow from the list.
   - `incoming_webhook` `n8n`: where n8n reports results. Scheme `static_token`, header `X-Marvin-Token`, secret
     `N8N_CALLBACK_TOKEN`.
   - `workflow` `n8n-record-result`: trigger `incoming_webhook` `n8n`; condition
     `event.payload.marvin.entry_id exists`; `set_metadata` on `entity_id: $event.payload.marvin.entry_id` with flat
     keys (smart rules read only top-level metadata): `n8n_status` (`success` | `error` | `waiting`),
     `n8n_execution_id`, `n8n_workflow`, `n8n_finished_at`, `n8n_message`.
   - `collection` `n8n-failed` (suggestion, smart, private): `where metadata.n8n_status eq error` — smart
     collection, not a routing workflow.
   - `collection` `n8n-in-flight` (suggestion, smart, private): `where metadata.n8n_status in [sent, waiting]`.
7. **n8n → Marvin (docs + templates, no new code).** One Marvin user per workspace (e.g. `n8n`, EDITOR) + a personal
   token in an n8n Header Auth credential (`Authorization: Bearer marvin_tk_…`). HTTP Request nodes against
   `/api/platform/entries`, `/api/ai/operations/{slug}/execute`, `/api/ai/agents/{slug}/run`. Starting Marvin
   workflows with data: POST to a Marvin incoming webhook. Marvin agents calling n8n: n8n's MCP Server Trigger as a
   workspace MCP server (works today). Templates in `iWobble/n8n-workflows` `marvin/templates/`: "receive from
   Marvin" (Webhook with JWT Auth → Remove Duplicates on `X-Marvin-Idempotency-Key` → Respond to Webhook
   `{executionId: $execution.id}`) and "report back to Marvin" (HTTP Request → `/api/hooks/<token>` with
   `X-Marvin-Token` and `{marvin: {entry_id}, status, execution_id, workflow, message}`).
8. **Security / run history.** Secrets only as `{{SLUG}}` in stored args; the dry run shows the reference. The
   provider never puts the secret, the JWT or request headers in results, errors or logs (sentinel test). JWT is the
   default because n8n saves Webhook request headers in execution data (verify on 2.38): a 60-second JWT is useless
   once expired. Execution data is never copied into Marvin. The n8n API key should be read-only where n8n offers
   scopes (`workflow:read`, `execution:read`). The integration step stays ADMIN (`INTEGRATION_ACTION_MIN_ROLE`).

## Checklist
- [ ] Prereq: SDK 0.5.0 merged to develop + tagged (the init container installs the SDK `develop` tarball)
- [x] Core: option-source hint for integration action inputs (`x-marvin-options`), resolved through the connection
      in the step editor + Run action form, free-text fallback. Tests: hint resolves; connection error → free text
- [ ] Package scaffold from Template: pyproject (entry point `n8n = "marvin_integration_n8n:N8nProvider"`, SDK
      `>=0.5`), CI copied from Buttondown, ruff
- [ ] `auth.py`: HS256 JWT, HMAC signer, header mode. Tests: JWT verifies (PyJWT dev-only), `exp`/`aud`/
      `body_sha256` match sent bytes, HMAC format
- [ ] `trigger_workflow` + URL builder + envelope + idempotency header + status → code mapping. Tests: every code
      row (incl. `Retry-After`, URLError vs timeout, SsrfError, oversize), path validation, test-webhook gate,
      sent bytes == signed bytes, secret sentinel absent from result/message/logs
- [ ] `list_workflows` (projection, pagination cap, no pinned data) + `get_execution` (no data passthrough, trimmed
      error) + `check()` both modes. Tests with recorded n8n JSON fixtures
- [ ] `error_policy` + read-action overrides. Tests: registers, shows in `info()`, `resolve_policy` per code
- [ ] `content.py` blueprints (callback webhook, `n8n-record-result`, 2 smart collections). Tests: shape, parameters,
      `{{N8N_WEBHOOK_SECRET}}` survives `substitute`, smart rules use only top-level `metadata.<key>`
- [ ] E2E against a throwaway n8n 2.x (Docker harness from `n8n-workflows` `test/e2e`): JWT accepted and an
      **expired one rejected**; header mode; 404 for an inactive workflow; 500 body shape; executionId round trip
- [ ] Docs: package README; manual `integrations.md` row + "Workflows with n8n"; `whats-new/n8n.md`; settings row
      for the allowlist; `marvin-chart/README.md` plugin example; `INTEGRATIONS_PLUGIN_ARCHITECTURE.md`
- [ ] Rollout: `values-iwobble.yaml` tarball; restart; connect in `mash-burn-co` (`base_url` `https://n8n.iwobble.com`,
      key from pass); n8n JWT credential from a new `N8N_WEBHOOK_SECRET`; smoke on a throwaway n8n test workflow:
      pick it from the list → `trigger_workflow` → `n8n-record-result` writes metadata → entry shows in `n8n-failed`
      when forced to error
- [ ] Brain: update "n8n Workflow Designs" (personal token, JWT template) and "Marvin Integrations"

## Logos (folded in, Jared 2026-10-04)
Official marks instead of emoji, generic for every provider. The SDK only reads the file; core is the
security boundary (validates, caches, serves with a locked-down CSP).
- [x] SDK 0.6.0: `IntegrationProvider.logo: ClassVar[str] = ""` (path relative to the provider's package,
      `.svg`/`.png`, package data); `load_logo(provider) -> (bytes, content_type) | None` via
      `importlib.resources`; `info()["has_logo"]`; README (hatch/setuptools package data); tests
- [x] Core: on provider load read via `load_logo` (getattr-guarded for SDK 0.5), validate (≤ 64 KB; PNG magic;
      SVG: no DOCTYPE/ENTITY, `<script`, `<foreignObject`, `on*=`, non-`#` `href`/`xlink:href`, `javascript:`,
      non-`#` `url(`/`@import`; stdlib parse only after the DOCTYPE check), cache in memory, warn + emoji on reject
- [x] Core: `GET …/integrations/providers/{slug}/logo` — cached bytes, `nosniff`, `default-src 'none';
      style-src 'unsafe-inline'; sandbox`, ETag + cache header, 404 without a logo; catalog `has_logo` from core
- [x] Frontend: `<img>` on a white rounded tile (alt="", name beside it) on integration cards, the add list,
      admin Plugins, workflow step editor/picker; emoji on `has_logo: false` or image error
- Display rules (from the providers' brand guidelines): logo **≥ 32px tall** (Instagram's minimum is 29px); a
  **light/white tile in both themes** (OpenAI's mark is black-only, Buttondown's must sit on white or black);
  **`object-fit: contain`** with a wider box for wordmarks (Apprise is 2.4:1 → max-width 80px, not a forced
  square); **never larger or more prominent than Marvin's own branding** (card-sized is fine)
- [x] Tests: each validator rule + clean SVG/PNG; endpoint headers, 304, 404; SDK without `load_logo`
- [x] Docs: `INTEGRATIONS_PLUGIN_ARCHITECTURE.md`, manual integrations page, whats-new
- Built 2026-10-04 on `feat/n8n-core` (core) and `feat/logo` (SDK 0.6.0). Endpoint is
  `GET /api/groups/integrations/providers/{slug}/logo` (the controller's prefix), public; the frontend `/api`
  proxy now passes `X-Content-Type-Options` and `Content-Security-Policy` through. Not yet checked in a browser.

## Later
- Core: provider-scoped private-host allowlist (`INTEGRATION_HTTP_ALLOWED_PRIVATE_HOSTS`, `<provider>=<host>[:<port>]`,
  platform env only, metadata IPs always refused, redirects re-checked) — only if Marvin should use n8n's in-cluster
  address instead of `https://n8n.iwobble.com`.
- Core: same guard + allowlist for the `webhook` step and event-bus delivery (and no redirects in `requests`) —
  only after the allowlist lists the n8n host, or the inquiry webhook breaks.
- Core: outgoing-webhook signing (JWT/HMAC) for every webhook; `{{SECRET}}` in event-subscription args.
- `retry_execution` / `stop_execution`; a scheduled poll of `n8n-in-flight` via `get_execution`.
- `n8n-nodes-marvin` community node (credential `MarvinApi`, a Marvin Trigger that registers/deletes an
  `event_driven` webhook, operations from `/openapi.json`; verified nodes: no runtime deps, provenance via GH Actions).
- MarvinMCP streamable-HTTP transport (n8n MCP Client Tool → Marvin).
- Personal-token workspace header (`X-Marvin-Workspace`, membership-checked) and token scopes.
- DNS pinning in `_guard` to close the rebinding window.

**Risks:** n8n may keep request headers in execution data (verify on 2.38; JWT mitigates); n8n JWT `exp` enforcement
unverified (e2e is load-bearing); synchronous steps hold a worker up to `timeout_seconds` (blueprints use
respond-immediately + callback); a read timeout may mean n8n ran it (`timeout` → review + idempotency header);
`auth` retry-on-recovery can re-arm when only the webhook secret is wrong (capped at 3, then review); the allowlist
widens what every workspace's n8n connection may reach (Later item; fine single-tenant); requests go through
Cloudflare — the integration client's `marvin-cms/integrations` user agent passes its browser check, Python's
default one gets error 1010; waits on SDK 0.5.0 + the core error engine (until then codes only reach `on_failure`).

**Decisions (Jared 2026-10-04):**
1. Credential = optional n8n API key; webhook secret as a `{{N8N_WEBHOOK_SECRET}}` step arg.
2. Default auth `jwt`; `header` kept for existing `X-Marvin-Hook` setups.
3. Allowlist per provider, platform env only — moved to Later: `https://n8n.iwobble.com` is reachable from the
   backend pod (checked 2026-10-04: resolves to Cloudflare, `/healthz` 200), so v1 doesn't need it.
4. Guard the core webhook paths later, as its own change.
5. No n8n community node (a Marvin step inside n8n) in v1; HTTP Request + personal token covers it.
6. The inquiry desk was just a test: don't code around it or for it; workflows are added by picking from n8n's
   list. Jared removes the test outgoing webhook (`1fc99f25…`) once the integration's webhook replaces it.
7. `workflow_error` alerting is configurable: default review only; per-connection Review/Alert overrides per code
   (a core feature, built with integration-owned error handling).

# Integration-owned error handling (plan, 2026-10-04)

**Goal:** when an integration step fails, Marvin looks up the provider's declared policy for that error code
and applies it to any workflow using the integration — review the entry, retry with backoff, mark the
connection "needs attention" and alert admins, ignore/succeed, or a combination. A workflow's own `on_failure`
still wins. Run history shows the outcome. One deduped alert per connection+code, not one per item.
Admin alerts (Jared): bell always; email to workspace admins configurable; Slack and/or Apprise configurable.

**Today (origin/develop, SDK 0.4.0):** `actions/integration.py` copies `.code` into `AutomationActionError` and
drops partial progress; `engine.py` stops at the first failure, runs `on_failure`, fires `automation_failed`;
no retry store; connection `status`/`last_error` only from `check()`; other `run_action` callers
(IntegrationEventListener, capability, scheduled integration task) have no policy; Square/Buttondown errors
carry codes but providers declare no policy; Square `create_listing` is multi-call/non-atomic; close workflows
call Square before marking `checkout_closed`.

## Design
1. **SDK 0.5.0:** `IntegrationError(ValueError)` (`code`, `partial`, `retry_after`); `Retry(backoff, max_attempts,
   on_recovery)`; `Handle(review, notify, succeed, retry, then)`; `error_policy` on provider and per action
   (lookup: action[code] > provider[code] > action["*"] > provider["*"] > none); `ctx.resume` (last partial for
   entry+action) and `ctx.idempotency_seed` (stable across one retry chain); policy exposed in `info()`.
2. **Engine** (`services/integrations/errors.py::handle_failure`): executor raises `IntegrationStepError`
   (catch-all → `unknown`); `on_failure` present → run it, skip entry-level policy (connection notify still
   recorded); `succeed` → step success `{ignored, code}`, pipeline continues; `review` → `request_review` + core
   metadata `integration_error.<slug>` (no entry → notify); `retry` → upsert retry row; `notify` →
   open/bump alert; partial saved and passed back as `ctx.resume`, cleared on success. Run still `failed`
   unless all failures were `succeed`; `automation_failed` carries `handled`/`handling`.
3. **Retries:** table `integration_retries` (unique live row per automation+target+step; lease; backoff;
   `then`; snapshot of event + earlier outputs, never secrets; partial; seed). 60s system task claims due rows,
   rebuilds context from the current entry, **re-checks the workflow's conditions** (fail → superseded), resumes
   at the failed step (earlier steps never re-run), success → succeeded, failure → next backoff
   (`retry_after` honoured), exhausted → `then`. Parked rows re-arm when the connection recovers. A fresh run
   that passes the step supersedes a pending retry. Prune after 30 days.
4. **Connection health:** table `integration_alerts` (open row per integration+code; count; samples; reminder);
   card shows "Needs attention" + message + "N failures since …" + Resolve/Test. Resolves on successful
   `check()`, next successful action, or manual Resolve → `integration_attention_resolved`, re-arms parked retries.
5. **Alerts fan-out:** events `integration_attention_needed` / `_resolved` emitted only when an alert opens or on
   a reminder window (default 24h). Bell gets it via the event feed; "Integration alerts" panel on Settings →
   Integrations writes existing subscription rows: email admins (new system template), Slack `send_message`,
   Apprise `notify` with templated args. Loop guard: failed alert delivery never emits another alert.
6. **Non-workflow callers** (listener, capability, scheduled task): connection-scope notify only. Test-fire: none.
7. **Run history:** `automation_action_executions.handling`, `automation_executions.handled` + `retry_of_id`;
   messages like "failed — handled by Square: sent to review", "retry scheduled (2 of 3)", "succeeded on retry 2".

**Migration:** `integration_retries`, `integration_alerts`, `handling`, `handled`, `retry_of_id`.
**API/UI:** integrations list `attention`; resolve endpoint; `GET/PUT alert-routing`; execution schemas;
card badge + "How errors are handled" table; routing panel; toaster tones; run detail retry chain.

## Providers
- **Buttondown:** add `auth`, `unavailable` codes; policy blocked/spammy/suppressed → review; unavailable → retry
  (2m, 10m, 1h) then review; auth → notify + retry parked until recovery; `*` → review. Drop blueprint
  `on_failure` (already-applied copies remain as overrides).
- **Square:** auth/config → notify (close: retry parked ×10 then review; create: parked ×1); rate_limited →
  retry (1m,5m,15m,1h, honour retry_after) then notify; unavailable → retry (2m,10m,30m,2h,6h) then notify +
  review; conflict → retry (30s, 2m) then review; invalid → review; not_found → create: review, close: succeed;
  unknown → retry 5m then review + notify.
- **Square closing safely:** close workflows set `checkout_closed: true` + request rebuild **first**, then
  `close_listing`, then `square_link_closed: true`; conditions key on `square_link_closed != true`; durable retry
  covers unpublish/archive triggers that never re-fire.
- **Square partial progress:** create_listing order upsert → image → stock → **create new link → delete old
  link**; ids in `SquareError.partial`; `ctx.resume` reuses them (no orphan item, delete-old-link-only path);
  seeded idempotency keys within a retry chain.

## Checklist
- [ ] SDK 0.5.0 (error class, Retry/Handle, error_policy, resume/seed, info) + tests + release
- [x] Core migration + models
- [x] Core `errors.py` (resolution, handle_failure, alerts + dedupe)
- [x] Core executor (IntegrationStepError, resume/seed) + engine hook + recorder + summary messages
- [x] Core retry sweep (60s task, condition re-check, resume-at-step, supersede, parked, prune)
- [x] Core events/payload, system email template, loop guard, connection-scope callers
- [x] Core API + frontend (card badge, policy table, routing panel, toaster, run history)
- [ ] Buttondown policy + codes, drop on_failure
- [ ] Square policy, close reorder + `square_link_closed`, create_listing reorder + partial + resume + seeded keys
- [x] Docs (integrations.md, INTEGRATIONS_PLUGIN_ARCHITECTURE.md) — core side; provider READMEs are the provider passes'
- [x] Per-connection policy overrides (decision 7) + published entries are flagged, not reviewed (decision 8)

**Risks:** retries act on changed content (condition re-check is load-bearing); Square idempotency window
(~24h, unverified); a still-live link may sell even if the site hides it; automation_failed toast volume in an
outage; system templates used by real subscription rows unverified; first sub-5-minute system task.

**Decisions (Jared, 2026-10-04):**
1. A workflow's own `on_failure` still runs instead of the entry-level policy, but connection-level notify (the
   policy's `notify`) still fires.
2. Handled failures still emit `automation_failed` (with `handled` / `handling` in the payload); the toaster shows
   them as a yellow warning, red stays for unhandled.
3. Alerts follow the routing configuration (Settings → Integrations → Integration alerts). The reminder window is
   configurable there (default 24h). The "resolved" notice goes to every channel that delivered the alert, from
   the channels recorded on the alert row, not the current routing (a route turned off is disabled, not deleted,
   so it can still carry the resolved notice). The bell always gets both.
4. Per-workflow opt-out: a definition may set `integration_errors: "fail"` to skip provider policies for its steps
   (connection notify still fires, per 1). Validated with the definition schema; documented.
5. Square close zeroing stock as a backstop: provider work (Square pass), kept in this plan.
6. Show `integration_error.<slug>` on the entry page next to the review reasons notice, e.g.
   "Square · invalid — <message>".
7. (Added) Admins can adjust a provider's policy per connection: `integrations.error_overrides`
   `{code: {review?, notify?}}` (only those flags; retries/backoff/`then` stay the provider's), applied with
   `dataclasses.replace`; Review / Alert checkboxes with defaults and "reset to default" in the policy table.
8. (Added) `review` never unpublishes: a published entry keeps its status, gets `integration_error.<slug>` and the
   review reason ("<Provider> · <code> — <message>"), and the connection alert fires as if `notify` were set.
   Draft/new entries move to Needs review as planned.

**Build notes (core, 2026-10-04):** migration `c9e2f4a6b8d1`. The retry sweep runs on the scheduler's minutely
tick (`sweep_integration_retries`, leader only), not as a scheduled-task row: a task row's interval re-arms after
each run (so 60s fires about every 120s) and would log a row a minute. `error_overrides` is its own column on
`integrations`, not inside `config` (the provider's settings, which the provider receives and which its
config_schema validates). An untagged provider failure now has `code` "unknown" (`${error.code}` was empty).

**Review fixes (2026-10-04):** one retry budget per chain across codes (largest `attempts`, 24h cap; mixed/timed-out
chains without `then` → review + notify); `succeed` ignores `retry`; retries outlive deleted entries (no entry FK,
entry facts in the snapshot); sweep in a worker thread, ~40s per tick, one claim at a time, re-arms orphaned parked
rows; plain-failure exhaustion applies `then` or notifies; ≥60s between attempts; disabled workflows' retries wait;
reclaimed leases count; automation_failed only for a chain's first failure and its end; secrets redacted from errors.

**Later:** retry/alert metrics on the dashboard; pruning resolved alerts' samples sooner; a per-workflow
"retries" view.

# Integration alerts & health page (plan, 2026-10-05)

**Goal:** one admin page, **Settings → Integrations → Alerts & health**, that shows what integration error
handling is doing across the workspace: open alerts, pending retries (retry now / give up), recent handled
failures, alert history, where alerts go, and a per-integration health summary on top. Scope approved by Jared
2026-10-05: items 1–5 and 7; item 6 (per-integration overrides table) followed the same day (see the item 6 note below).

**Today (origin/develop `99723737`):**
- `integration_alerts` already stores how an alert ended: `resolution` (`check` | `action` | `manual`),
  `resolved_at`, `resolved_by`; reminders are `notified_at` + `group_preferences.integration_alert_reminder_hours`
  (a reminder goes out on the next failure after the window, not on a timer). Resolved alerts and finished retries
  are pruned after 30 days.
- `integration_retries` live rows are `pending` / `parked` / `running` (lease 5 min). `errors.claim_next` selects a
  due row and then writes `running` by primary key, so a concurrent write in between would be overwritten.
- Run history: `automation_action_executions.handling` (`{code, provider_name, summary, applied, retry{id, …}}`),
  label `<integration slug>.<action>`; `automation_executions.handled` / `retry_of_id`.
- Nothing records an integration's last successful call (only `last_checked_at` / `status` from `check()`).
- UI: the routing card (`IntegrationAlertsPanel`) sits on Settings → Integrations; each connection card shows
  **Needs attention** with Test / Resolve. Workflows deep-link with `/automation/workflows?workflow=<id>`, no run id.

## Design
1. **Service** `services/integrations/health.py` (SDK-free queries, so its tests run without the SDK): open /
   resolved alerts (paged), live retries, retry-now, give-up, handled failures (paged), health summary.
2. **API** on the integrations controller, every route `require_workspace_admin` first and filtered by
   `group_id` (another workspace's id → 404): `GET /alerts?status=open|resolved&page&per_page`, `GET /retries`,
   `POST /retries/{id}/retry-now`, `POST /retries/{id}/give-up`, `GET /handled-failures?since&page&per_page`
   (default the last 7 days), `GET /health`. No secrets: rows carry the stored (already redacted) messages only;
   no snapshots, partials, seeds or samples beyond what the card already shows.
3. **Retry now** = one conditional `UPDATE … SET status='pending', next_attempt_at=now WHERE id AND group AND
   status IN (pending, parked)`; 0 rows → 409 (running or finished). The sweep runs it on its next tick, never the
   request. **Give up** = the same conditional update to `superseded` (clears `live_key`, `finished_at`, reason
   "given up by an admin"), nothing else applied (no `then`). A running row is refused unless its lease has run
   out. `claim_next` becomes a conditional update too (skip the row if it changed since it was selected), so an
   admin's give-up can't be overwritten by a claim.
4. **Handled failures:** step rows with `handling` set joined to their run; a line like "Square · rate_limited —
   retried, succeeded on retry 1" from the retry row's current status when it still exists, else the stored
   summary. Links: run (`/automation/workflows?workflow=<id>&run=<exec>`, the page opens that run) and entry.
5. **Alert history:** resolved alerts, open for how long (`resolved_at − first_at`), how (manual + who / passing
   check / successful action). No migration needed for this.
6. **Health summary:** per integration — last successful action (new `integrations.last_success_at`, stamped by
   `connection_succeeded` for actions, every caller), last check (time + status + error), failed workflow steps in
   7 days, open alerts badge, live retries.
7. **Frontend** `pages/workspace/settings/integration-health.astro`: SSR with Astro JSX (no innerHTML of server
   strings), `adminOnly` via the existing 403 handling, stacked cards on mobile, empty states, Prev/Next paging via
   query params; **Where alerts go** reuses `IntegrationAlertsPanel` unchanged. Linked from the Integrations page
   header and a Settings → Integrations link card that replaces the routing card.

**Migration:** `integrations.last_success_at` (batch mode, nullable).

## Checklist
- [x] Plan (this section)
- [x] Migration + model `last_success_at`; `connection_succeeded` stamps it
- [x] `claim_next` conditional claim
- [x] `health.py` service + schemas + controller routes
- [x] Tests: shapes, scoping (other workspace → 404/absent), admin-only (gate list), retry-now / give-up incl.
      leased/running rows, pagination; skip API tests without the SDK
- [x] Frontend page + `lib/integrationHealth.ts` (+ node test), API client, links (Integrations header, Settings
      card), workflows `&run=` deep link
- [x] Docs: manual integrations page (+ glossary), what's new
- [x] Verify: full suite with and without the SDK, `npm test`, biome on touched files, `astro check` at 51

**Build notes (2026-10-05):** migration `d5b1e8a3c7f2` (`integrations.last_success_at` only; item 4 needed none).
Wording follows the run history: "Retry 2 of 5", "retried, succeeded on retry 1" (the spec's "attempt n of max"
counts the same thing; `max_attempts` is the number of retries). Retry now also un-parks a parked retry. Give up
records `last_error` "given up by an admin" (status `superseded`). The 7-day failure figure counts failed workflow
steps (and ignored ones) only. Verified: backend suite 2460 passed / 5 skipped with SDK 0.6.0 (develop tarball),
2182 passed / 175 skipped without; `npm test` 326 pass; biome clean on touched files; `astro check` 51 errors
(baseline); live check against a seeded SQLite backend + `astro dev` (render, escaping, paging, links, both levers).

**Item 6, overrides table (2026-10-05):** an **Error handling** section on the page: one row per connection ×
code that differs from the provider's default (logo, code, default summary + Review/Alert, this connection's
Review/Alert checkboxes, **Reset**), **Show all codes** to list and change every declared code, saved per connection
through `PUT /{id}/error-overrides` (the whole set, Reset = without that code). No new endpoint: the page already
loads the provider catalog (`errorPolicy`), and `GET /groups/integrations` (admin-only, workspace-scoped) carries
`error_overrides`; `connectionPolicies()` in `lib/integrationPolicy.ts` reuses the card's `policyRows`. Verified:
backend suite 2575 passed / 178 skipped (no SDK; no backend change); `npm test` 345 pass; biome clean; `astro
check` 51 (baseline); live check on SQLite + SDK 0.6.0 (develop) + n8n provider + `astro dev` (filter, show all,
check → save, reset, uncheck back to default, escaping, empty state, 390px stacked cards, no horizontal scroll).
- [x] Per-integration overrides table on this page (item 6)

## Later
Counting non-workflow failures (event subscriptions,
capabilities, scheduled tasks) in the 7-day figure; live refresh; filters by integration.

# Audit toggles — choose what the Event Log records, per workspace (plan, 2026-10-05)

**Goal:** a workspace admin decides which event types land in the Event Log, on top of the catalog default
(`CatalogEntry.audited`). Security events always land and can't be switched off. The Event Log page's
**Audit coverage** panel reads the API instead of a hand-kept mirror of the three non-audited types.

**Today (origin/develop `349974e4`):** `AuditLogListener.get_subscribers` skips an event whose catalog entry has
`audited=False` (scheduled_task_triggered, scheduled_task_started, webhook_task); everything else, and anything
without a catalog entry, is audited. `events.astro` mirrors that list by hand, read-only.

## Design
1. **Storage:** `group_preferences.audit_overrides_json` — `{event_type: bool}`, only the types that differ from
   the catalog default (the `submission_protection_json` / `integrations.error_overrides` pattern: a JSON override
   map on the owning row). Not on the preferences Read/Update schemas, so the lock can't be bypassed through
   `PATCH /groups/{id}/preferences`. Migration: one nullable column (batch mode).
2. **Locked:** `CatalogEntry.audit_locked`, set after the catalog like the `_NO_EMITTER` gate: every entry in
   Members, Authentication, Workspaces (incl. `workspace_settings_changed`, which records the audit change
   itself), Security and Secrets, plus the API client events (`api_client_*`, token rotation included).
3. **Service** `services/events/audit_settings.py`: rows for the API, validate + apply a change set, and
   `is_audited(group_id, event_type)` for the listener — locked or uncatalogued → audited; overrides cached per
   workspace (short TTL, dropped on write); any read error → audited.
4. **API** `/api/groups/audit-settings` (active workspace): `GET` (ADMIN/OWNER) every catalog type with
   `{event_type, name, category, default_audited, audited, locked}`; `PATCH` (ADMIN/OWNER) `{overrides: {type:
   bool | null}}` (null = default; unknown type 422; locked type 409); `GET /excluded` (any member) the types
   not recorded, for the read-only panel. A change dispatches `workspace_settings_changed`
   (`changed_fields: ["audit_overrides"]`), audited and locked.
5. **Frontend:** the panel loads the API: admins get switches by category, a filter box, locked rows marked,
   **Reset** where overridden, the excluded count in the summary; everyone else the read-only excluded list.
   Rows stack under 640px. Shown even when the log is empty.
6. **Docs:** manual Event Log section + what's new.

## Checklist
- [x] Plan (this section)
- [x] Catalog `audit_locked` + migration + model column
- [x] Service (cache, fail-safe) + listener uses it
- [x] Controller + schemas; change dispatches `workspace_settings_changed`
- [x] Tests: listener honours override/default, locked can't be disabled (API + listener), role gates, the change is
      logged, cache invalidation, uncatalogued/unknown types, migration up/down on SQLite
- [x] Frontend panel + `lib/auditSettings.ts` (+ node test) + API wrapper
- [x] Docs: manual Event Log + what's new; `mkdocs build --strict`
- [x] Verify: backend suite (no SDK), `npm test`, biome, `astro check` vs baseline 51, SDK gate regeneration

**Review (2026-10-05):** built as designed, plus `approval_*` among the locked types (a person authorising or
refusing an AI tool call). 117 catalog types, 34 locked. Uncatalogued types (`user_authenticated`, `role_assigned`,
`permission_changed`…) stay audited. A live check turned up one side effect, now fixed: `workspace_settings_changed`
always queued a site rebuild, so each switch did too. `SiteRebuildReactionListener.UNSEEN_SETTINGS` skips a change that
only touches `audit_overrides`. Things that read the log lose a switched-off type too (toasts, dashboard activity, dry-run
samples, site rebuild status); the manual says so. Verified: backend suite 2618 passed / 178 skipped without the SDK and
2921 / 5 with SDK 0.6.0 (develop); new tests also pass on Postgres 16; migration `e6c2a9f4b1d3` up/down/up on SQLite and
Postgres; `npm test` 356 pass; biome clean on touched files; `astro check` 51 (baseline 51); `mkdocs build --strict`
clean. Live on SQLite + `astro dev` + headless Chromium: switch off/on, Reset, round trip back to the default, locked
rows, filter + empty state, reload persistence, viewer read-only list (API 403), 390px stacked rows with no horizontal
scroll, no console errors. SDK gate reproduced (fresh 3.12 venv, `marvin[dev]` + integration SDK develop, `npm run
generate`): origin/develop gives no drift; this branch adds 2 paths / 3 schemas. Those types are committed on
MarvinSDK `feat/audit-settings-types`, which has to reach marvin-sdk develop before the gate passes here.

## Later
Bulk "reset all"; showing per-type event volume next to each switch, to pick what to silence.

# Admin events — platform events leave the workspace Event Log (plan, 2026-10-05)

**Goal:** Jared: "the events should not include any sort of admin events so we should probably have an events page
on the admin settings". Sign-ups, workspace creation and the other platform events land in a workspace's Event Log
today (they carry that workspace's id). They move to a super-admin **Events** page; the workspace log shows only
what happened in the workspace.

**Unchanged:** storage and dispatch. Platform events keep their `workspace_id` (context on the admin page), the bus
fires the same subscriptions, webhooks and workflows. Only what's shown and toggled changes.

## Design
1. **Catalog scope:** `CatalogEntry.scope: "workspace" | "platform"` (default workspace), set by a gate after the
   catalog like `_NO_EMITTER`. Platform: the Authentication category (sign-up, profile, password reset, token
   refresh), workspace lifecycle done by a platform admin or a user's own switching (`workspace_created`,
   `workspace_updated` (only the admin controller emits it), `workspace_deleted`, `workspace_activated`), personal
   API tokens, the platform security events (rate limit, failed logins, suspicious activity) and platform backups.
   `workspace_activated` and `token_refreshed` are dispatched and audited but uncatalogued: catalogue them.
   `PLATFORM_EVENT_TYPES` / `is_platform_event()` are derived from the catalog.
2. **One filter:** `workspace_events_clause()` beside `EventLogRepository`; its workspace reads
   (`get_by_workspace`, `get_by_entity`, `get_by_user`) always apply it, and the readers that query the model
   directly (dashboard activity, workflow dry-run samples) use the same clause. Single-event reads 404 a platform
   event.
3. **Audit settings:** platform entries are `audit_locked` (always audited) and leave the workspace audit settings
   (GET list and `/excluded`); PATCH answers 422 "not a workspace event".
4. **Admin API** (`AdminAPIRouter`, super admin): `GET /api/admin/events` — platform events across workspaces,
   newest first, paginated (`page`, `perPage`), filters `eventType`, `workspaceId`, `startDate`, `endDate`; each
   row with workspace name/slug and the user's name/email. `GET /api/admin/events/{event_id}` (payload) and
   `GET /api/admin/events/catalog` (platform types for the filter).
5. **Admin page** `/admin/events` (Operations nav + an Overview card): server-rendered filter form (GET query
   string), a log table styled like the workspace Event Log with Workspace and User columns, lazy payload,
   prev/next. Rows stack as cards under 640px.
6. **Workspace Event Log page:** audit panel copy no longer lists sign-in/tokens as workspace security events;
   lead line says platform events are on the admin page.
7. **Docs:** manual Event Log + new admin Events section, what's new.

## Checklist
- [x] Plan (this section)
- [x] Catalog scope + new entries + derived set
- [x] Shared filter; every workspace reader of the log uses it
- [x] Audit settings exclude/refuse/lock platform types
- [x] Admin API + schemas
- [x] Tests: scope classification, workspace log/feed/entity/user/single event, dashboard, dry-run samples, AI
      tools exclude platform types; audit settings; admin endpoint (super admin only, owner 403, filters,
      pagination); platform events still dispatched and stored
- [x] Admin page + nav + overview card; workspace page copy
- [x] Docs: manual + what's new; `mkdocs build --strict`
- [x] Verify: backend suite (no SDK), `npm test`, biome, `astro check` vs baseline, SDK gate + MarvinSDK types,
      live check

**Review (2026-10-05):** built as planned, no migration. 19 platform types: the Authentication category (incl. the
newly catalogued `token_refreshed`), `workspace_created/updated/deleted` and the newly catalogued
`workspace_activated`, `api_token_*`, `api_rate_limit_exceeded`, `login_failed_multiple_times`,
`suspicious_activity_detected`, `backup_*`. `workspace_updated` qualifies because its only emitter is the admin
workspace controller (a test pins that). Readers filtered: the log list and its filters, single event (404), entity
and user history, the feed (toasts), dashboard activity, dry-run samples (list/default/by event id/by entry), AI
tools `list_events` / `get_entity_history` (MCP reaches them through the tool registry). Not touched, reviewed:
`site_controller._newest` and the embeddings-reindex lookup read fixed workspace types; maintenance pruning and
workspace purge delete, not read. One live find, fixed: on a phone the card layout's `display:block` beat the closed
payload rows' `hidden`. Verified: backend 2648 passed / 178 skipped without the integration SDK, 2951 / 5 with SDK
develop; `npm test` 366 pass; biome clean on touched files (AdminLayout's import order is pre-existing); `astro
check` 50 (baseline 50); `mkdocs build --strict` clean (with CI's generated `openapi.json`). Live on SQLite +
`astro dev` + headless Chromium: the workspace log shows only `variable_created` while the admin page lists
token_refreshed, two workspace_activated, a password reset and workspace_created with workspace and user columns;
type and workspace filters, an empty future range with Clear, a junk query string ignored, payload on expand, the
Overview card and nav highlight; 390px with no horizontal scroll (payload open too); no console errors. SDK gate
reproduced (fresh 3.12 venv, `marvin[dev]` + integration SDK develop, `npm run generate`): origin/develop gives no
drift against marvin-sdk develop; this branch adds 3 paths / 4 schemas, committed on MarvinSDK
`feat/admin-events-types`, which has to reach marvin-sdk develop before the gate passes here.

## Later
Show who changed a workspace in `workspace_updated` / `workspace_created` (the admin controller passes no user_id);
redact `reset_url` from stored password-reset payloads.


# Events hub — see what sends an event and what reacts to it (plan, 2026-10-06)

**Status:** plan reviewed by Jared 2026-10-06 ("everything else looks fine"), with "installed by" widened to every
blueprint-created row. Slices 1–5 built; slice 6's core part (`describe_event`) built, SDK methods / CLI left.

**Goal (Jared 2026-10-06):** events are a central feature, so each event should show its whole story in one place —
what sends it, everything that reacts to it (however it was connected), and when it last happened. Today the Events
catalog only knows about three kinds of connection, so integrations look disconnected even when they're not. And the
"who listens to what" data shouldn't be duplicated across tables: one fact, one place, joined when read.

**Today:**
- One `dispatch()` runs a fixed list of listeners (`event_bus_service.py:154`). Each listener decides for itself, from
  its own storage, whether it cares — nothing central records "X listens to Y".
- Where each connection lives:

  | Connection | Stored as | Joinable? |
  |---|---|---|
  | Integration actions | `integration_event_subscriptions` (event_type column, FKs) | yes |
  | Emails | `email_event_subscriptions` (event_type column, FKs) | yes |
  | Outgoing webhooks | `webhook_urls.subscribed_events` JSON list | no |
  | Workflows | `workspace_automations.definition` JSON → `trigger.event` | no |
  | Built-in reactions (site rebuild, indexing, embeds, smart collections) | code: each listener's own event set | n/a |

- The Events catalog (`automation/events.astro`, `events/[type].astro`) only reads the first three rows plus webhooks,
  so workflows — and with them every integration, which installs **workflows** through blueprints
  (`services/blueprints/apply.py`) — never show as connected. Live example: `entry_published` shows nothing, but runs
  Buttondown "email an issue when published" (both workspaces), "Summarize published bench notes" (M&B) and queues a
  site rebuild; `entry_updated` runs three Square workflows on Grace's workspace.
- Workflows don't record which integration installed them (only the name prefix tells).
- The workflow engine loads **every** enabled workflow per event and matches in Python
  (`engine.run_automations_for_event`), because the trigger is inside JSON.
- "Which events" is listed in several places that can drift: the catalog (`enabled`, `audited`, `_NO_EMITTER`,
  `_PLATFORM_SCOPE`), the workflow trigger allowlist (`automation/triggers.py` `TRIGGER_EVENT_GROUPS`), the
  `emit_event` allowlist (`actions/emit_event.py` `SITE_EVENTS`), and the built-in listeners' own sets.
- Production data is clean (no orphaned subscriptions; both subscription tables cascade on delete) — this is a design
  fix, not a data repair.

## Design

**Principle:** each fact stored once, in a real column or table; anything that combines them is a query, not a copy.
API shapes stay the same, so the SDK, CLI, MCP and the sites don't break.

**1. Normalise the two JSON stores (migrations, no UI change)**
- Webhooks: new `webhook_event_subscriptions` (webhook_id FK cascade, event_type; unique pair) — the same shape as the
  email and integration tables. Backfill from `subscribed_events`, then drop the JSON column. The webhook API still
  reads/writes `subscribedEvents` (the repository maps it), and the webhook listener queries the table.
- Workflows: the trigger moves out of `definition` into columns — `trigger_type` (event, incoming_webhook, manual,
  mcp, chained, on_error, …), `trigger_event` (indexed, nullable), `trigger_ref` (incoming webhook slug / chained
  workflow id). `definition` keeps conditions and actions only. The API still accepts and returns
  `definition.trigger` (assembled by the schema), so the builder, SDK and blueprints don't change. Backfill parses
  every existing trigger, including the old `{event: …}` shape without a `type`.
- The engine then selects only the workflows whose `trigger_event` matches — less work per event.
- "Installed by" on **everything a blueprint creates** (Jared 2026-10-06): `source_integration_id` (FK to
  integrations, SET NULL) + `source_blueprint` (the blueprint key) on workflows, scheduled tasks, incoming webhooks,
  integration event subscriptions and collections — set in one place, `blueprints/apply.py`. NULL means a person made
  it. `entry_fields` blueprints add fields, not rows, so they're out. Blueprints themselves (templates shipped in the
  integration packages) don't change, and neither does the integration SDK. Backfill: match existing rows to the
  workspace's installed integration by blueprint slug, then by name prefix; leave NULL when unsure. Later this lets
  uninstalling an integration list (or clean up) exactly what it added.
- Not doing: one big polymorphic `subscriptions` table. Each connection has different settings (recipients, args,
  payloads) and real FKs; separate same-shaped tables + one query keep both.

**2. One catalog (code, no migration)**
- The catalog becomes the single list of event facts. New `CatalogEntry` fields replace the side lists:
  - `triggerable` (replaces `TRIGGER_EVENT_GROUPS`; the builder's dropdown groups by category),
  - `emittable` (replaces the `emit_event` allowlist),
  - `sent_by`: short human lines for Marvin's own senders, e.g. "Publishing an entry (editor, API, CLI, AI tool)".
- Built-in reactions declare themselves: each hard-coded listener exposes `reacts_to` (the set it already matches on)
  and a label ("Queues a site rebuild"). Its matching uses that same set, so the label can't drift from behaviour.
- `leads_to` on entries that cause other events (entry_published → site_rebuild_queued → webhook_triggered →
  site_deployment_*), for the chain view.
- Tests: every dispatched `EventTypes` member has a catalog entry; every entry with a sender has `sent_by` (or is in
  `_NO_EMITTER`); every `leads_to` target exists; triggerable/emittable match what the engine and action accept.

**3. One lookup: `services/events/connections.py`**
- `reactions(group_id, event_type)` — one UNION query over integration subs, email subs, webhook subs and workflow
  triggers (each row: kind, id, name, enabled, managed-at link, installed-by integration), plus the built-in
  reactions from code.
- `senders(group_id, event_type)` — Marvin's own `sent_by`, workflows whose actions emit it or request a rebuild
  (scanned from the workspace's workflows: a few dozen rows, no stored copy), incoming webhooks that start those
  workflows, scheduled tasks.
- `recent(group_id, event_type, limit)` — from the Event Log (workspace scope; types not audited have no history, and
  the page says so).
- `summary(group_id)` — per event type: counts of senders and reactions, for the catalog list in one call.
- API (any member reads; same workspace scoping as the catalog): `GET /api/platform/events/connections` (summary) and
  `GET /api/platform/events/{type}/connections` (senders, reactions, recent, leads_to). Platform-scope events are
  excluded here and get the same view on the admin Events page.

**4. UI**
- Event page (`/automation/events/{type}`) in three parts: **Sent by** · **What happens** · **Recent**, plus the chain
  ("leads to …"). Connections made elsewhere show as subscribed, read-only, with a link to where they're managed
  (workflow, integration) and an on/off state. The Subscribe menu keeps webhooks, emails and integration actions, and
  adds "**+ New workflow on this event**" (opens the builder with the trigger filled in).
- Catalog list: the dot counts real connections in both directions; the chip tooltip names them.
- Workflows page: "Installed by Square" badge from `source_integration_id`.
- Admin Events page: the same "Sent by / What happens" panel for platform events.

**5. Events cleanup (decided by Jared 2026-10-06, built in slice 5 — see the decisions under its review)**
- `webhook_triggered`: label "Site Rebuild Sent", category Publishing (internal name stays — webhooks subscribe to it).
- Never-sent types: webhook_created/updated/deleted, webhook_delivery_succeeded/failed, api_token_* — wire them up or
  hide them. api_token_* matter most (security, currently locked as "always audited" but never fired).
- `site_build_*` vs `site_deployment_*`: keep one family; the other becomes an alias so existing workflows keep
  working.
- Security types with no feature behind them: hide until built.

**6. Everything else that reads these**
- SDK: regenerate types (new connections endpoints; webhook/workflow shapes unchanged). CLI: `marvin events show
  <type>` (senders, reactions, recent). MCP/AI: a `describe_event` tool so Marvin can answer "what happens when I
  publish?". Docs: manual Events section + what's new.

## Checklist
- [x] **Slice 1 — storage:** webhook subscriptions table + workflow trigger columns + "installed by" columns on all
      five blueprint-created tables (set by `blueprints/apply.py`); backfill +
      downgrade; listeners and engine read the new storage; API shapes unchanged (contract tests on webhook and
      workflow read/write); migration tested up/down/up on SQLite and Postgres 16; prod backfill dry-run against a copy
      of `marvin.db` (counts before = after)
- [x] **Slice 2 — one catalog:** `triggerable`, `emittable`, `sent_by`, `leads_to`; built-in listeners declare
      `reacts_to`; side lists removed; drift tests
- [x] **Slice 3 — connections service + API:** reactions/senders/recent/summary; role + workspace scoping tests;
      platform events excluded; SDK Quality Gate
- [x] **Slice 4 — UI:** event page (three parts + chain), catalog dots, "+ New workflow on this event", Installed-by
      badge, admin panel; live check incl. 390px
- [x] **Slice 5 — cleanup:** Jared picked all four items (decisions below); plus the email-template override's own
      variable list and `name`/`category` on the connections summary rows
- [ ] **Slice 6 — SDK/CLI/MCP/docs:** core part done (`describe_event` AI/MCP tool + docs; SDK types regenerated with
      slice 5). Left: SDK methods for the new endpoint, CLI `marvin events show <type>`
- Each slice ships on its own (CI-gated rollout); slice 1 first, since everything else reads its storage.

## Open questions for Jared
1. Built-in reactions (site rebuild, indexing, smart collections, embeds): show them as a muted "Built-in" line?
   (Proposed: yes.)
2. ~~Section 5 cleanup: which items, and `site_build_*` or `site_deployment_*` as the family to keep?~~ All four;
   `site_deployment_*` kept (Jared 2026-10-06; see the slice 5 decisions).
3. "+ New workflow on this event" in the Subscribe menu — yes?
4. Workflows installed by an integration: may they be switched off from the event page, or only on the workflow /
   integration page? (Proposed: link only, so the event page never fights the integration that owns them.)
5. Slice order OK (storage first), or UI first on top of today's storage and normalise after?
6. The Emit event step accepts every `entry_*` type, including `entry_shared` (nothing else sends it) and
   `entry_type_*` (which get an entry payload). Narrow `emittable` to the entry lifecycle events, or keep it?
   (Slice 2 kept it as it was; the builder offers only the 23 subscribable ones.)

## Later
- **`media_embed_failed` event** (Jared 2026-10-06, "if it's important" — low priority): today a link the embed
  resolver can't turn into a player (private/removed video, unsupported host, provider down) silently renders as a
  plain link on the site; nothing tells the editor. Dispatch `media_embed_failed` (entry, url, provider, reason) from
  the media-embed cache warm-up, catalogue it (Content, triggerable, sent_by "Warming the media-embed cache"), so a
  workflow, email or Slack action can flag it. No retry storm: once per URL until it changes.

## Slice 1 review (2026-10-06, branch `feat/events-storage`)

**Built.** Migrations `cba7c23b692e` (webhook subscriptions table + workflow trigger columns) and `1dbc9b51d024`
("installed by" on the five blueprint-created tables), both with a working downgrade.
- Webhooks: `webhook_event_subscriptions` (unique webhook+event, indexed event_type, cascade). The model's
  `subscribed_events` is a property over the rows, so the API, seed loader and exporter still speak `subscribedEvents`.
  `WebhookEventListener` and `site_rebuild.deploy_targets` are joins now.
- Workflows: `trigger_type` / `trigger_event` (indexed) / `trigger_ref` / `trigger_config`; the `definition` column keeps
  the rest. `trigger_event` is what the trigger listens to — `incoming_webhook` / `automation_ran` / `automation_failed`
  for those three types — so "what reacts to X" is one column. `WorkspaceAutomationModel.definition` / `.trigger` are the
  one accessor pair (assemble on read, split on write); engine, dry-run samples, AI tools, schedule sync read them. The
  engine selects by `trigger_event` in SQL; `_trigger_matches` still settles the slug/target.
- `source_integration_id` + `source_blueprint`, set only in `blueprints/apply.py` (`installed_by()`), read-only on the
  five Read schemas (SDK types regenerated: MarvinSDK `feat/events-storage-types`).

**Departures from the plan (Jared's call if any matters):**
- A 4th column, `trigger_config`, holds what the other three can't (a schedule's `schedule_type`/`schedule_config`,
  extra keys) — without it a schedule trigger would lose its interval.
- `trigger_type` is nullable: NULL means "no trigger" (the API accepts `definition: {}`); making it NOT NULL would invent
  a trigger. Every production row has one.
- API shape changes, all normalisations: an untyped `{"event": X}` trigger reads back with `"type": "event"` (2 prod
  rows, both "Summarize published bench notes"); `subscribedEvents` reads back sorted and de-duplicated, and `[]`
  instead of `null` (2 prod rows, the `entries` webhooks).
- Backfill name-prefix matching needs `"<Provider>: "` with the colon, so "n8n ping" / "n8n pong received" stay NULL.

**Verified.** Backend 2703 passed / 178 skipped (develop 2648/178; +55 new in `tests/test_events_storage.py`), with
the integration SDK 3006/5 (develop 2951/5), Postgres 16 2704/177; migration up/down/up with every trigger and webhook
shape on SQLite and Postgres 16 (+ PG downgrade-to-base cycle); prod dry-run: counts equal before/after, all 25
workflows' trigger columns as expected, 34 rows matched to their integration by blueprint slug (18 workflows, 5
incoming webhooks, 8 collections, 2 scheduled tasks, 1 Slack subscription), rest NULL; downgrade gave back the original
JSON except the normalisations above. API responses diffed against develop: only the changes listed. SDK gate clean
after regenerating. Frontend untouched (tree identical to develop): 439/439 tests, astro check 51 errors (= develop).

**Found, not fixed:** on Postgres the `webhookmode` enum lacks `workflow`, so creating a "workflow" webhook 500s there
(SQLite prod unaffected). Needs an `ALTER TYPE … ADD VALUE` migration.

## Slice 2 review (2026-10-06, branch `feat/events-catalog`)

**Built.** `services/events/event_catalog.py` is the one list of event facts. New `CatalogEntry` fields:
`triggerable` (+ `trigger_group`, the builder's heading where it isn't the category: Entries, Collections,
Entry types, Resources, Site), `emittable`, `sent_by` (96 entries — every one not in `_NO_EMITTER` — written from
the dispatch sites; workflow-sent events are slice 3's), `leads_to` (24 entries: the 20 events the site-rebuild
reaction takes → `site_rebuild_queued`; the 6 indexed-on events → `ai_embeddings_reindexed`; `site_rebuild_queued`
→ `webhook_triggered`; `scheduled_task_triggered` → started/completed/failed). Derived: `TRIGGERABLE_EVENT_TYPES`,
`EMITTABLE_EVENT_TYPES`, `trigger_groups()`, `offered_emittable()`.
- Removed: `services/automation/triggers.py`, emit_event's `SITE_EVENTS`, the builder's own `SITE_EVENTS`
  (`AutomationOptions.emittable` replaces it — the one API change, additive; MarvinSDK `feat/events-catalog-types`).
- Built-in reactions: `BuiltinReaction` gives the five hard-coded listeners (scheduled tasks, AI search, media
  embeds, site rebuild, smart collections) a `label` and `reacts_to()`, and one `get_subscribers` matching on it.
  `builtin_reactions(event_type)` → [(label, class)] for slice 3.
- Tests: `tests/test_event_catalog_facts.py` (dispatched types are catalogued, sent_by honest both ways, leads_to
  targets exist and match the reactions that cause them, triggerable == what the automation listener takes,
  emittable == what emit_event accepts, each reaction reacts to exactly its declared, catalogued set). The first
  commit also asserted every derived set equal to a snapshot of the retired list; the second dropped those
  literals once proven.

**Same behaviour, checked old vs new** (listener sweeps over every `EventTypes` member, emit_event dry runs, the
options endpoint): triggerable 41, emit_event accepts 24, emit menu 23, subscribable 90, the five reaction sets
(1/11/3/20/6) and the automation listener's 44 — all identical.

**Decided with Jared's coordinator (2026-10-06) and done:**
- Every dispatched type is catalogued: `automation_ran` / `automation_failed` (Automation) and
  `email_template_created/updated/deleted` (Connect), all `enabled=False` and `audit_locked=True` — exactly as
  before (an uncatalogued type was always audited and never subscribable). The drift test has no exceptions.
- "Secrets" and "Variables" are in `CATEGORIES`; a test checks every entry's category is listed.
- One internal-events set: `CatalogEntry.internal` (webhook_task, scheduled_task_*) → `INTERNAL_EVENT_TYPES`, read
  by EventBusService's dispatch logging and the console listener (the two copies are gone).
- Builder order follows the catalog; `form_submission_received` moved to the top of the Forms entries.
- emit_event left as is; open question 6 above.

**Visible differences (intended):**
- `/event/types` (the Events catalog) lists 90 instead of 84: the 6 secret_* / variable_* events now show. Forms
  starts with Form Submission Received.
- Event Log settings list 105 rows instead of 100: the 5 newly catalogued types, as locked ("always recorded");
  Secrets and Variables now sort by their place in `CATEGORIES` instead of last.
- Builder menus follow catalog order — same events, same headings: groups Entries, Collections, Entry types,
  Resources, Assets, Forms, Site (was …, Assets, Resources, Forms, Entry types, …); inside groups, Site lists
  deployments before builds, Collections lists collection_* before entry membership, Forms keeps
  `form_submission_received` first but lists `submission_surge_detected` last.
- An admin Events row for an email template now shows its catalog name.

**Verified.** Backend 2725 passed / 179 skipped (develop 2704/179), with the integration SDK 3028/6 (develop
3007/6); SDK gate reproduced twice in a fresh venv — only `AutomationOptions.emittable` changes. Frontend:
`npm test` 439/439, `astro check` 51 errors (= develop), biome clean on the touched page.

## Slice 3 review (2026-10-06, branch `feat/events-connections`)

**Built.** `services/events/connections.py`, read-only, nothing stored:
- `reactions()`: one UNION ALL over integration actions (+ integration), emails (+ template), event-driven webhooks,
  workflows (`trigger_event`) and the system email templates, then the built-in reactions. Switched-off rows are
  listed with `enabled=false`; `enabled` is decided the way each listener decides (`_runs`), including the email
  rule for invitation / password reset / welcome: the system template sends unless the workspace connects its own
  template of that type, and while it sends, other subscriptions on that event don't. Each row: kind, id, name,
  enabled, detail (action / "To the workspace admins" / trigger ref), triggerType, managedAt, installedBy. No URLs,
  headers, args, tokens or addresses.
- `senders()`: the catalog's `sent_by`, then the workspace's workflows whose steps send it (Emit event; a task step
  such as Request Site Rebuild → `site_rebuild_queued` + `webhook_triggered`; entry steps), the incoming webhooks
  that start such a workflow (one hop; every incoming webhook also sends `incoming_webhook`), and scheduled tasks
  whose type sends it, system tasks included. Two small declarations make that honest: `OP_SENDS` beside the entry
  step's ops, and `ScheduledTaskHandler.sends` (publish/unpublish scheduled entries, request site rebuild, reindex);
  tests run each op and task and compare.
- `recent()` (Event Log, workspace scope, the caller's AI-run visibility) + `audited`; `leads_to` / `caused_by`.
- `summary()`: per workspace-scope type `senders`, `reactions`, `activeReactions`, `builtinReactions`,
  `lastOccurredAt` — 6 queries whatever the number of types (one grouped query for every stored reaction).
- API: `GET /api/platform/event-types/connections`, `GET /api/platform/event-types/{type}/connections?limit=`,
  `GET /api/admin/event-types/{type}/connections` (super admin: senders, built-in + system email, each workspace's
  own reactions grouped by workspace, newest events across workspaces). 404 for unknown types and for the other
  scope's types. SDK: types regenerated + `events.getConnectionsSummary()` / `events.getConnections(type)`
  (MarvinSDK `feat/events-connections-types`).

**Departures (Jared's call):**
- Paths: `/api/platform/event-types/…`, not `/api/platform/events/…` (that prefix has `/{event_id}`).
- Guard: workspace OWNER/ADMIN, not every member. The catalog page is admin-only, and every list it draws on
  (workflows, webhooks, email subscriptions, integrations) refuses members; this API names all of them. Easy to
  widen if members should see it.
- Entry steps, incoming webhooks → `incoming_webhook`, task types and system tasks as senders go beyond the brief's
  emit / rebuild examples; all are real code paths and tested.
- Not listed (payload-dependent): an `integration_attention_resolved` notice also reaching the routes that delivered
  its alert; `webhook_task` posting scheduled webhooks; workflow conditions; `run_automation` /
  `run_integration_action` tasks; chains longer than incoming webhook → workflow.

**Production, read-only** (non-secret columns copied into a scratch SQLite at head, then deleted): summary equals
detail for all 105 types in both workspaces. Grace: `entry_updated` runs the three Square workflows and is sent by
eleven workflows (Buttondown, Square, "Turn on Sell online"); `webhook_triggered` → "Rebuild Site" webhook, sent by
five Square workflows' rebuild steps; `site_deployment_completed` ← "Cloudflare Pages: deployed" (Emit event) via
its incoming webhook. M&B: `entry_published` → Buttondown issue + "Summarize published bench notes" (+ Slack, off);
`form_submission_received` → Buttondown signup workflow, the notification email and the "n8n inquiry desk" webhook.
**Found, not fixed:** M&B's "CloudFlare Rebuild Hook" is event-driven with no subscriptions (as before slice 1), so
its 13 logged `webhook_triggered` reached nothing.

**Verified.** Backend 2771 passed / 179 skipped (develop 2725/179; +46 in `tests/test_event_connections.py`), with
the integration SDK 3074/6; the new tests on Postgres 16: 46/46. SDK gate reproduced in a fresh venv: only the new
paths and schemas; MarvinSDK lint, `tsc --noEmit`, 185/185 tests.

## Slice 4 review (2026-10-06, branch `feat/events-ui`)

**Built** (frontend only; the connections API from slice 3 through `fetchApi`, not the unreleased SDK methods):
- Event page (`automation/events/[type].astro`): **Sent by** (Marvin's lines; workflows with what step sends it;
  incoming webhook → workflow hop with a link to the workflow; scheduled tasks), **What happens** (every reaction by
  kind: workflows, integration actions, emails, webhooks, then the muted built-ins; On/Off badge on each; emails,
  webhooks and integration actions connected here keep Edit/Disconnect; workflows, the system email and anything with
  `installedBy` are read-only with an **Installed by <integration>** badge and an Open link; the system email row says
  whether Marvin's own email sends), **Recent** (rows open `/workspace/events?event=<id>`; audited off → "This event
  isn't recorded in this workspace's Event Log" + link to `#audit-coverage`), and **Caused by / Leads to** chips.
  **Subscribe ▾** opens a menu of what can still be connected: **+ New workflow on this event** (only when the builder
  options list the type as triggerable), unconnected event-driven webhooks, unconnected templates, + integration action.
  `#subscribe` opens it (the catalog's Subscribe buttons link there).
- Catalog list: one `GET /api/platform/event-types/connections` replaces the three client-side lists. Filled dot =
  something reacts, ring = every reaction switched off, "Not sent" = nothing sends it (legend shows that item only
  when a listed type has it; none does today); the row tooltip counts both directions + built-ins + last seen;
  category counts use the summary.
- Builder: `?trigger=<type>` opens a new workflow on that event if it's triggerable, then drops the parameter.
- Workflows page: **Installed by <integration>** badge (name from the integrations list, "an integration" when the
  list is unavailable; blueprint key in the tooltip).
- Admin Events: filtering by a type (or clicking a row's type) shows a panel with Sent by / What happens (platform
  reactions, then each workspace's own, grouped) and the chain; the filtered log below is its Recent.
- Event Log: `?event=<id>` highlights and expands that row (or says it's older than the 100 shown);
  `#audit-coverage` opens that section.
- Platform events off the workspace side (Jared 2026-10-06, after review): `GET /api/event/types` skips
  `scope == "platform"`, so the Events list, the event page (a platform type's link redirects to the list), the
  webhook / email / integration pickers and the email template page offer none of the 7. Workflow triggers and
  Emit event never offered them (now tested). Marvin's welcome / password-reset / invitation emails still send with
  no subscription (tested per template). OpenAPI unchanged (the filter is in the body), so no SDK change.
- Shared: `lib/eventConnections.ts` (types, grouping, managed-here rule, dot state, tooltip, dates, links,
  `?trigger=` parsing) + `components/events/ConnectionRow|ConnectionGroup|ConnState.astro`.
  Server strings only through Astro JSX / textContent; the event page's integration modal now builds its options
  as DOM nodes too.

**Departures (Jared's call):**
- The Subscribe "menu" opens inline under What happens rather than as a popover (works the same at 390px).
- Admin panel has no separate Recent list: the type-filtered log under it is that.
- Also fixed on the way: workflow card buttons wrapped at 390px (3px horizontal scroll before).

- The email template page's welcome / password-reset override (a workspace template on `user_signup` /
  `user_password_reset_requested`) is still there, but those events no longer appear in its event list or variable
  hints. Production has no such override. Removing the override path (or keeping it with its own variable list) is
  open.

**Verified.** `npm test` 454/454 (develop 439; +15 in `lib/eventConnections.test.mjs`); biome clean on the 11
touched/new files; `astro check` 51 errors / 69 hints (= develop); `mkdocs build --strict` clean. Backend:
3078 passed / 6 skipped with the integration SDK (0.6.0), 2775 / 170 without (+4 in
`tests/test_event_connections.py`: workspace pickers and triggers offer no platform type; the three system emails
send with no subscription); ruff clean; OpenAPI identical to develop. Live on SQLite
+ `astro dev` + headless Chromium (integration SDK + Slack plugin in the worktree venv so the integrations list
answers), seeded with a Buttondown-installed workflow on entry_published, own workflows on entry_updated (one off),
a webhook on webhook_triggered, an email subscription, an incoming webhook → Emit event workflow, entries
published/updated, `collection_created` audited off. As workspace admin: entry_published / entry_updated /
webhook_triggered / site_deployment_completed / collection_created / user_signup pages as described; catalog 5
active dots; **+ New workflow on this event** → builder with Event / entry_published set → saved, listed on the event
page; absent on webhook_triggered; Recent → Event Log row expanded; Audit coverage link opens it; Workflows badge
"Installed by Buttondown". After hiding platform types: the list shows 83 types and none of the 7,
`/automation/events/user_signup` and `/workspace_created` redirect to the list, the new-webhook picker offers none.
As super admin: `/admin/events?type=user_signup` and `workspace_created` panels. No
console errors, no 4xx/5xx, no horizontal scroll at 390px; light + dark. Screenshots in the job's
`events-ui-shots/`.

**Found, not fixed:** `PATCH /api/platform/entries/{id}` to `published` 500'd once in seeding — `EntryRead`
validation got bare UUIDs in `collections` (an entry joining a smart collection during the same request?).
Pre-existing, backend.

## Slice 5 review (2026-10-06, branch `feat/events-cleanup`)

**Decisions (Jared 2026-10-06; production checked the same day: nothing uses site_build_*, site_published,
webhook_created/updated/deleted, webhook_delivery_*, api_token_*, api_rate_limit_exceeded,
login_failed_multiple_times or suspicious_activity_detected; `webhook_triggered` has one subscription — Grace's
"Rebuild Site" deploy hook — and 43 Event Log rows):**
- `webhook_triggered` → display name **Site Rebuild Sent**, category Publishing, described as the signal deploy hooks
  listen to; internal name unchanged.
- Wire up `webhook_created/updated/deleted` (outgoing-webhook routes; name, type, switch, subscribed events, who —
  never URL or headers) and `webhook_delivery_failed` (once per delivery after retries; webhook, event carried, HTTP
  status or error kind — never URL, headers or body). Hide `webhook_delivery_succeeded` (noise; the webhook's
  activity log covers it).
- Wire up `api_token_created/rotated/revoked` from the personal-token routes (platform scope, audit-locked; name, id,
  owner — never the token or hash).
- `site_published`: hidden (no sender).
- `site_build_*` → aliases of `site_deployment_*`: never offered, triggerable or emittable; triggers, Emit event
  steps (and subscriptions) naming one are stored and read as the counterpart; data migration for stored ones; old
  API inputs keep working.
- Security types with no feature (`api_rate_limit_exceeded`, `login_failed_multiple_times`,
  `suspicious_activity_detected`): hidden until built, enum members kept, still platform scope + audit-locked.
- Email override of system emails: keep it, presented as "Replaces Marvin's … email" with its own variable list
  from the catalog, served by its own endpoint (not by re-listing platform types).

**Built.**
- Catalog: `CatalogEntry.alias_of` + `ALIASES` / `canonical_event_type` / `aliases_of`; `CatalogEntry.hidden`
  (`HIDDEN_EVENT_TYPES` = `_NO_EMITTER` ∪ aliases). Hidden types are left out of `/api/event/types`, Audit coverage
  (`/api/groups/audit-settings`), the admin Events filter (`/api/admin/events/catalog`) and the connections summary,
  and the connections detail answers 404 (workspace and admin).
- Senders: `webhook_controller` (`EventWebhookConfigData`), `WebhookPublisher` (`EventWebhookDeliveryData`; error is
  "HTTP 503" or the exception's class name because requests quotes the URL; a webhook on `webhook_delivery_failed`
  failing doesn't announce itself), `api_token_controller` (`EventAPITokenData` + `user_name`).
- Aliases: `WorkspaceAutomationModel` normalises the trigger and Emit event steps on write and on read; the engine
  also matches a row still holding an old `trigger_event`; Emit event accepts an old name and emits the counterpart
  ("Site deploy …"); webhook / email / integration subscription models store the counterpart. Migration
  **`011f6c720d1d`** rewrites stored triggers, steps and the three subscription tables (a webhook already on the
  counterpart keeps one row); idempotent; downgrade is a no-op.
- Email override: `GET /api/platform/workspaces/{id}/email-templates/system-emails` (OWNER/ADMIN): per system email
  its event, label, recipients, `systemSends`, `replacedBy` (from `connections.system_email`, the event page's `_runs`
  rule) and the catalog entry's variables. The template page shows "Replaces Marvin's welcome email" with a "Send this
  template instead" switch (saved as the email subscription with the system email's recipients) and a note on what
  sends now; the system template's page says Sending / Replaced; the hard-coded map copy in the page is gone.
- Coordinator add-on: connections summary rows carry the catalog `name` and `category` (for the CLI).
- `describe_event` (slice 6 core): registry tool, ADMIN, `automation_read`, agent + MCP; event type or hint →
  senders, reactions (built-ins, installed-by), leads_to / caused_by, last occurred; workspace events, platform
  events for super admins only; hidden / platform names asked by a workspace caller get a reason, not a guess.
- Drift tests: the hidden set is spelled out; every shown type has a `sent_by`, every hidden one none and isn't
  offered; aliases point at shown, triggerable, emittable types and nothing sends an alias.

**Departures / Jared's call:**
- Hiding is global: besides the cleanup's types, the other never-sent ones (comments, backups, storage quota,
  user_updated/deleted, …) also left Audit coverage and the admin Events filter (they were listed there, switchable,
  though never written). Audit coverage lists 90 workspace types now (was 105); the admin Events filter 10 platform types.
- Deleting a personal token sends `api_token_revoked` too (it stops working); switching one off through PATCH
  `enabled=false` sends nothing — say if that should count as revoked.
- Aliases also cover webhook, email and integration subscriptions (save + migration), not only workflows.
- `webhook_delivery_failed` is sent for scheduled and Test sends as well (same publisher); not for a workflow's
  Webhook step (its failure is the run's `automation_failed`).
- The Event Log's message title for `webhook_triggered` stays "Webhook Triggered" (titles come from the enum name for
  every event); the activity toast has its own "Site rebuild" label.
- `entry_shared` is hidden but the Emit event step still accepts it (open question 6).

**Verified.** Backend 2822 passed / 179 skipped without the integration SDK (develop 2777/179), 3125 / 6 with it
(develop 3080/6); new and touched event tests on Postgres 16: 116/116. Migration up/down/up with old-name rows
(trigger, Emit event steps, duplicate webhook rows, email and integration subscriptions) on SQLite and Postgres 16.
SDK gate reproduced (fresh venv, `pip install -e .[dev]` + integration SDK): only the new endpoint, `SystemEmail*`
schemas and the summary's `name`/`category` — MarvinSDK `feat/events-cleanup-types`; lint, tsc, 185/185 tests,
build. Frontend `npm test` 454/454, biome clean on touched files, `astro check` 51 errors / 69 hints (= develop);
`mkdocs build --strict` clean. Live (SQLite + astro dev + headless Chromium, as workspace admin): the Events list has
84 types and none hidden, Site Rebuild Sent under Publishing; `/automation/events/site_build_completed` and
`/webhook_delivery_succeeded` send back to the list; a welcome template's switch on → off → on, each saved and
reflected on Marvin's own welcome template (Sending / Replaced), variables from the catalog; password reset shown off;
no console errors, no 4xx/5xx, no horizontal scroll at 390px, light + dark. Screenshots in the job's `cleanup-shots/`.

# Settings breadcrumbs — one trail on every admin and settings page (plan, 2026-10-06, design approved by Jared)

**Goal (Jared 2026-10-06):** every admin and workspace settings page shows where it sits the same way: one trail of
its ancestors above the title, built from one map, instead of four home-made styles.

**Today:** 67 in-scope pages (`pages/admin`, the non-content pages of `pages/workspace`, `pages/automation`,
`pages/publishing`) use four styles: `components/Breadcrumb.astro` (16 pages), hand-made `<div class="breadcrumb">`
(12: scheduled-task pages, Ask, AI Executions, Event Log, webhook log, event type pages), "Back to …" buttons
(integrations, alerts & health, AI pages, users/new, groups/[id], entry-types/[id], API clients) or nothing (most
admin pages, secrets, environment). The eyebrow above the H1 reads "Settings", "Workspace", "Workspace Settings",
"Settings · Integrations", "Automation", "Events", "Publishing", "Workspaces" or (admin) always "Admin". Trails point
at the settings hub's tabs in some places and at pages in others. Content pages (entries, assets, collections,
resources) don't use `Breadcrumb.astro`, so the component can go.

## Design
- **One trail, rendered by the layout** in place of the eyebrow: the page's ancestors, each a link; the H1 is the
  current page. Under 640px it shows only the parent ("‹ Email"). `<nav aria-label="Breadcrumb">` + `<ol>`.
- **One map:** `frontend/src/lib/navTree.ts` — every node `{id, label, href, parent, title?}`; `label` is the
  short name (crumb, sidebar), `title` the H1 when it differs. Detail pages are nodes with a route-pattern href
  (`/admin/users/[id]`); the page passes its dynamic `title` (and `crumbParams`/`crumbLabels` when an ancestor is
  dynamic — only the event type → webhook page). Pages declare `crumb="settings.email.smtp"`.
- **Roots:** Admin (`/admin`) and Settings (`/workspace/settings`) only. Automation and Publishing pages sit directly
  under Settings (Jared 2026-10-06: "just consistent"): they're tabs of the settings hub, not pages, and every crumb
  is a link to a real page — so no tab-based roots. Sidebar group names
  that aren't pages ("People & access", "Operations") are not crumbs. Root pages (Admin overview, the settings hub,
  the workspace dashboard, Create Workspace) have no trail.
- **Readers of the map:** AdminLayout's sidebar takes its hrefs and labels from it (same groups, icons, look); the
  settings hub's cards take their hrefs and titles from it (descriptions stay in the hub).
- **Removed:** per-page `<Breadcrumb>`, hand-made breadcrumb divs and their CSS, "Back to …" links, eyebrow props.
  Kept: form Cancel buttons, in-page tabs. `components/Breadcrumb.astro` retired.
- **Guard:** `lib/navTree.test.mjs` — every in-scope page declares a `crumb` that exists and whose href is that
  page's route; no page renders its own breadcrumb, back link or eyebrow; every parent exists, no cycles, hrefs
  unique, every href resolves to a page file.

## Checklist
- [x] Plan (this section)
- [x] `navTree.ts` + trail builder; layouts render the trail (desktop + phone, light + dark)
- [x] Admin pages: crumbs, old breadcrumbs/back links out; sidebar reads the map
- [x] Settings / automation / publishing pages: crumbs, old breadcrumbs/back links/eyebrows out; hub cards read the map
- [x] Retire `Breadcrumb.astro`
- [x] Node test
- [x] Docs: manual (navigation) + what's new
- [x] Verify: `npm test`, biome on touched files, `astro check` vs baseline, live check as super admin and workspace
      admin (every in-scope page, links, no 404s, no console errors), screenshots at desktop and 390px

**Review (2026-10-06):** built as designed. 67 pages declare a crumb (66 nodes have one page each; Automation and
Publishing link to the hub tab). H1s come from the map unless a detail page passes its own; two changed:
"Workspace Members" → "Members", "Workspace Invites" → "Invitations". Hub card titles now match their destination's
H1 ("Manage Entry Types" → "Entry Types", "Scheduler" → "Scheduled Tasks", "Site Clients" → "API Clients", …;
"Notifications" kept its name). Ask stays under Settings although it's also a top-level sidebar link. Removed: 16
`<Breadcrumb>`, 12 hand-made trails + their CSS, 13 Back links (incl. error-state ones); the event webhook page's
"Back" beside Connect became "Cancel". One live find, fixed: Astro's scoped selectors made the phone "‹" lose to the
desktop "›" rule. Verified: `npm test` 439 pass (73 new); biome clean on new files, no new findings on touched ones;
`astro check` 51 errors (baseline 51); `mkdocs build --strict` clean (with a generated `openapi.json`). Live on
SQLite + `astro dev` + headless Chromium: super admin 69 pages (all static nodes + 11 detail pages), workspace admin
48; every trail matches the map, every trail link (18) answers 200, no old breadcrumbs or eyebrows, no console
errors; 390px shows only the parent with no horizontal scroll, light and dark.

# Storage plugins + backup targets — cloud storage leaves core (plan, 2026-10-06, Jared: "everything uses the same APIs")

**Status:** all 8 slices approved by Jared (2026-10-06); slices 1–3 merged and in production since revision 28
(`develop-f83140e`) — see "Review (slices 1–3)" below; slice 4 merged and live too ("Review (slice 4)"). Slice 5:
the plugin is on GitHub (`InnerOpen/marvin-storage-s3`, public, `main`, CI green) and installed in dev with slice 6.
Slice 6: **dev cut over** (2026-10-06, `r2` target hourly, legacy job off, restore test green); **production pending
the coordinator's promotion** of the same chart change — see "Review (slice 6)". Slice 8: **code built and
tested** (admin choice of upload provider, `storage_migrate`, redirects, backups of R2 assets), no environment
switched — see "Review (slice 8)" and the runbook `docs/manual/assets-on-r2.md`.
Decisions below are Jared's (2026-10-06), open questions answered the same day.

**Goal (Jared 2026-10-06):** keep core lean. Cloud SDKs leave core, and storage becomes a site-wide plugin type the
same way AI providers will (see "AI provider plugins" above). Core keeps the local disk and a backup engine that can
write to a second local volume (the NAS). One generic S3-compatible plugin covers R2, AWS, MinIO and B2, for asset
storage and backups alike. Backups go to a **list of targets**, each on its own schedule and retention (e.g. hourly
to R2, nightly to the NAS), and R2 backups must not stop at any point during the switch.

**Today:**
- `services/storage/`: `BaseStorageProvider` (put/get/delete/exists/get_public_url/get_metadata, no `list`),
  `LocalStorageProvider`, `S3StorageProvider` (boto3) and `get_storage_provider()`, which picks one by the
  `STORAGE_PROVIDER` string (`local` | `s3`, settings `STORAGE_LOCAL_*`, `STORAGE_S3_*`, `STORAGE_REMOTE_PUBLIC_URL`).
  Every environment runs `local` (`marvin-data` PVC, 516 assets in production).
- `boto3` is a **core dependency** (`pyproject.toml`). Its only users are `s3_provider.py`,
  `scripts/offsite_backup.py` and `tests/test_offsite_backup.py`.
- The asset row has a `storage_provider` column, but reads mostly ignore it: `AssetRead.compute_public_url` and
  most callers (about 20 `get_storage_provider()` call sites) use the one global provider. Only the download
  endpoint (`assets_controller.py:205`) branches on the row, and it returns 409 when the row says `local` and the
  global provider isn't local. So **a mix of local and s3 rows can't be served today**.
- `S3StorageProvider.get_public_url` without `STORAGE_REMOTE_PUBLIC_URL` returns `<endpoint>/<bucket>/<key>`. On R2
  that's the private S3 API, which browsers can't read. Assets on R2 need a public URL (custom domain), presigned
  URLs or a backend proxy.
- `scripts/offsite_backup.py` (739 lines) is S3-only. It does a consistent DB snapshot (SQLite backup API +
  `integrity_check`, or `pg_dump` + `pg_restore --list`), a config archive (`.secret`, `scheduler_state.json`,
  `templates/`), an incremental `assets/` mirror (size + MD5/ETag, never deleted remotely), sha256 metadata,
  `list` and `restore`. Retention is `select_retained` with 14 daily + 8 weekly, plus 48 hourly for `postgres/`.
  Its `Bucket` class is already a small put/get/list/delete seam.
- Chart: one CronJob `marvin-offsite-backup` (`backup.*`: schedule, timeZone, existingSecret, s3Region, prefix).
  Production (CNPG `marvin-pg`) runs it hourly to `marvin-backups`, dev (`marvin-dev`, `marvin-dev-pg`) hourly to
  `marvin-backups-dev`. Retention is hard-coded in the script. The job uses `podAffinity` onto the backend's node
  (RWO data PVC).
- Plugins: integrations are discovered from `marvin.integrations` (`services/integrations/loader.py`, which keeps a
  per-distribution load report with versions). They're installed by the `install-integrations` init container
  (`values-iwobble.yaml`: `pip install --target=/plugins …` + `PYTHONPATH`), and that runs **only in the backend
  pods. The backup CronJob gets no plugins.** The admin Plugins page exists (`/admin/plugins`,
  `services/plugins.py`, `PluginKind = "integration" | "ai_provider"`, with only integrations wired). The plugin SDK
  (`marvin-integration-sdk`) is **not** a core dependency: it comes in through the init container, from a branch
  tarball.

## Design

**1. Shared site-wide plugin plumbing (built here first, reused by AI provider plugins)**
- One entry-point loader in core (generalised from `services/integrations/loader.py`). Per plugin type it takes a
  group name and a register function, and keeps the resilient per-distribution load report (name, version, ok, error).
  A broken plugin is logged and skipped. New group: `marvin.storage_providers`.
- The plugin contract lives in the SDK, so **core takes the SDK as a pinned dependency** (today it's only present
  through the init container). Core re-exports the contract from `marvin.services.storage`, so existing imports keep
  working. The init container then stops installing the SDK from a branch tarball: a `PYTHONPATH` copy shadows the
  image's pinned one, and that's version skew waiting to happen.
- Admin Plugins page: kind `storage`. It lists each installed storage plugin with its version, what it provides
  (asset provider, backup target) and whether the platform uses it (the active `STORAGE_PROVIDER`, configured targets).
- Chart: a first-class `plugins.packages` list renders **one** install init container + `plugins` emptyDir +
  `PYTHONPATH` into every pod that runs Marvin code: the backend (split and combined), and **each backup CronJob**.
  The raw `initContainers` value stays as an escape hatch. Production and dev move their package list to
  `plugins.packages`.

**2. Storage contract (SDK) + registry (core)**
- SDK `storage` module: `StorageProvider` (today's `BaseStorageProvider` plus `iter_keys(prefix)`, which the backup
  engine needs to mirror assets from any provider), `StorageMetadata`, `BackupTarget`
  (`put_file(key, path, metadata)`, `get(key, dest) -> metadata`, `list(prefix) -> {key: TargetObject}`,
  `delete(keys)`, `head(key)`), and `TargetObject` (key, size, digest + algorithm, metadata). A plugin's entry point
  returns a `StoragePlugin`: slug, name, the provider and/or target classes, and a settings model (which env vars or
  values it reads, with secrets masked).
- SDK conformance kit: a pytest suite any storage plugin runs against its own provider and target (round trip,
  missing key → `FileNotFoundError`, list by prefix, delete idempotent, metadata/digest survives). Core runs the same
  kit on its built-in local provider and local target.
- Core registry: the built-in `local` provider is always registered (the **mandatory default**); plugins add theirs
  by slug. `get_storage_provider()` resolves `STORAGE_PROVIDER` through the registry. If the slug is unknown (plugin
  not installed), **startup fails with a clear message**. It never falls back to local quietly, because that would
  hand out broken asset URLs.
- **Per-row resolution:** `provider_for(asset)` resolves the row's `storage_provider`. It's used by
  `compute_public_url`, the download endpoint, delete and AI context reads. New uploads still go to the active
  provider. This lets local and s3 rows be served side by side, so the asset move doesn't need a freeze.

**3. Backup engine in core (built-in `local` target)**
- `services/backup/` + `python -m marvin.scripts.backup {run,list,restore,prune} --target NAME`. A port of
  `offsite_backup.py`'s logic (snapshot, `pg_dump`, config archive, sha256, incremental assets, restore), with
  `Bucket` replaced by `BackupTarget`. **Same key layout** (`postgres/`, `sqlite/`, `config/`, `assets/`, optional
  prefix), so the new s3 target can read and prune the existing R2 history. No re-seed, and history isn't lost at
  cutover.
- Built-in `local` target: a directory on a mounted volume (NAS export, second disk). Writes go to a temp file +
  `rename` (atomic within the directory, also on NFS). sha256 and metadata sit in a `<key>.meta.json` sidecar. The
  asset mirror compares size + sha256 instead of S3 ETags.
- Assets are read through the storage provider (`iter_keys` + `get`), not `DATA_DIR/assets`, so backups keep
  working once assets live in R2.
- **Targets are independent:** one CronJob per target, each with its own dump, run, exit code and alert. A failing
  NAS never stops the R2 run, and the other way round.
- **Retention per target, admin-configurable, default 30 days:** keep the hourly knob from today's rule and change
  the default to `keepHourly: 48, keepDaily: 30, keepWeekly: 0` ("30 days, hourly for the last two"). Today's rule is
  48 + 14 + 8 weekly, which reaches about 8 weeks back, so the new default trades the oldest weeks for daily points
  over a month (open question 2). The other existing rules stay: counted among backups that exist (a run of
  failures never empties a target), prune only after a successful upload, never touch `assets/` or keys the engine
  didn't name.
- **Guardrail, in code too:** the local target refuses a root inside `DATA_DIR` or on the same filesystem
  (`st_dev`) as `DATA_DIR`. Caveat for the docs: the NAS export and `managed-nfs-storage` share one ZFS pool on
  `192.168.30.10`. That copy protects against a deleted or corrupted PVC and app bugs, but not against losing the
  NAS. R2 is the off-site copy.

**4. Chart: `backup.targets[]`**
- Each entry has `name`, `type` (`local` | `s3`, or any plugin target slug), `schedule`, `timeZone`, `retention`
  (`keepHourly/keepDaily/keepWeekly`), `prefix`, and type-specific settings. `s3` takes `existingSecret` (same keys
  as `marvin-r2-backup`) and `region`. `local` takes `volume.existingClaim`, or `volume.nfs: {server, path}`, from
  which the chart renders a static PV + PVC. It renders `<fullname>-backup-<name>` CronJobs (plugins init container
  included). The values are then:
  `[{name: r2, type: s3, schedule: "0 * * * *"}, {name: nas, type: local, schedule: "30 3 * * *"}]`.
- **Guardrail:** the chart `fail`s on a local target whose claim is the data PVC (`marvin-data` /
  `persistence.existingClaim` / `<fullname>-data`), or with no volume at all.
- NAS wiring: a **static NFS PV** (`nfs: {server: 192.168.30.10, path: <export>}`, RWX,
  `persistentVolumeReclaimPolicy: Retain`, `storageClassName: ""`, `claimRef` to the namespace's PVC), one per
  environment. It has to be PV + PVC: OpenShift's `restricted-v2` SCC doesn't allow inline `nfs:` volumes. A second
  nfs-subdir provisioner / StorageClass for `/tank/backups` would also work, but it's more moving parts for two
  volumes. NFS ignores `fsGroup`, so the export directory has to be writable by the pod's random UID (group 0
  writable + setgid, or `all_squash` to an anon uid) — open question 1.
- The old `backup.*` single-target values and template stay until the cutover is verified (slice 6), as the rollback.

**5. `marvin-storage-s3` plugin (new repo `InnerOpen/marvin-storage-s3`)**
- Takes `S3StorageProvider` from core and the S3 `Bucket` code from `offsite_backup.py`, and provides the asset
  provider `s3` and the backup target `s3`. **`boto3` lives only here.** Settings keep today's names
  (`STORAGE_S3_*`, `STORAGE_REMOTE_PUBLIC_URL`; target keys as in `marvin-r2-backup`), so no Secret changes.
- Public delivery for assets: `public_url` (custom domain, recommended), else presigned GET URLs. The bare endpoint
  URL is never offered, because it doesn't work on R2.
- README / manual page: what it can store (assets) and back up (DB dump, config archive incl. `.secret`, asset
  mirror), and the "bucket holds `.secret`" warning. Per provider: which credentials to create, where, endpoint and
  region:
  - **Cloudflare R2:** R2 → Manage API tokens → an **Object Read & Write** token scoped to the one bucket. Endpoint
    `https://<account-id>.r2.cloudflarestorage.com`, region `auto`.
  - **AWS S3:** an IAM user (or role) with a policy limited to `arn:aws:s3:::<bucket>` and `<bucket>/*`
    (Get/Put/Delete/List). No endpoint, region = the bucket's.
  - **MinIO:** an access key (Access Keys, or `mc admin user svcacct add`) with a bucket-scoped policy. Endpoint =
    the MinIO URL, path-style.
  - **Backblaze B2:** an application key restricted to the bucket (B2's S3-compatible API). Endpoint
    `https://s3.<region>.backblazeb2.com`, region from the endpoint.
- Tests: the SDK conformance kit against MinIO (CI service) + the ported `test_offsite_backup` cases. Installed via
  `plugins.packages` in dev, then production.

**6. Assets on R2 (after the plugin exists)**
- New bucket `marvin-assets` (separate from the backups, with its own bucket-scoped token, Secret `marvin-r2-assets`).
  Public delivery through a Cloudflare custom domain on the bucket (cached edge, e.g. `assets.iwobble.com`) as
  `STORAGE_REMOTE_PUBLIC_URL`.
- Migration, no freeze (thanks to per-row resolution): switch `STORAGE_PROVIDER=s3` (new uploads go to R2), then
  `python -m marvin.scripts.migrate_assets --to s3 [--dry-run]` copies each local file under the same key. It
  verifies size + the row's `checksum` and only then updates the row's `storage_provider`. It's idempotent and
  resumable, and it reports counts. Local files stay on `marvin-data` for a set period, then get deleted. Fallback if
  per-row resolution is dropped: a short upload freeze (516 files, minutes).
- Audit before switching: entry bodies, site settings or published sites that contain literal `/assets/…` or
  `…/assets/…` URLs won't follow the provider. Find them, then rewrite them or keep a redirect from `/assets/<key>`
  to the R2 URL. Rebuild the published sites after the migration.
- Backups after the move: the asset mirror reads from R2. To the R2 target that's a same-vendor copy, to the NAS
  target it's the off-vendor copy.
- Cost (measured 2026-10-06): 0.23 GB used; steady state ~1.3–1.5 GB with assets, well inside R2's 10 GB free tier
  (list calls on the hourly mirror are ~1 per 1,000 keys per run).

**Later / parked**
- The per-workspace storage overlay ("Phase 3" in the Marvin working notes: an `asset.store`/`asset.fetch` seam,
  per-workspace buckets) **stays parked**. When it comes back, a workspace "bring your own bucket" connection lives in
  `marvin-storage-s3`, not core.
- Admin Backups page: per-target last run / status / size (read-only; v1 config is Helm values).
- `replicaCount > 1` needs more than assets off the PVC: `.secret` and `scheduler_state.json` are still on
  `marvin-data`.

## Checklist
- [x] **Slice 1 — plugin plumbing:** generic entry-point loader (integrations moved onto it, behaviour unchanged);
      SDK as a pinned core dependency; admin Plugins page kind `storage`; chart `plugins.packages` rendering the
      init container into the backend and backup CronJobs; prod/dev values moved over (render diff: same pods +
      the CronJob gains the init container)
      — done except the last part: **prod/dev values are not moved yet** (it changes their render; its own rollout,
      after the SDK is merged). The admin `storage` kind landed with slice 2 (it needs the registry).
- [x] **Slice 2 — storage contract:** SDK `storage` module + conformance kit; core registry with the built-in
      `local`; `get_storage_provider()` through the registry, unknown slug fails startup; `provider_for(asset)` at
      every read site; `S3StorageProvider` temporarily registered from core as `s3` (removed in slice 7); tests:
      kit on local, mixed local/s3 rows served (fake s3 provider)
- [x] **Slice 3 — backup engine + local target:** `services/backup_engine` (`services/backup` already holds the
      per-workspace backup keys) + `scripts.backup` (run/list/restore/prune);
      local target (atomic writes, sidecar sha256, `st_dev` guardrail); assets via the provider; per-target
      retention (48/30/0 default); port the offsite_backup tests (snapshot under a live writer, incremental re-run
      uploads 0, restore matches, retention, pg_dump path). `offsite_backup.py` untouched and still running
- [x] **Slice 4 — chart targets:** `backup.targets[]`, one CronJob per target, static NFS PV/PVC for `local`,
      data-PVC guardrail (`helm template` fails as expected), old `backup.*` still renders unchanged; production
      gets the `nas-nightly` local target (NAS export, `prod/` subfolder, 02:30 New York, 0/30/8)
- [x] **Slice 5 — `marvin-storage-s3`:** repo, provider + target, conformance kit on MinIO, ported S3 tests,
      per-provider credential docs; installed in dev
      — repo `InnerOpen/marvin-storage-s3` (public, CI green); installed in dev through `plugins.packages` with slice 6
- [ ] **Slice 6 — backup cutover, no R2 gap:** NAS export ready (Jared); **dev first:** targets `r2` (bucket
      `marvin-backups-dev`, same layout, hourly) + `nas` (nightly), old CronJob off in the same upgrade; a one-off
      run per target, `list` on both, the restore test from each (dump → scratch Postgres 17 → per-table counts
      equal). **Production:** one `helm upgrade` swaps `marvin-offsite-backup` for `backup-r2` (same bucket, Secret,
      hourly; the old CronJob's last run and the new one's first are ≤ 1 h apart) + `backup-nas` (nightly). Run
      `backup-r2` once right after the upgrade, watch the next three hourly runs and the first nightly, then the
      restore test from both targets. Rollback: re-enable `backup.*`
      — **dev done** (2026-10-06): chart values only (`plugins.packages` incl. the plugin, `backup.targets[r2]`,
      `backup.enabled: false`; dev and production in one commit); one-off run, `list` and the restore test green
      (see "Review (slice 6)"). Dev has no NAS target (Decisions, answer 1), so dev's "+ nas" part is dropped.
      **Production pending** the coordinator's promotion: one upgrade swaps `marvin-offsite-backup` for
      `marvin-backup-r2` (48/30/8); `nas-nightly` already live since slice 4 (it gains the plugins init container).
      Then: run `marvin-backup-r2` once, watch three hourly runs + the next nightly, restore test from both targets
- [ ] **Slice 7 — remove the old code (only after slice 6 has been green for 7 days):** delete
      `offsite_backup.py` + its test, the old `backup-cronjob.yaml` / `backup.*` values; `s3_provider.py` and the
      `s3` registration leave core; `boto3` out of `pyproject.toml` + `uv.lock`; `STORAGE_S3_*` documented as the
      plugin's settings; image size before/after
- [ ] **Slice 8 — assets on R2:** bucket + token + Secret (Jared); install the plugin's asset side; URL audit (above);
      custom domain `assets.iwobble.com` (Jared, Cloudflare); dev rehearsal on a production copy (migrate, every
      asset URL 200, sites rebuilt); production: switch, migrate 516, verify counts + checksums, rebuild sites;
      delete local copies after the set period
      — **code built** (2026-10-06, Jared's "8 ok but configurable"): admin choice of upload provider (Admin →
      Storage), per-file providers for character-library files, `storage_migrate` (no freeze, `--to local`
      rollback, `--prune-local`), `/assets/<key>` redirects for moved files, backups mirror every provider in use
      (`BACKUP_ASSET_PROVIDERS`); e2e against MinIO green — see "Review (slice 8)". **No environment switched.**
      Left: Jared's Cloudflare checklist + Secret, then the runbook (`docs/manual/assets-on-r2.md`), dev first
- [ ] **Opaque asset keys + per-workspace asset domain** (Jared 2026-10-07: "A but can B be configurable"):
      **A** new keys `<storage code>/<yyyy>/<mm>/<uuid>.<ext>` for assets and library files (`_platform/…`): no
      workspace slug, no filename; original name served as `Content-Disposition` (Marvin) and stored on the object
      (plugin); `storage_migrate --rekey [--to P]` + `--prune-old`, old `/assets/` URLs keep working. **B** a
      platform admin's per-workspace `asset_public_base_url` (Admin → Storage, audited) for remote files.
      — **code built** on `feat/opaque-asset-keys` (see "Review (opaque keys)"). Left: dev `--rekey` on
      `marvin-assets-dev` + rebuild dev sites + prunes (runbook "Opaque keys"); then production's switch with
      `--to s3 --rekey --verify` (opaque from day one)
- [ ] **SDK rename** (its own slice, Jared 2026-10-06): `marvin-integration-sdk` → `marvin-plugin-sdk`. Ship the
      new package `marvin_plugin_sdk` and keep `marvin_integration_sdk` as a re-exporting shim (both import names
      work); publish the new distribution name; move core's pin, the plugin repos' dependencies and the init
      containers over one at a time; drop the shim once nothing imports the old name
- [ ] **Asset tombstones** (after slice 6): drop `assets/` objects from a target once their asset has been gone for
      30 days (Jared 2026-10-06). The engine records when a key first went missing from the source in a manifest
      next to the mirror and deletes it 30 days later. Needs the mirror to read every provider in use, so a
      half-finished asset move never looks like deletions
- [ ] **Cost:** trim dev retention (e.g. `keepHourly: 24, keepDaily: 7`); **Cloudflare R2 usage alert at ~5 GB
      (Jared sets it)**
- [ ] **Docs:** manual "Storage" (built-in local, plugins, settings), "Backups" (replaces `offsite-backup.md`:
      engine, targets, retention, guardrail + the same-pool caveat, restore from either target), the
      `marvin-storage-s3` page with the credentials table, storage plugin authoring guide next to the integration one,
      `postgres.md` backup section updated, what's new
- Order: slices 1–2 also unblock AI provider plugins (same loader, chart list and admin page). Each slice ships on its
  own through dev.

## Review (slices 1–3, 2026-10-06)
- **SDK** `feat/storage-contract` (0.7.0): `marvin_integration_sdk.storage` (contract), `.storage.testing`
  (conformance kit), `.storage.memory` (reference implementations / fakes). 81 tests, ruff clean.
- **Core** `feat/storage-plugins-1-3`: pins the SDK by commit as a PEP 508 git reference (`uv.lock` written with
  current uv). **Push order:** SDK branch first (merged to its `develop`, since production's init container still
  installs the SDK develop tarball and that copy shadows the image's until prod moves to `plugins.packages`), then
  core. If the SDK commit is rebased or squashed, bump the pin in `pyproject.toml` and re-lock.
- Backend suite 3348 passed / 12 skipped (also with the SDK worktree installed editable); ruff clean on touched
  files; Biome clean; `astro check` 50 errors, same as the base. `helm template` byte-identical for every values
  file; with `plugins.packages` set the backend and the backup CronJob get the init container, volume and
  `PYTHONPATH`, and the rendered command (python:3.12-slim, random UID) installs plugins without leaving the SDK.
- End to end, `python -m marvin.scripts.backup` with the local target on a second filesystem (`/dev/shm`): Postgres
  17 (container, PG17 client) run → re-run copies 0 assets → list → restore → `pg_restore` into a scratch DB: 250
  users / 1200 entries and a content hash equal; SQLite (Marvin schema, 62 tables) restore identical; assets
  byte-identical; nothing created under `BASE_DIR` (settings never built).
- OpenAPI changes (admin plugins: `kind` gains `storage`, providers gain `provides` / `inUse`), so the marvin-sdk
  gate reports drift until marvin-sdk is regenerated (`npm run generate`).
- Engine details that differ from `offsite_backup`: retention default 48/30/0 (same knob names); the hourly rule
  applies to database backups of either engine (`postgres/` and `sqlite/`), not only `postgres/`; the generic key
  prefix is `BACKUP_PREFIX` (falls back to `BACKUP_S3_PREFIX`); restore takes `--into DIR`.
- Not covered yet: character-library files (`LibraryFileStore`) still use the active provider, not per row;
  slice 8 has to give them a provider of their own before switching `STORAGE_PROVIDER`. The mirror reads only the
  active provider (fine for the no-freeze move, since earlier copies stay in the target).

## Review (slice 4, 2026-10-06)
- **Chart** `templates/backup-targets.yaml`: per `backup.targets[]` entry a CronJob `<fullname>-backup-<name>`
  (`python -m marvin.scripts.backup run --target <type> --name <name>`, backend image, backend-node podAffinity,
  plugins init container + `PYTHONPATH` when `plugins.packages` is set, `marvin-data` mounted as the legacy job
  does + `/tmp` emptyDir). `local` gets `/backup-target` (`BACKUP_LOCAL_ROOT`) from `volume.existingClaim` or
  `volume.nfs` → static PV `<namespace>-<fullname>-backup-<name>` (RWX, Retain, `storageClassName: ""`,
  `[hard, nfsvers=4.2]`, `claimRef`) + PVC (`volumeName`), optional `volume.subPath`. Plugin targets get
  `existingSecret` (envFrom) and `env`. Retention `{hourly, daily, weekly}` → `BACKUP_KEEP_*`; deadlines default
  3600/3600; resources default `backup.resources`. No engine change.
- **Missing root:** the NAS PV points at the export root `/tank/backups/marvin` and the CronJob mounts
  `subPath: prod`; the kubelet creates the subfolder on the first mount (it does on NFS: all_squash maps it to
  3100, which owns the root). Chosen over an `mkdir -p` wrapper (keeps the plain engine command and the engine's
  "root must exist" guardrail meaningful) and over pointing at the root (dev gets `dev/` later without a
  second export). Trade-off: prod's PV could see a future `dev/` sibling; same trust (one NAS, one admin).
- **Guardrails** (`helm template` fails): local target with no volume, or with `existingClaim` = the data claim
  (`marvin.pvcName`, `<fullname>-data`, literal `marvin-data`, with or without `subPath`), both `existingClaim`
  and `nfs`, missing `nfs.server`/`path` or a relative path, `volume` on a non-local type, bad / duplicate name,
  CronJob name > 52 chars, missing type / schedule, unknown retention key (`keepDaily` typo), targets without
  `persistence.enabled`.
- **Renders:** default, dev, k8s, production, staging byte-identical; `values-iwobble.yaml` adds exactly
  PV `marvin-marvin-backup-nas-nightly`, PVC `marvin-backup-nas-nightly`, CronJob `marvin-backup-nas-nightly`
  (per-object diff: 3 added, 0 removed, 0 changed; `marvin-offsite-backup` unchanged). `helm lint --strict`
  clean for every values file.
- **Dev end to end** (`marvin-dev`, throwaway objects from the chart with name `slice4-test`, subPath
  `slice4-test`, never-firing schedule): PVC bound; the kubelet created the subfolder (3100, 0770); run 1:
  pg_dump 63 tables 7.4 MB + config + 516 assets (91 MB) in 33 s, the `st_dev` guardrail passed (target
  `192.168.30.10:/tank/backups/marvin/slice4-test` vs `/tank/nfs/...marvin-data...`); run 2: 0 uploaded / 516
  unchanged, pruned the first run's dump + config (same day, hourly 0); `list --target local` shows the dump
  and config; `restore --into /tmp/restore`: 516 assets sha256-identical to `marvin-data`, `.secret` identical,
  dump lists 63 TABLE DATA entries. Test PV/PVC/CronJob/Jobs deleted and `slice4-test/` removed (export root
  empty again). `marvin` namespace untouched.
- **Promote expectations:** the next `promote-iwobble.sh` adds the PV/PVC (binds at once) and CronJob
  `marvin-backup-nas-nightly`; nothing runs until 02:30 New York. The first run creates `prod/` and copies all
  assets (~90 MB) + a dump; later runs are incremental. Optionally trigger one right after the promote
  (`oc -n marvin create job --from=cronjob/marvin-backup-nas-nightly marvin-nas-first`).

## Review (slice 5, 2026-10-06)
- **Plugin** `marvin-storage-s3` 0.1.0 at `~/code/MarvinStorageS3` (`git init`, branch `main`, not on GitHub: the
  repo name/location `InnerOpen/marvin-storage-s3` is Jared's call). Entry point `marvin.storage_providers`:
  `s3 = marvin_storage_s3:plugin` → `StoragePlugin(slug="s3", provider=S3StorageProvider, target=S3BackupTarget)`.
  Depends on `marvin-integration-sdk>=0.7,<1` + `boto3>=1.36,<2`; dev resolves the SDK at core's pinned commit.
- **Settings.** Target: `BACKUP_S3_BUCKET` (required), `BACKUP_S3_ENDPOINT` (empty = AWS), `BACKUP_S3_REGION`
  (default `auto`), `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (masked) — the `marvin-r2-backup` Secret's keys —
  plus optional `BACKUP_S3_ADDRESSING_STYLE` / `BACKUP_S3_CHECKSUMS`. No prefix setting: the engine already applies
  `BACKUP_PREFIX` / `BACKUP_S3_PREFIX`. Provider: core's `STORAGE_S3_BUCKET/ENDPOINT/REGION/ACCESS_KEY/SECRET_KEY`,
  `STORAGE_REMOTE_PUBLIC_URL`, plus `STORAGE_S3_PREFIX`, `STORAGE_S3_PRESIGN_SECONDS` (3600),
  `STORAGE_S3_ADDRESSING_STYLE`, `STORAGE_S3_CHECKSUMS`. Defaults: checksums `when_required` (as `offsite_backup`;
  boto3 here is 1.43), path-style with an endpoint / virtual on AWS, region `auto` refused without an endpoint.
- **Digests.** One PUT up to 64 MiB (ETag = MD5 → `TargetObject(algorithm="md5")`, what the asset mirror
  compares), multipart above (ETag kept, no algorithm → size only; restore checks the `sha256` metadata). SSE-KMS /
  SSE-C ETags aren't taken for MD5 on `head` (README: use SSE-S3 for a backup bucket). Provider stores `sha256`
  as object metadata, so `checksum("sha256")` needs no download; md5 from a single-part ETag. Asset URLs:
  `<public base>/<prefix><key>`, else presigned; never the bare endpoint.
- **Tests:** 116 passed / 1 skipped (moto + MinIO `cgr.dev/chainguard/minio` RELEASE.2026-09-22): the SDK kit for
  both sides (provider plain and with prefix + public URL; target single-part and all-multipart) on both backends,
  plus the S3 cases from `test_offsite_backup` (old-script objects readable, rollback readable, metadata
  lower-cased, multipart digests, paging past 1000, delete batching / errors, 403 never read as missing). ruff
  clean. CI workflow starts MinIO.
- **Core engine against MinIO** (plugin installed in the core venv, SQLite data dir, 13 assets incl. a 70 MB
  file): old `offsite_backup` writes history under `dev/` → `scripts.backup run --target s3` reads it: 0 assets
  uploaded / 13 unchanged, old dump + config pruned → re-run 0 → a new asset: 1 uploaded → the old script after it:
  0 uploaded / 14 unchanged (rollback works) → `list` identical to the old script's → `restore` (of the old
  script's dump): `.secret` identical, 14 assets sha256-identical, DB rows equal.
- **Read-only R2** (`marvin-backups-dev`, keys from `pass`, write calls blocked on every client): plugin `list`
  523 objects = the old script's `Bucket.list` (same keys and sizes; assets 516, postgres 5, config 2), every
  object single-part with md5 = the old script's ETag; `engine.open_target("s3")` resolves to the plugin and
  `list_backups` equals the old script's `list`; `head` on the oldest/newest dump and config shows a 64-hex
  `sha256`. Nothing written or deleted.
- **Core discovery** (plugin installed): load report `s3` (marvin-storage-s3 0.1.0, ok), the registry logs
  "storage plugin 's3' replaces core's built-in 's3'", `GET /api/admin/plugins` lists it as kind `storage`,
  `provides: [assets, backups]`. No core code change was needed (registry/engine/chart already fit); OpenAPI
  unchanged. One test fix: two `test_admin_plugins` cases stubbed only the integration sources, so an installed
  storage plugin leaked into their listing; an autouse fixture now stubs the storage sources empty by default.
  Backend suite with the plugin installed: 3410 passed / 12 skipped; the storage/plugin/backup tests also pass
  without it (141).
- **For slice 6:** the target CronJob needs `existingSecret: marvin-r2-backup` only (region defaults to `auto`;
  the old job passed `BACKUP_S3_REGION` from values); `plugins.packages` must carry the plugin's tarball (and the
  SDK's) in dev and production values. The plugin pulls boto3 + deps (~35 MB) into `/plugins` on each pod start,
  shadowing the image's copies until slice 7 drops boto3 from core.

## Review (slice 6, 2026-10-06)
- **Chart values only** (no code, no template logic; two comments updated): `values-dev.yaml` and
  `values-iwobble.yaml` move the integration list from the raw `install-integrations` init container
  (+ `extraVolumes` / `extraVolumeMounts` / `PYTHONPATH` in `extraEnv`) to `plugins.packages`, adding
  `marvin-storage-s3` (main tarball); add target `r2` (`type: s3`, `existingSecret: marvin-r2-backup`, hourly,
  deadlines 2700/900 as before; dev 24/7/0, production 48/30/8 with `timeZone: America/New_York`); set
  `backup.enabled: false` with the old settings kept as the rollback. No `BACKUP_S3_REGION` needed: the plugin
  defaults to `auto`, and the Secret's four keys (same in both namespaces) are exactly the plugin's.
- **One install, no SDK shadowing:** the chart's `install-plugins` replaces `install-integrations` (one init
  container in the backend, plus one per backup CronJob); it removes the SDK copy after pip, so the image's pinned
  SDK (`424927150c…` = the SDK's `develop` head, 0.7.0) is imported. Checked in the dev pod:
  `marvin_integration_sdk` from `/app/.venv`, `boto3` from `/plugins` (shadows the image's until slice 7).
- **Renders** (per object): default / k8s / production / staging byte-identical. Dev: CronJob
  `marvin-offsite-backup` removed, `marvin-backup-r2` added, backend init container renamed + rewritten (same
  packages + the plugin, SDK removed after install), frontend loses the unused `PYTHONPATH`. Production: the same,
  plus `marvin-backup-nas-nightly` gains the plugins init container / volume / `PYTHONPATH`. Legacy vs new R2
  CronJob: same schedule, zone, deadlines, image, affinity, data mount; command → `marvin.scripts.backup run
  --target s3 --name r2`, the four `secretKeyRef`s → `envFrom`, `BACKUP_S3_REGION` dropped, `BACKUP_KEEP_*` set
  (production 48/30/8; dev unchanged 24/7/0). `helm lint --strict` clean for every values file. A read-only render
  of production at its live tag against `helm get manifest`: exactly those changes, nothing else.
- **Dev cutover** (`helm upgrade` revision 8, `image.tag=develop-7f653ff`, chart from this branch): backend and
  frontend rolled out; the 8 integrations load as before; the storage registry loads lazily, so the backend log
  shows "storage plugin 's3' replaces core's built-in 's3'" on the first storage call — confirmed by loading the
  registry in the backend pod (load report `s3`, marvin-storage-s3 0.1.0, ok) and in every backup job's log.
  `marvin-offsite-backup` and its jobs are gone.
- **First run** (`oc create job --from=cronjob/marvin-backup-r2`, 60 s incl. the plugin install): found the old
  job's history in `marvin-backups-dev`: pg_dump 63 tables 7.4 MB, config, **assets 0 uploaded / 516 unchanged**,
  pruned 2 (the old job's 02:00 UTC dump + config, same hour/day), 8.7 s. `list`: 6 dumps (back to
  20261006T213943Z) + 2 configs, within 24/7/0.
- **Restore test** (Job from the CronJob, `restore --into /tmp/restore`): `.secret` identical to the live one;
  516/516 assets sha256-identical to `marvin-data`; the dump `pg_restore`d into a local `postgres:17` scratch
  database: **63 tables, 16,062 rows, every per-table count equal** to `marvin-dev-pg` live. Scratch container,
  dump and Job deleted. (`postgres.md`'s count query needs `psql -U postgres` in the CNPG pod: peer auth.)
- **Docs:** `offsite-backup.md` rewritten around targets (r2 + NAS, retention table, run/check/restore with the
  engine, the old job as a retired section with the rollback); `postgres.md` backups + restore test (in-cluster
  fetch, no credentials on the workstation); chart README "Backups"; `operations.md` "every hour".
- **New dependency to know about:** every backup run now pip-installs the plugins (GitHub + PyPI egress, ~45 s);
  if GitHub or PyPI is down, the R2 and NAS runs fail until it's back (the old job needed neither). Fixed for good
  by pinned tags or baking plugins into an image; not done here.
- **Production expectations:** `promote-iwobble.sh <develop sha with this commit>` removes `marvin-offsite-backup`
  and adds `marvin-backup-r2` in the same upgrade (plus the backend restart that installs the plugin). The next
  run is the following top of the hour (America/New_York), so the old job's last run and the new first are
  ≤ 1 h apart; run it at once: `oc -n marvin create job --from=cronjob/marvin-backup-r2 marvin-r2-first`, expect
  `assets 0 uploaded, 516 unchanged` and the old job's same-hour dump pruned. Rollback: `helm rollback marvin
  <previous revision> -n marvin` (old CronJob back at once), or `backup.enabled: true` + suspend/remove the
  `r2` target.

## Review (slice 8, 2026-10-06) — code only, no environment switched
- **Branches (not pushed):** core `feat/storage-slice-8` (from `develop` 1236b1db), plugin `marvin-storage-s3`
  `feat/slice-8`, marvin-sdk `feat/slice8-types` (from `main`). Push order: plugin (merge to `main`, the chart
  installs its `main` tarball; optional, only for `STORAGE_S3_CACHE_CONTROL`), core, SDK types (the SDK gate
  fails on the core PR until they're in).
- **Prerequisite, per-row everywhere:** every `get_storage_provider()` left is an upload (assets, derivatives, AI
  imports, bundle imports, character uploads); reads and deletes resolve the row. Fixed: character-library files
  record `"provider"` per file (a file without one is local) and are deleted from it (`CharacterFileStore.delete`
  takes the file entry); `repair_character_mattes` reads/writes each file on its provider; a bundle import records
  the provider the bytes were actually stored on (it copied the bundle's `storageProvider`, so after a switch the
  row said `local` with the file on R2); the `/assets` mount is always there (it was mounted only when
  `STORAGE_PROVIDER == "local"`, so local rows would 404 the moment it changed).
- **Admin choice** (`services/storage/admin.py`, `routes/admin/storage_controller.py`, `GET/PUT
  /api/admin/storage`, page `/admin/storage` under Settings): `platform_settings["storage"] =
  {"upload_provider": slug|null}` overrides `STORAGE_PROVIDER` (null = follow it); only an installed, configured
  provider is accepted (422); counts and bytes per provider, library files per provider, per workspace × provider;
  asset detail shows *Stored on*. Read through a 5 s cache (every asset URL asks), reset in-process on save.
  Audited as `storage_provider_changed` (new event type, catalog "System", platform scope → locked).
- **Fallback decision:** `STORAGE_PROVIDER` stays strict at startup (operator config). The admin's choice is data:
  if it becomes unavailable (plugin removed, Secret gone) new uploads fall back to `STORAGE_PROVIDER` with a
  CRITICAL startup line, a once-per-reason error log and a red banner on Admin → Storage, instead of refusing to
  start (which would lock the admin out of the page that fixes it). Safe now where the old quiet fallback wasn't:
  each new row records the provider it was really stored on, so no URL is wrong. Verified live (backend without
  `STORAGE_S3_BUCKET`, choice `s3`: starts, banner, uploads land local).
- **`storage_migrate`** (`services/storage/migration.py`): stages each file, copies it unless the target already
  has the same sha256 (resume), verifies (provider sha256; `--verify` downloads and hashes), then a compare-and-set
  `UPDATE … WHERE storage_provider = <old> AND storage_key = <key>` (also refreshes the cached `public_url`); a row
  deleted meanwhile has its copy removed, a changed one is left. Passes repeat until nothing is left (max 10), so
  uploads to the old provider during the run are caught. Library files move with their pack JSON (provider, URL,
  states). Never deletes the source; `--prune-local` deletes a local copy only after downloading the remote copy
  and matching sha256 + size. A stale row checksum is reported, not fatal (the copy is checked against the bytes).
  Exit 0 / 1 (some failed) / 2 (bad target or workspace).
- **Old URLs:** `LocalAssetFiles` (the `/assets` mount) answers a missing key whose row (or pack file) lives
  elsewhere with a 302 to its current URL; the frontend's `/assets` proxy passes redirects through
  (`redirect: "manual"`) instead of streaming R2 through Astro. Character URLs are computed at read time
  (`with_current_urls` in `resolve` / `pack_character` / the packs admin), never rewritten in the stored JSON.
- **Backups (item 5):** the engine mirrors local + `STORAGE_PROVIDER` + `BACKUP_ASSET_PROVIDERS` (a key on several
  providers copied once; a provider that can't open fails only the asset step). Decision: keep mirroring R2 assets
  to both targets (R2→R2 covers app-level deletes, bugs and a leaked assets token at ~1.5 GB; the NAS is the
  off-vendor copy). Proven R2→R2 (MinIO bucket → bucket, 46/46, re-run 0 uploaded) and s3 → local target.
- **Plugin:** optional `STORAGE_S3_CACHE_CONTROL` (empty default; runbook sets `public, max-age=86400`, not
  `immutable` because the matte repair rewrites in place); README covers the admin choice, migration, backups and
  CORS. 118 passed / 1 skipped (moto + MinIO).
- **Tests:** backend 3441 passed / 12 skipped (also with the plugin installed); new `test_storage_switching.py`
  (13) and `test_storage_migrate.py` (12); frontend unit 475 pass; Biome clean on new files; `astro check` 51
  errors = base 51; `mkdocs build --strict` only the pre-existing `openapi.json` warning. SDK gate reproduced
  (fresh venv, `pip install -e`, FastAPI 0.142.2): additions only (`/api/admin/storage` + 4 schemas), committed in
  marvin-sdk `feat/slice8-types`; `tsc --noEmit` clean.
- **E2E against MinIO** (`cgr.dev/chainguard/minio`, anonymous-read bucket standing in for the custom domain, SQLite
  backend + `marvin-storage-s3` editable): 40 local assets serve (API + publishing API, bytes equal) → `migrate --to
  s3 --verify` started, 3 uploads landed local, admin switched to s3 via the API, 3 more landed on s3 → pass 2
  caught the 3 stragglers (43 moved, 2 passes) → all 46 serve from the public base with equal bytes via the API,
  the publishing API and its `/file` redirect → re-run copies 0 → old `/assets` URL 200 (local kept) →
  prune dry-run 43 / prune 43 → old URLs 302 to the public base, bytes equal → backup r2 (bucket → bucket) 46/46,
  re-run 0 uploaded; local "NAS" target 46/46 → switch back to local, 2 uploads land local, mixed rows serve →
  `migrate --to local --verify` 46 back, all 48 serve from `/assets` → 2 `storage_provider_changed` events on the
  admin Events page. Character pack: created on local → migrated (pack JSON provider s3, state URL on the public
  base, bytes equal) → pruned → old URL 302 → back to local (original URL) → deleted. Admin page screenshots
  (choice, fallback banner, asset *Stored on*) in the job's `slice8-shots/`. Containers stopped; no cluster or R2
  touched.
- **URL audit** (core, MarvinAstro, GraceMartinFranklin, mashandburnco): core issues fixed above (mount, bundle
  import provider, character URLs, library files, mirror, proxy redirects; logo/favicon placeholders now suggest an
  asset slug). Not code: any asset URL typed into entries/settings keeps working through the redirect (runbook has a
  count query); MarvinAstro and both sites pass `publicUrl` through at build time (no image domains, CSP, headers or
  redirects to change) — they must be rebuilt after the move, and production must never run without
  `STORAGE_REMOTE_PUBLIC_URL` (presigned URLs would expire inside built pages). mashandburnco's `/assets/brand/…` are
  its own `public/` files, not Marvin's. No changes in those repos.
- **For Jared:** the Cloudflare checklist + Secret (runbook); new bucket-scoped tokens recommended over extending the
  backup token (a leaked backend token shouldn't reach the backups); the prune period (suggest 30 days, after a
  restore test with assets); dev refreshes from production need the bucket copied too once production is on R2.

## Review (opaque keys + per-workspace domain, 2026-10-07) — code only, no environment changed
- **Branches (not pushed):** core `feat/opaque-asset-keys` (from `develop` f099f244), plugin `marvin-storage-s3`
  `feat/content-disposition` (from `main` 969fbde), marvin-sdk `feat/opaque-keys-types` (from `main`). Push order:
  plugin (merge to `main`: the chart installs its `main` tarball), core, SDK types (the SDK gate fails on the core
  PR until they're in).
- **Key format:** `<storage code>/<yyyy>/<mm>/<uuid>.<ext>` (`services/storage/keys.py`) for uploads, derivatives,
  bundle imports and character-library files (`_platform/…`). `<storage code>` = `groups.storage_code`, 12 random
  base32 chars, backfilled by the migration and set on creation (model default; `workspace_code()` makes one if
  ever missing). **Why random, not HMAC(`.secret`, id):** stable even if `.secret` is lost or rotated (a pod
  without the PVC), reveals nothing if the secret leaks, no secret needed to work it out; it costs one column.
  Keys live on rows and are never recomputed, so neither choice would break old keys. Extension kept, lower-cased,
  `[a-z0-9]{1,10}` (or guessed from the MIME type).
- **Download names:** `content_disposition()` → `inline; filename="<ascii fallback>"` + `filename*=UTF-8''…` for
  non-ASCII (quotes/control chars/paths stripped). Served by `/api/platform/assets/{id}/file` (inline now, was
  `attachment`) and the `/assets` mount (opaque keys, name looked up and cached); passed to `put()` as metadata
  `content_disposition`, which the plugin (and core's temporary s3) store as the object's `Content-Disposition`.
  The frontend `/assets` proxy passes the header through.
- **`--rekey`** (`migration.migrate(to, rekey=True)`): rows/library files without an opaque key (under their own
  workspace's code) are copied to `rekeyed()` keys — uuid5 of the row id (library: pack + old key), month from the
  old key — verified, then one compare-and-set repoints provider + key and inserts `storage_key_aliases` (old
  provider/key → current key, asset or pack). Idempotent (second run `0 passes`), resumable (an interrupted run
  finds its copy at the same key: `already there`), stragglers caught by the next pass, rows deleted mid-copy
  have the copy removed. Old copies never deleted by it. **`--prune-old`** deletes an old copy only if nothing is
  stored at that (provider, key) and the current copy matches (both downloaded); the alias stays (marked pruned)
  so `/assets/<old key>` keeps redirecting (302, any provider's old key). `--prune-local` also covers a local
  copy at an old key (dev's case: moved to R2 under old keys, then rekeyed there). Deleting an asset deletes its
  unpruned old copies and aliases.
- **Per-workspace domain:** `groups.asset_public_base_url`; `PUT /api/admin/storage/workspaces/{id}` (super admin;
  `https://host[/path]`, no user info/query/fragment, ≤255; `http://` outside production), table on Admin →
  Storage (key prefix + domain per workspace, platform default shown). `public_url_for(slug, key, group_id)`
  rebuilds the row's provider with `STORAGE_REMOTE_PUBLIC_URL` = the domain (only providers that declare that
  setting; cached per domain); local rows keep the API host. Every URL site uses it (AssetRead, publishing API +
  `/file`, download redirect, characters, AI tools, automation). Audited as `storage_public_domain_changed`
  (platform scope, locked). Lookups cached 5 s like the upload choice.
- **Assumption audit:** backup mirror is key-agnostic (`assets/<key>`; tested with opaque keys); export writes
  `files/<key>` and import makes a new key under the importing workspace's code; library delete guard accepts
  its old prefix or `_platform` opaque keys; `repair_character_mattes` keeps the download name when rewriting.
  MarvinAstro/sites: they only pass `publicUrl` through (fixtures have old-format URLs as data only) — no change;
  sites must be rebuilt after a rekey and before `--prune-old`. SDK `StorageProvider` docstring still shows the
  old key as its example (cosmetic, SDK repo, not changed).
- **Tests:** backend 3464 passed / 12 skipped (develop 3441/12; new `test_opaque_storage_keys.py`, plus updated
  library/migrate/switching/catalog tests); plugin 120 passed / 1 skipped against MinIO (+ moto); frontend unit
  475 pass, `astro check` 51 errors = base 51, Biome clean. SDK gate reproduced (fresh 3.12 venv, `pip install
  -e`, FastAPI 0.142.2): additions only (`PUT /api/admin/storage/workspaces/{workspace_id}`,
  `StorageWorkspaceSettings`, `StorageWorkspaceUpdate`, 2 fields on `StorageSettingsRead`); `tsc --noEmit` clean.
- **E2E against MinIO** (anonymous-read bucket standing in for the custom domain; SQLite; plugin editable): develop's
  code uploaded 6 assets (`IMG_9750 orig.JPEG`, `Café menü.png`, `Résumé 2026.pdf`, `日本の写真.webp`, …) and a
  2-file pack under old keys → branch: migration gave the workspace a code, old URLs 200, a new local upload is
  opaque and served inline under its name → admin switched to s3 → `--to s3 --rekey --verify` (7 rows + 2 library
  files, 8 rekeyed, 0 failed) → every asset: opaque key, URL on the bucket, bytes equal, `Content-Disposition`
  right (ASCII + RFC 5987), publishing API `publicUrl` and `/file` redirect equal, `/file` redirect; pack states
  on `_platform/…` with `idle.gif`/`waving.gif` names → second run copies 0 → old `/assets` URLs 200 → `--prune-old`
  (8) → old asset and library URLs 302 to the opaque URLs, bytes equal → workspace domain (`localhost` vs
  `127.0.0.1`, same bucket) reflected in the API, publishing API and both redirects, bytes equal from it; invalid
  domain 422; event on admin Events → back to local with `--to local --rekey --verify` (0 rekeyed) → all served from
  `/assets/<opaque>` inline. 194 checks, 0 failed. Admin UI screenshots in the job's `opaque-shots/` (table, invalid
  domain error, saved, phone width, Events). MinIO and servers stopped; no cluster or R2 touched.
- **For Jared:** (1) dev: `--rekey` on `marvin-assets-dev`, rebuild the dev sites, then `--prune-local` /
  `--prune-old` (runbook "Opaque keys"); (2) production's switch with `--to s3 --rekey --verify` after this ships;
  (3) a workspace domain needs DNS work first (R2 custom domain in our account, or Cloudflare for SaaS for a
  client-owned zone — check its pricing/plan); (4) `/file` now answers `inline` instead of `attachment` (as asked:
  images open in the tab; *Save as* keeps the name).

## Decisions (Jared, 2026-10-06)
- Keep core lean: cloud SDKs out of core. Storage is its own plugin type (`marvin.storage_providers`), with the
  contract in the plugin SDK (core re-exports), installed site-wide by a platform admin (Helm init container) and
  configured by admins.
- Core keeps the storage interface, the local disk provider (mandatory built-in default) and the backup engine with a
  built-in `local` target.
- One generic S3-compatible plugin (`marvin-storage-s3`, working name) for R2/AWS/MinIO/B2: asset provider **and**
  `s3` backup target. Its docs say what it stores and backs up, and which credentials to create per provider.
- Backups take a list of independent targets, each with its own schedule and retention. Retention defaults to
  30 days, configurable by an admin per target.
- A local target must be on a different volume from the live data. The chart refuses `marvin-data`.
- Assets move to R2 only after the plugin exists. Phase 3 per-workspace storage stays parked.
- Storage plugin type first (smallest contract), so AI provider plugins reuse the plumbing.
- No gap in R2 backups: engine + local target → plugin with s3 target → switch the CronJob and verify both targets →
  only then delete the old built-in R2 code.
- **All 8 slices approved** (Jared 2026-10-06: "1 ok … 8 ok but configurable").
- **Slice 8: asset storage is configurable by an admin.** The admin chooses `local` or `s3` for *new* uploads and can
  switch back at any time; existing assets keep serving from wherever they live (per-row `provider_for(asset)`), so
  a switch never breaks a URL and never requires moving files.
- Answers to the open questions (Jared 2026-10-06):
  1. **NAS export** (created by Jared 2026-10-06): server `192.168.30.10` (the Proxmox node `pve`), path
     `/tank/backups/marvin` (ZFS dataset `tank/backups`, quota 50G, lz4), exported to `192.168.50.0/25` with
     `rw,sync,no_subtree_check,all_squash,anonuid=3100,anongid=3100`; the directory is `3100:3100 0770`, so any pod
     UID writes as 3100. Verified from `marvin-dev` with a static PV (`nfs.server/path`, ReadWriteMany, Retain,
     `storageClassName: ""`, `mountOptions: [hard, nfsvers=4.2]`, `claimRef` to the PVC) + PVC (`volumeName`) under
     `restricted-v2`. Same `tank` pool as the live data: it protects against PVC/app problems, not pool loss (R2
     stays the off-site copy). **Dev gets no NAS target**; if it ever does, use subfolders `marvin/prod` and
     `marvin/dev`.
  2. **Retention:** R2 keeps **48 hourly + 30 daily + 8 weekly**, set per target and admin-configurable; the generic
     default stays "30 days" (48 hourly + 30 daily + 0 weekly).
  3. **SDK name:** rename to `marvin-plugin-sdk`, with a compatibility shim so both import names work during a
     transition. Not cheap inside slice 1 (the distribution name is the dependency of every plugin repo and the
     init containers), so it is its own slice ("SDK rename" below).
  4. **Asset move without a freeze** (per-row resolution).
  5. **Public custom-domain asset URLs** (`assets.iwobble.com`); presigned URLs only if private assets appear.
  6. **Deleted assets are dropped from backups after 30 days** (today's mirror keeps them forever). Not part of
     slice 3, which keeps the never-delete rule: see "Asset tombstones" below.
  7. **Target config via Helm values in v1.**

## Open questions for Jared
None open: all seven were answered on 2026-10-06 (see Decisions).

# Backup health + storage settings visibility (2026-10-07, approved by Jared)

Why: prod's hourly R2 backup failed silently 15:00–16:00 UTC (the `marvin-r2-backup` Secret held a revoked
key after the token was re-scoped). The backend has no Kubernetes API access, so the jobs report to it
through the database.

## Plan
- [x] `backup_runs` table (model + migration, SQLite + Postgres 17 up/down): target name/type, status
      ok|failed|partial|missed, started/finished/duration, schedule/time zone/retention, location (describe(),
      never a credential), non-secret target settings, db key/bytes, config items, assets uploaded/unchanged,
      pruned, error summary (scrubbed), pod name, notified_at.
- [x] Engine side (`backup_engine/recorder.py`, no Marvin settings/SQLAlchemy): plain DB-API insert at the
      end of every `run` — ok/failed/partial, and failed when the target can't even be opened; the DB is
      the job's own (POSTGRES_* or DATA_DIR/marvin.db). Errors mapped to plain messages (shared mapping).
- [x] `backup test` subcommand: list/put/get/delete `_marvin-healthcheck/<uuid>.txt` on a target.
- [x] Chart: BACKUP_SCHEDULE / BACKUP_TIME_ZONE on each target CronJob (retention already travels).
- [x] Backend `services/backup_health`: tiny 5-field cron reader (no croniter dependency), target status
      (last run, last success, next expected, overdue), recent runs; scheduler task every minute-tick:
      dispatch `backup_completed`/`backup_failed` for runs not yet notified, overdue → a `missed` row +
      `backup_failed` (reason overdue) once per incident, cleared by the next ok run; prune runs > 90 days.
- [x] Events: un-hide backup_completed/backup_failed (sent_by, variables), dispatch with group_id=None;
      EmailEventListener must not match every workspace's subscriptions when group_id is None.
- [x] Bell: `GET /api/admin/events/feed` (super admin, platform events); ActivityToaster polls it for
      super admins (AppLayout + AdminLayout), `backup_failed` toast → /admin/backup-health.
- [x] Admin: `GET /api/admin/backup-health`, page `/admin/backup-health` (Operations), linked from Storage
      and Backups; Storage shows each provider's effective settings (masked via SDK `masked_config`) and
      backup targets' settings from their latest run; Test connection (super admin) for asset providers.
- [x] Docs: offsite-backup.md, assets-on-r2.md, what's new.
- [x] Verify: full pytest, new tests, frontend tests/biome/astro check vs baseline, live check +
      screenshots, helm lint/template diffs, SDK gate (+ types commit in a MarvinSDK worktree).

## Review (2026-10-07) — code only, nothing deployed, no cluster or R2 writes
- Migration `59d0896537fa` (`backup_runs`): up/down/up on SQLite and Postgres 17 (throwaway container).
- Runs record themselves at the end of `run`: ok / partial / failed, and failed when the target can't be
  opened (exit 2). Plain DB-API insert (sqlite3 / psycopg2), never creates a DB, never changes the exit
  code. Same-reason step failures are folded ("database, config, assets: the key is invalid or revoked…").
- Overdue = no successful run within interval + min(interval, 2 h) + 15 min (hourly 2h15, daily 26h15),
  from the last success (or first seen). One `missed` row per incident = the dedupe marker; next ok clears.
- Found live: dispatching while the `missed` row was uncommitted lost the event on SQLite ("database is
  locked" in the audit publisher's own connection). Fixed: marker committed first, `announce_runs`
  dispatches every un-notified row; regression test + a throwaway test proving the old order lost it.
- Events: `backup_completed` / `backup_failed` un-hidden, platform scope, audit-locked, `group_id=None`.
  EmailEventListener no longer matches every workspace's subscriptions when group_id is None.
- Bell: new `GET /api/admin/events/feed`; ActivityToaster polls it for super admins (AppLayout + AdminLayout
  now has the bell). No Slack routing for platform events exists → bell + admin pages are the alert.
- Verified: backend 3523 passed / 14 skipped (SQLite), 3529 / 5 on Postgres 17; frontend 484 tests,
  biome 1 info (= baseline), astro check 50 errors (= baseline); helm lint ok, template diff prod/dev =
  only BACKUP_SCHEDULE / BACKUP_TIME_ZONE on the target CronJobs; SDK gate reproduced, types committed in
  MarvinSDK `feat/backup-health-types`. Live check (SQLite + astro dev + headless Chromium + local MinIO)
  with real job runs incl. a revoked key; screenshots in the job's tmp/backuphealth-shots.
