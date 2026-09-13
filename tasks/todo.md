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
- [ ] Bubble: `/agents` shows effective read-only/rw from the same policy.
- [ ] Biome/astro check + pytest green; commit; push; roll out backend + frontend; verify.

## Review
(at the end)
