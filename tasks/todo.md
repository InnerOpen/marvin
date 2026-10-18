# Workflow Library — finish phases 1+2 (2026-10-17)

Jared: "Finish Workflow Library" → phases 1+2 (Recommended); one local commit per slice, Jared pushes.
State at start: 95 verified-current, 11 supported-after-configuration, 6 needs-engine-capability, 3 needs-adapter
(`recipes/catalogue.json`); `docs/workflow-library/roadmap.md` is stale (approvals, waits, repeat, run inputs,
member triggers shipped 2026-10-11→14 but aren't struck). Slices run one at a time (one pytest at a time).
Every slice: dry run + second run tested for any recipe it unblocks; catalogue counts + roadmap row updated;
`task docs:openapi` if the automation definition changes; full suite green (grep FAILED lines) before commit.

- [x] S0 Audit + refresh (2026-10-18; 10 done, 3 partly, 11 open; counts unchanged): each of the 24 roadmap gaps vs code → roadmap.md / catalogue.json status
      (e.g. agent-directory-intake still lists `fetch`, done 2026-10-12)
- [x] S1 Custom events `custom.<name>` (2026-10-18; 96 verified-current, 5 needs-engine-capability): registered per workspace
      in `group_preferences.custom_events_json` (migration c32c63c7a131; Settings → Automation → Custom events), emit_event
      templated `payload` held to typed fields, triggerable + subscribable, depth-bounded → achievement-cabinet runs
- [ ] S2 Schema check step: validate a JSON document (e.g. a fetch step's body) against a JSON schema,
      violations as output → choose-your-own-adventure, agent-directory-intake run
- [ ] S3 Ops events as triggers: ai_budget_*, integration_attention_*, webhook_delivery_failed,
      scheduled_task_failed, with origin filtering (never react to a failure the run itself caused)
      → integration-health-companion, webhook-repair-desk become workflows
- [ ] S4 Member-addressed email: member_added carries the member's email / recipient `member` → new-member-welcome
- [ ] S5 Parallel branches + join (all/any, deterministic merge, partial-failure semantics) → publication-release-gate
- [ ] S6 Metrics windows: a step records an observation per variant/window; a report lists them (no causal claims)
      → social-experiment-log (campaign-scoreboard still needs social adapters)
- [x] A1 Admin (Jared 2026-10-17 "Ok"): Embeddings card on admin/system.astro — model (`BUILTIN_EMBEDDING_MODEL`),
      enabled/available, fastembed + onnxruntime versions (importlib.metadata), dimensions, indexed model ids + chunk
      counts — via `embeddings` on GET /api/admin/about (no model load); Admin → Plugins rows show
      "update available → vX.Y" from `plugin_updates.available_updates` (today only Overview lists them)
- Out of scope (phase 3 / later): TTS adapter (audio-edition), social adapters (poll-companion, campaign-scoreboard),
  comments (reply-drafting-desk — Marvin has no comments feature)

# Bring your own storage — slice 5 (2026-10-14)

Jared: "Stage 5". The workspace's own backups, in its own private bucket (never its file bucket).

- [x] SDK v0.12.0 (BackupTarget.workspace_settings/endpoint_setting) + marvin-storage-s3 v0.3.0 (S3BackupTarget declares them)
- [x] Migration 4166a87cee01 (after MCP's 10b5c7c078c7): connections.purpose, settings.backup_connection_id/backup_keep
- [x] `workspace.plugin_class` / `build_connection_target` (no platform bucket, no workspace file bucket);
      purpose-aware specs/create/check (backups: check_target, no public URL), set_mode/copy refuse backup buckets
- [x] `services/storage/workspace_backups.py`: save (keys `marvin-backups/<slug>/<stamp>-<bundle>`, keep N), list,
      fetch (sha256-checked), backup_now, events workspace_backup_saved/_failed
- [x] Daily bundles task also saves to a workspace's own bucket; "Back up now" = task backup_to_workspace_bucket
- [x] API: PUT /backup-bucket, GET/POST /backups, GET /backups/download; page: Backups section, add form "For"
- [x] Tests (4): private check + choose + back up now + list + download + key guard; keep N; never share; daily task
- [ ] Browser check: shared local dev servers can't be swapped (permission denied) → check on admin-dev after deploy
- [ ] Live R2 check needs a second private bucket + key from Jared
- [ ] Full suite (marvin_test_byo); SDK main; push from the worktree (rebase onto origin/develop, one alembic head)

# Bring your own storage — slice 4 (2026-10-14)

Jared: "move on to the next slice". Health task, events, Admin/Backup-health visibility, bundle toggle.

- [x] `consecutive_failures` (migration c6822c311b2b); `workspace_admin.health_check` (2 failures → failing +
      `workspace_storage_unhealthy`; pass → ok + `workspace_storage_recovered`; never re-verifies keys)
- [x] Hourly system task `check_workspace_storage` (connections in use + failing ones; None when there are none)
- [x] Bundle toggle (PUT `/groups/storage-settings/bundle`, page checkbox); exporter skips ws: files unless on
- [x] Admin: GET `/api/admin/storage/workspace-buckets`, table on Admin → Storage, note on Backup health
- [x] Guard: a ws: row is only read from its own workspace's connection (provider_for row, public URLs, exporter,
      attachments, upload service reads)
- [x] Tests (5): blip/two failures/recovery + events, nothing to say, bundles, cross-workspace refusal, admin list
- [ ] Full suite; SDK main; push; dev/prod check

# Bring your own storage — slice 3 (2026-10-14)

Jared: "Next slice". Copy existing files into a workspace's bucket (explicit only; originals never deleted).

- [x] migration.migrate guard: a `ws:` target needs `--workspace`, the connection's own workspace, not retired
- [x] `workspace_admin.copy_plan` (files/bytes by location, entries embedding links via the workspace code) and
      `start_copy` (a disabled, run-on-demand workspace scheduled task `copy_to_workspace_storage`)
- [x] Handler `scheduled_tasks/handlers/storage.py` (policy on + verified connection; failures fail the run)
- [x] API: GET/POST `/groups/storage-settings/connections/{id}/copy`; page: "Copy existing files here…" dry run → start
- [x] Tests (4): guard, plan counts incl. linked entries, full copy keeps originals, verified-only/OWNER-only
- [x] Local E2E with the real R2 test bucket: dry run 51 files 3.8 MB → started from the page → task success
      "51 copied, 51 moved, 0 failed" → moved image serves 200 image/jpeg, original kept → CLI rollback to local → 52 local
- [ ] Deferred: pruning the platform copies after a move (needs a moved-at record and a grace period)
- [ ] Full suite; SDK main; push; dev check

# Bring your own storage — slice 2 (2026-10-14)

Jared: "start BYO storage slice 2". Settings page, API, check connection, policy, SSRF, audit.

- [x] `services/storage/workspace_admin.py`: provider field specs, create/update (bucket/endpoint/prefix fixed)/retire,
      check (storage check + public-URL probe via the SSRF-guarded client), set_mode, view, save_policy
- [x] Key fingerprint (HMAC with SECRET) recorded on a passing check; keys changed later stop uploads (write_target)
- [x] `routes/groups/storage_settings_controller.py` (OWNER edits, ADMIN reads) + `/api/admin/storage/workspace-policy`
- [x] Events: storage_provider_changed (mode), workspace_settings_changed `storage` (no rebuild), platform_settings_changed
- [x] Pages: Workspace → Storage (`/workspace/settings/storage`, nav + settings card), Admin → Storage policy card
- [x] Tests: tests/test_workspace_storage_api.py (12) — roles, add/check/switch, public URL failing, rotated keys,
      fixed bucket, refusals, retire, policy
- [x] Local end to end with the real R2 test bucket: policy on → Check connection Verified (incl. public URL) → switch
      → upload via /api/platform/assets/upload lands in marvin-byo-test and serves 200 → policy off → 503 → restored
- [x] Manual: docs/manual/workspace-storage.md (nav); SDK types additive (schema names prefixed WorkspaceStorage* to
      avoid clashing with admin StorageCheckStep / StorageProviderOption)
- [ ] Full suite; SDK main; push; dev check

# Bring your own storage — slice 1 (2026-10-14)

Jared: "start BYO storage slice 1". Plan + decisions: tasks/byo-storage-plan.md. Slice 1 = SDK/plugin + inert core
(policy off by default, no UI): a workspace can't opt in through the app yet; tests and dev prove the wiring.

- [x] SDK 0.11.0: `StorageProvider.workspace_settings`, `endpoint_setting`, `public_url_setting`; conformance check
- [x] marvin-storage-s3 0.2.0 declares them (keys and public URL required); tests
- [x] Core pins SDK 0.11.0 + plugin 0.2.0; lock
- [x] Models + migration: `workspace_storage_settings`, `workspace_storage_connections`
- [x] `services/storage/workspace.py`: policy, endpoint policy (`known`), `provider_for_connection` (cached by id+version,
      never env), `write_target` (fail closed: `WorkspaceStorageUnavailable`)
- [x] provider_factory: `ws:<id>` rows resolve to their connection; public URLs from the connection
- [x] `AssetStorageService.for_workspace(repos)` records the location; sweep the 9 call sites; 503 on unavailable
- [x] Tests (tests/test_workspace_storage.py, 18): a stand-in plugin instead of moto (CI has no plugins group); fail closed in
      every case, platform storage untouched; old rows keep reading; own-bucket refusal; endpoint policy; a mutation
      check (endpoint policy disabled) fails 5 of them
- [ ] Full suite; push; live check on marvin-dev with a throwaway R2 bucket (needs Jared: bucket + token)

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
