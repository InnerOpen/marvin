# A daily limit on paid approvals (phase 4 of the approval work)

Agreed by Jared 2026-11-16 ("yes all seem reasonable"): an optional per-workspace daily limit on paid approvals, with a
warning before it and a block past it; stored in settings, not hard-coded. Phases 1-3 (#265, #266, approve-many) are the
ground it stands on.

## What counts
- A **paid approval** is one that guards a paid step: an integration step after it (up to the next approval, a
  `repeat`'s or a `parallel`'s own steps included) whose provider action is `cost_hint: paid` or needs an approval —
  the rule the likely-cost line uses (services/integrations/estimate.py), looking inside a repeat. It is decided at park time and kept on the row (`workflow_approvals.paid`,
  boolean), so the count never re-reads workflows and a workflow edited later does not change history.
- **Used today** = this workspace's approvals with `paid` true, settled `approved`, `decided_at` since midnight UTC.
  (UTC, not the workspace's timezone: there is no workspace timezone setting to read; the card says when it resets.)
- Not counted: a deny, an expiry, a stale; an `approved_when` that went on unasked. A batch that makes inside its
  repeat (*Record lines*) counts once. **A batch that only queues entries for other runs (*Make the stills*, *Make the
  sounds*) is not counted at all**: its approval guards no paid step itself, and each item's run goes on through
  `approved_when`. That is the honest limit of counting approvals rather than calls; a limit on calls or credits per
  provider (counted from the AI-executions rows the paid steps write) is the follow-up (below).

## Where it is kept
`group_preferences.paid_approvals_per_day` (int, nullable, 1-1000; null = no limit), beside `approval_expires_hours`
and `max_workflow_steps` (Settings → General → Workflows: "Paid approvals a day"). Owners and admins set it, as the
other workflow limits. One migration adds both columns (the preference and `workflow_approvals.paid`).

## What a person sees
- A pending paid card: "3 of 20 paid approvals used today" under the likely cost; at 18-19 of 20 it says "2 left
  today"; at the limit Approve is off and the card says "Today's limit of 20 paid approvals is reached (Settings →
  General). It resets at midnight UTC. Deny still works."
- **Approve all N** says "only 4 of 9 can be approved today" and approves in order until the limit; the rest come
  back refused with that reason (they stay waiting).
- API: `spend_limit: {limit, used_today, resets_at}` on a pending paid approval; `decide`/`decide-many` refuse an
  approve past it with 409 and that message. Deny is never limited.

## Edges
- Two people approving the last slot at once: the count and the claim happen in one transaction per decision, so at
  worst one goes one over under a race (a hard guarantee needs a row lock per workspace; not worth it for a courtesy cap).
- An admin may still raise or clear the limit to go on the same day.
- Not covered: credits. A later `credits_per_day` per provider (ElevenLabs credits from the tally's rule, dollars for
  images) would stop a single huge call; it needs the estimate to be known (it is often "cost unknown"), so it waits.
