# Agent work check — plan

An agent checks its work before it finishes: Marvin looks for gaps it can see itself, and asks the agent to go through
the "Done when" checklist of the Playbooks steering the run, before letting it answer. Gaps go back into the loop.

Decisions (Jared, 2026-10-22): do the core; no step-cap change, no model change, no history caching. **Additive only:
nothing that works today changes** — the check is **off by default** for every agent and workflow step (existing and
new); tool results keep every field they return today and only gain new ones. Playbooks get their "Done when" sections
afterwards (Jared, with me).

## 1. Writes read back what they saved
- `update_draft` (services/ai/authoring.py) keeps its return and gains `saved`: the entry's title, summary, status and
  the values of the fields it changed, read after the write (applied), or the proposed values (staged).
- Audit the other write tools; any that answer only ids gain the resulting state the same way (new keys only).

## 2. "Done when" in Playbooks
- Convention: a `## Done when` heading (case-insensitive; "Done-when", "Definition of done" too) followed by bullet
  lines. `services/ai/work_check.py: done_when(body) -> list[str]`.
- The checklist of a run = the Playbooks in effect (`playbooks_in_effect(session, group_id, convo, thread, scope)`:
  always-load, loaded this run, remembered by the thread), de-duplicated, at most 12 items.

## 3. The gate (services/ai/agent.py + work_check.py)
`run_agent_loop(..., work_check=None)`: when given, at the point the model stops calling tools (after the existing
deferral nudge):
- **Marvin's own checks (no model call, no step):** from the transcript (works across a resume):
  - a tool that answered `{"error": …}` and was not later called again successfully;
  - a draft written this run (`create_draft` / `update_draft`, latest per entry) whose `warnings` (what still blocks
    publishing) are not empty.
- **The checklist (one round, only if there is one):** the agent is asked to go through each item with evidence from
  its tool results, keep working on any it can't show, and end its answer with a "Checked:" list.
- Gaps or an unasked checklist → one user message to the model, `continue`. At most 2 gate rounds, and only while at
  least one step remains; otherwise the run answers as today and the summary records what is unmet.
- `AgentResult.check` (new, default None): `{"criteria": [...], "unmet": [...], "rounds": n}`. With unmet gaps left
  when it answers, the answer gains a short "Still to do:" list (honest, from Marvin's own checks).
- `work_check=None` (every existing caller) → exactly today's behaviour.

## 4. Switch and wiring
- Agent: `check_work` boolean column (default false; migration), in AgentRead/Create/Update. Built-ins: off.
- Workflow agent step: `check_work: bool = False` in the agent step model.
- Callers pass `work_check` only when on: interactive run (`operations_controller` run + resume), MCP/tool `run_agent`
  and unattended (`builtins_agents`), the workflow agent step.
- Stored: `execution.output_json["check"]` and the run's API response `check` (new keys).
- UI: Agents → Edit → Model and access: "Check its work before finishing" toggle (with a hint); workflow builder agent
  step: the same checkbox; AI Executions row detail shows the check (criteria, unmet). Playbook editor: a "Done when"
  hint + an "Add a Done when section" button that appends the heading.
- OpenAPI changes → regenerate + release the SDK first.

## 5. Tests
- work_check: parsing variants, gaps (error then retry ok / not retried; warnings latest per entry), checklist.
- Loop: off = unchanged (existing tests stay green); gate continues on a gap; checklist asked once; 2-round cap; no gate
  on the last step; resume keeps seeing earlier failures; `check` summary; "Still to do" only when unmet.
- update_draft `saved`; agent column round-trip; workflow step option passes through.
- Full suites with and without plugins, ruff, frontend tests, astro check.
