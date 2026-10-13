# Dashboard first pass (2026-10-13)

Jared: "do the first pass" — of the dashboard ideas: Waiting on you, Coming up, health strip, workflow sparkline.

## Plan
- [x] Backend `GET /api/platform/stats/dashboard`: extend `DashboardData` (`services/dashboard.py`)
  - [x] `attention`: + `approvals`, `parked_runs`, `oldest_draft_days`, `oldest_inbox_days`
  - [x] `approvals` (oldest 3, decided inline), `upcoming` (7 days: publishes, resumes, scheduled tasks)
  - [x] `health`: backups (platform admins only), integrations failing, webhook deliveries failed 24h, workflow runs failed 7d, email, push
  - [x] `runs_by_day`: 14 days of {day, ok, failed}
- [x] Frontend `workspace/index.astro`: health strip, approval cards + parked-runs row + ages, Coming up panel, inline-SVG sparkline
- [x] Tests: `tests/test_dashboard_panels.py` (5, one behaviour each)
- [x] SDK: types regenerated, MarvinSDK develop + main (`152a04a`)
- [x] Phone check (390px): no overflow; panels stack
- [x] Docs: what's-new bullets; journal

## Review
- Everything the four panels show already existed in the DB; no migration. Invites have no expiry column, so "expiring invites" was dropped from Coming up.
- Backups are platform-wide (no group_id), so the backup dot shows only to platform admins and only when a target is configured.
- Verified in local dev with seeded demo rows (deleted afterwards): approvals oldest-first with choice buttons, parked-runs row, "3 workflow runs failed (7 days)" matching the seeded failed+partial runs, Coming up with a resume and a task, sparkline 14 bars with red failures.
- Not done (second pass): publishing-velocity chart, AI spend, "pick up where you left off", pinned entry-type cards, trimming the inventory count cards.
