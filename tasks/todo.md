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
