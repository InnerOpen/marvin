# Approval with a picture (2026-10-14)

Jared: "How can I see if it's too dark if it hasn't run yet for approval?" — the cover recipe asks before the paid
generation, so there is nothing to look at. Fix: an approval step can show a picture, and a run can ask twice.

- [ ] `ApprovalAction.image` → executor → `WorkflowApprovalModel.image_url` (+ migration) → `park`
- [ ] `WorkflowApprovalRead.image_url`, event payload, dashboard `ApprovalBrief.image_url`
- [ ] Entry op `attach_asset` (`asset`, `role`) so attaching waits for the second approval
- [ ] Approvals page + dashboard cards show the picture; editor's approval form gets a Picture field
- [ ] Recipe `alternate-universe-cover`: approve the spend → generate (not attached) → approve the picture (shown) → attach; test + catalogue
- [ ] Validator/guide; SDK types; what's-new
- [ ] Verify: tests; local dev click-through

## Review
