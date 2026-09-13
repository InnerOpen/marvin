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
- [ ] `astro check` + pytest green; commit; push (CI builds); rollout is Jared's call (`deploy.yml`).
- [ ] Seed `workshop` on mash-burn-co after rollout (script for Jared to run as admin).

- [x] Added after the n8n settings review: per-agent `allow_writes` (default off) on top of the allowlist; caller still needs AUTHOR+.

## Review
(at the end)
