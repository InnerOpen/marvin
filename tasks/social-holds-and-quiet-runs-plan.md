# Why a DM wasn't answered, and run history that says it's partial

Found 2026-10-24 while testing Facebook DM auto-replies: a matched DM was held by the rule's cool-down (the tester had
replied by hand three minutes earlier), and nothing anywhere said so. The run that held it left no history row, because a
run with nothing matched, failed or announced isn't recorded — by design, but since Bluesky 0.4.1 made its chat 501 a note
instead of a failure, *every* routine run is quiet, so the task's history looked like it stopped on 2026-10-23 22:06.

## A. The inbox says why a DM wasn't auto-replied

- [x] `social_inbox_items.held` (JSON, nullable) + migration: `{reason, rule, until?, note?, at}`.
  - `cooldown`: a rule matched but the person was answered by DM within its cool-down; `until` = that reply + cool-down.
  - `refused`: the network refused the DM (e.g. outside Meta's 24-hour window); `note` = the network's words.
- [x] `social_inbox.hold(...)` writes it once (unchanged reason/rule/until → no write); `record_reply` clears it.
- [x] `last_direct_reply_at` returns when the person was last answered; `answered_recently` uses it.
- [x] Engine: the cool-down branch and a refused `_answer_direct` record the hold.
- [x] API: `SocialInboxItemRead.held` (`SocialInboxHeldRead`, with the rule's entry id).
- [x] Inbox UI: a "Not auto-replied" badge on the row; the dialog says why, until when, and links the rule.
- [x] Tests (engine + inbox store + API + frontend helper); docs (social.md); SDK regenerated.

## B. Run history says it's partial

- [x] The assistant's `get_scheduled_task_history` returns the task's real `lastRunAt` / `lastStatus` / `nextRunAt` and a note
      that routine runs with nothing to report aren't recorded.
- [x] The task page shows the last run, its status and the next run above the history, with the same note; the overview
      card's history panel ends with the note.
- [x] Tests; docs.

Not doing: recording every skip in history (the same unanswered, unmatched DMs are re-checked every run — 288 rows a day).

## Review

Shipped together. The full run: SQLite with plugins 6,743, Postgres 6,743, no plugins 6,724 — the one failure was the
social-inbox migration test's list of later columns, which now names `held`; frontend 1,170 pass; astro check 34 (baseline).
`answered_recently` became `last_direct_reply_at` (its only caller needed the time, for `until`). A refused DM is still
re-tried every run until it leaves the 7-day window (one network call per run each) — unchanged here, worth a look.
