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
- [ ] On prod: decide the Foundry Jacket cover approval and see the stamp
