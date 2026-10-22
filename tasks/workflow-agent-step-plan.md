# Workflow step: run an agent (Playbooks step 3) (2026-10-21)

Jared: "So if I wanted a few agents and skills to go with those agents so that I have a very self-sufficient
site…" / "plan step 3". Design: [[ADR-002]] scope item 3 ("A workflow step: run this agent with these Playbooks").

## Why
Agents (persona, permissions, Playbooks, multi-step tools, hand-offs) only work when someone asks them — Ask, the
bubble, `run_agent` over MCP. Workflows run on their own, but their AI is a one-shot `operation` step (custom prompt
or a named op): no Playbooks, no tools across steps, no agent. So "when a Bench Note is published, have Writer draft
the social posts" or "every Monday, have Copy reviewer review the week's changed pages" can't be built. This step
joins the two: a workflow hands a job to a named agent, which works within its own permissions and Playbooks, and
everything it makes lands as drafts for the maker.

## What exists to build on (verified)
- **Unattended agent run**: `builtins_agents._run_standalone` (MCP's `run_agent`) — binds only tools the agent's
  matrix **Allows** at the caller's role (`standalone_tools`), refuses Ask-first ones (nobody can approve mid-loop),
  runs bulk writes unattended, includes the Playbook catalog + always-load Playbooks, records an AI execution.
- **Workflow parking**: the `approval` step returns a park request; the engine parks the run (`waiting`) until a
  decision resumes it from the next step (`services/automation/approvals.py`).
- **Loop guard**: `MAX_REACTION_DEPTH = 3` hops per reaction chain (engine).
- **AI budget / cost**: per-execution tokens and cost; `services/ai/budget.py`.

## The step
```json
{ "kind": "agent", "id": "social",
  "agent": "writer",
  "message": "Draft a Bluesky and a Mastodon post for ${entry.title} (${entry.url}). Drafts only.",
  "playbooks": ["social-post"],          // optional: loaded in full for this run, on top of the agent's always-load (≤ 3)
  "max_steps": 8,                         // default 8, hard cap 15
  "on_entry": true }                      // default: the run is about the trigger's entry (its id/title/url in context)
```
- **Runs** the named agent unattended, like `run_agent` from MCP: the agent's own permission matrix at the
  workflow's authorizer role; only **Allow** tools are offered; Ask-first and Off tools aren't.
- **Output** for later steps: `steps.<id>.output.answer` (text), `.entries` (ids + review links of entries it
  created or drafted), `.playbooks` (used), `.stopped` (`complete` | `max_steps` | `refused`).
- **Writes are drafts** by design (`entries_author` only drafts; publishing isn't an agent tool).
- **Recorded**: an AI execution with trigger `automation` (agent, tokens, cost, steps), linked from the run detail;
  the agent's thread is not shown in Ask.
- **Dry run**: shows the agent, the interpolated message, the tools it would get and the Playbooks — no AI call.

## Guardrails
- **Loops**: entries an agent step creates carry the run's reaction chain, so the depth guard applies; and an
  `agent` step never runs for an event whose chain already ran that same workflow's agent step (no Writer → draft →
  entry_created → Writer …).
- **Cost**: `max_steps` cap; the workspace AI budget is checked before the run (over budget → the step fails with a
  clear message and on_failure runs); the run's cost shows on the run detail.
- **Validation** (save and `draft_workflow`): the agent exists and is enabled, is a persona (not `chat`/model-only),
  the message is non-empty, `playbooks` name published Playbooks, `max_steps` in range. Warn when the agent has no
  write permission but the message asks it to draft.
- **Agents that can't act**: if the agent's matrix allows nothing useful (all Ask first), the step warns at save.

## UI
- Workflow builder: an **Agent** step — agent picker (with its description and what it may do), message (with the
  usual `${…}` helpers), Playbooks multi-select (published only), max steps.
- Run detail: the agent's answer, the drafts it made (links), Playbooks used, tokens/cost, link to the AI execution.
- Approvals stay a separate step: put an `approval` step after the agent step to gate what happens next (e.g. post
  only after approval), or rely on drafts landing in the Inbox.

## Authoring and Library
- `workflow_authoring_guide` + `draft_workflow` learn `kind: agent`; Builder can draft one.
- Two Library recipes (need an agent with author permissions):
  - `agent-on-publish` — "When an entry of a type is published, have an agent draft something from it" (vars:
    entry_type, agent, message, playbooks).
  - `agent-weekly-review` — "Every week, have an agent review recently changed entries" (schedule; vars: agent,
    entry_type, message). Its output (the answer) is kept as the run result; findings the agent drafts land in the
    Inbox.

## Decisions (recommendations; Jared to confirm)
1. **Ask-first tools are not offered** to an agent in a workflow (as over MCP). Gate with an Approval step instead.
   Alternative (later): park the whole run when the agent wants an Ask-first tool, resume on approval — much more
   machinery (resuming an agent loop inside a workflow run).
2. **Permissions = the agent's own matrix** at the workflow authorizer's role (not External assistants, not a
   new matrix). Set Writer to "Entries: author → Allow" for it to draft from a workflow.
3. **Per-step Playbooks** allowed (up to 3, loaded in full for that run), on top of the agent's always-load.
4. **Output** = answer + created entries + playbooks + stopped, for later steps.
5. **Loop guard** as above (depth + no same-workflow agent re-entry).
6. **Defaults**: max_steps 8, cap 15; budget checked first.
7. **Not in this pass**: per-run model override, streaming progress in the run view, an agent step inside
   `repeat`/`parallel` (refused at save for now), parking on Ask-first.

## Order
1. Executor (`actions/agent.py`) on `_run_standalone` internals (extract a shared runner both use), output shape,
   dry run, budget check, loop guard. 2. Validation + authoring guide + `draft_workflow`. 3. Builder UI + run detail.
4. Library recipes + catalogue + docs (manual workflows page, Playbooks page). 5. Tests (below). One push.

## Tests
- Executor with a fake provider: runs the named agent with only Allow tools; Ask-first/Off tools absent; always-load
  + step Playbooks in the system frame; output answer/entries/playbooks/stopped; writes land as drafts; AI execution
  recorded with trigger automation; max_steps respected; over-budget fails cleanly; disabled/unknown agent fails.
- Loop guard: an agent-created draft's entry_created doesn't re-run the same workflow's agent step; depth guard holds.
- Validation: unknown agent, model-only agent, bad Playbook, max_steps out of range, inside repeat/parallel.
- Dry run makes no AI call. Workspace isolation. Builder: npm tests for the step editor's pure parts.
- Full SQLite + Postgres; astro check at baseline.
