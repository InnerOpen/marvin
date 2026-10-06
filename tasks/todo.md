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
- [ ] SDK: move the provider contract (`AIProvider`, `Message`, `ToolCall`, `ToolDefinition`,
      `CompletionOptions`, `CompletionResult`, `ImagePart`) into the plugin SDK; core re-exports for compatibility.
- [ ] Core: discover providers from `marvin.ai_providers`; factory, credential modes and capability flags read
      the registry; AI Settings' provider list and model picker come from it (nothing hard-coded).
- [ ] Prices live with the provider (see Pricing below), not in core's `pricing.py`.
- [ ] Packages, one per vendor: openai (+ azure, shares `openai_api`), anthropic,
      google (move to the `google-genai` SDK — `google-generativeai` is deprecated), ollama.
- [ ] Baseline (decide: leaning no built-in; the chart installs openai by default). Tests use a fake provider.
- [ ] Helm: tarballs in the same init container as integrations; admin page lists installed providers + versions.
- [ ] Docs: provider plugin authoring guide next to the integration one.

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
- Workflow provenance: `source_integration_id` (FK to integrations, SET NULL) + `source_blueprint` (the blueprint key),
  set by `blueprints/apply.py` when an integration installs a workflow. Backfill: match existing workflows to the
  workspace's installed integration by blueprint slug, then by name prefix; leave NULL when unsure.
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

**5. Events cleanup (needs Jared's call — not built until decided)**
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
- [ ] **Slice 1 — storage:** webhook subscriptions table + workflow trigger columns + provenance columns; backfill +
      downgrade; listeners and engine read the new storage; API shapes unchanged (contract tests on webhook and
      workflow read/write); migration tested up/down/up on SQLite and Postgres 16; prod backfill dry-run against a copy
      of `marvin.db` (counts before = after)
- [ ] **Slice 2 — one catalog:** `triggerable`, `emittable`, `sent_by`, `leads_to`; built-in listeners declare
      `reacts_to`; side lists removed; drift tests
- [ ] **Slice 3 — connections service + API:** reactions/senders/recent/summary; role + workspace scoping tests;
      platform events excluded; SDK Quality Gate
- [ ] **Slice 4 — UI:** event page (three parts + chain), catalog dots, "+ New workflow on this event", Installed-by
      badge, admin panel; live check incl. 390px
- [ ] **Slice 5 — cleanup:** only the items Jared picks
- [ ] **Slice 6 — SDK/CLI/MCP/docs**
- Each slice ships on its own (CI-gated rollout); slice 1 first, since everything else reads its storage.

## Open questions for Jared
1. Built-in reactions (site rebuild, indexing, smart collections, embeds): show them as a muted "Built-in" line?
   (Proposed: yes.)
2. Section 5 cleanup: which items, and `site_build_*` or `site_deployment_*` as the family to keep?
3. "+ New workflow on this event" in the Subscribe menu — yes?
4. Workflows installed by an integration: may they be switched off from the event page, or only on the workflow /
   integration page? (Proposed: link only, so the event page never fights the integration that owns them.)
5. Slice order OK (storage first), or UI first on top of today's storage and normalise after?
