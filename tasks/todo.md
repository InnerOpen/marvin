# Approval with a picture (2026-10-14)

Jared: "How can I see if it's too dark if it hasn't run yet for approval?" — the cover recipe asks before the paid
generation, so there is nothing to look at. Fix: an approval step can show a picture, and a run can ask twice.

- [x] `ApprovalAction.image` → executor → `WorkflowApprovalModel.image_url` (+ migration) → `park`
- [x] `WorkflowApprovalRead.image_url`, event payload, dashboard `ApprovalBrief.image_url`
- [x] Entry op `attach_asset` (`asset`, `role`) so attaching waits for the second approval
- [x] Approvals page + dashboard cards show the picture; editor's approval form gets a Picture field
- [x] Recipe `alternate-universe-cover`: approve the spend → generate (not attached) → approve the picture (shown) → attach; test + catalogue
- [x] Validator/guide; SDK types; what's-new; labels + manual (`2d1967cf`)
- [x] Verified on prod (develop-2d1967c, head 4aa75d81d41f, column present). Still to click through: an approval with a picture.

## Review

# Generated image: links and lists on a phone (2026-10-14)

Jared: a generated cover attached to the entry — "does it get published immediately?"; the asset page's "Made by…
UUID" should link; Resources rows should open like Assets; View/Edit/Trash off-screen on a phone.

- [x] Lineage line links the entry (title) and the workflow (`?workflow=<id>`); File Metadata links `made_for_entry`
      and `workflow_id` (`metaLink`, tested)
- [x] Resource rows open on tap (`data-href`); `.table.stacks` stacks Assets/Resources rows under 640px
- [x] `npm test` 691 pass; astro check: no errors in the changed files; `ff8a2275` pushed
- [ ] Verify on prod at phone width

## Review

Attaching never publishes: the entry keeps its status. A published entry's new attachment is live on the next
coalesced rebuild (the attach event queues one), so the picture approval step is the gate.

# A picture's decision stays with it (2026-10-14)

Jared: "does the metadata carry the decision if I say no?" → "the word"; "on Approval we should attach a decision".

- [x] `approvals.settle` → `_stamp_picture`: `metadata.approval` = decision (approved/denied/expired/stale), who, when, note, approval id — on the workspace asset the approval's `image` names (storage key in the URL); best-effort
- [x] `decision` filter in `item_query` (library, workflow asset targets, collect) + `GET /api/platform/assets?decision=`; SDK types (`542a5a8`, main)
- [x] Asset page: "Denied by Jared on <date> — “note”"; list/grid **Denied**/**Approved** badge; library **Decision** select
- [x] Manual (approval section + query keys); tests: approvals (deny/approve stamp), library filter, frontend lib
- [x] Full backend suite green; `npm test` 693; astro check clean on the changed files
- [x] Live on prod (develop-6c99c7f). No approval with a picture exists there yet: the installed cover workflow is the one-approval copy; Jared: leave it ("no")

# Dashboard tidy (2026-10-14)

- [x] One frame, two column stacks, every section a panel (`f2e6893`); Recent activity to the left column (`ce8ac7d`); both live

# Prompt caching (2026-10-14, Jared: "Do caching first then")

A bubble "hello" sends ~30k prompt tokens, ~90% the 53 tool schemas, resent every call; no plugin uses caching and
cached tokens aren't reported or priced. Feed (LiteLLM): cached input = 0.1× input on all three vendors; Anthropic
cache writes 1.25×.

- [x] SDK 0.10.0 (`42b67323`): the two counts on CompletionResult, cache rates on ModelPrice, contract test
- [x] Anthropic 0.2.0 (`c1b84c9`), OpenAI 0.2.0 (`640c26a`), Google 0.2.0 (`8c0ff71`) — released, tags moved onto the real commits
      (first push tagged the old heads because `git add uv.lock` tripped on .gitignore)
- [x] Core: `estimate_cost(..., cached, cache_write)` at every call site; feed reads `cache_read_input_token_cost` /
      `cache_creation_input_token_cost`; AIExecution columns + migration; AgentResult accounting; Executions page "(n cached)";
      manual; pins; SDK types (`c302f2e`) — live on prod as develop-1dcb26c (head 5c5fa5536fc3, columns present, plugins 0.2.0 loaded)
- [x] Verified on prod 2026-10-14: OpenAI 15,035→$0.0114 then 14,848 cached→$0.0015, expiry after 9 min, tool loop 29,696 cached→$0.0046; Anthropic write 29,834→$0.0764 then read→$0.0084. M&B restored to OpenAI.

# Admin batch (2026-10-14, Jared: "do these")

- [x] Workflow run retention: system task `prune_workflow_runs` (WORKFLOW_RUN_RETENTION_DAYS, default 90) deleting
      finished automation_executions (+ their action executions) older than the window; never a run still waiting;
      on Database & cleanup it shows as what keeps "Workflow runs" in check
- [x] Site Settings: delete the dead settings (API_HOST + 6 OPENAI_*), chart drops apiHost; a warning card when
      BASE_URL/FRONTEND_URL are still localhost; FRONTEND_PORT labelled as the frontend pod's
- [x] Settings: email branding (platform: name, footer, accent colour → branded.html); Admin → Site Settings
      "Security" section editing the SECURITY_* knobs as platform settings that override env; workspace limits
      (agent max steps, chat memory turns, bulk-write ask threshold, approval expiry default, workflow max steps)
- [x] Admin Overview: health strip, workspaces table (entries, AI spend vs limit, last activity, alerts), AI spend
      30-day chart with cached share

## Review (admin batch)

Built and checked on the dev server (every page renders; Security, Branding and workflow-limit saves round-trip):
prune_workflow_runs (WORKFLOW_RUN_RETENTION_DAYS 90, never running/waiting; Database & cleanup now shows it), seven
dead settings gone (API_HOST + six OPENAI_*; chart 1.5.2 drops apiHost), Site Settings warns on a localhost UI address
and notes four settings, services/platform_policy.py (security values override env, cached 15 s; email branding
into all three templates), budget_config agent_max_steps / history_turns / bulk_ask_threshold, group_preferences
workflow_max_steps / approval_expires_hours (migration f179fc8388df), Admin Overview health strip + workspaces table +
30-day AI spend with cached share. Tests: test_platform_and_workspace_limits (6), maintenance prune (2).
