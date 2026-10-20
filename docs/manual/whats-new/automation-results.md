# Automation results

When a workflow hands work to another system (starts a run in another tool, kicks off a build) Marvin only knows the call went out. **Automation results** keeps one record of each hand-off, so you can see whether it came back, and what happened when it didn't.

It lives under **Settings › Automation › Results** (`/automation/results`), next to Approvals, Events and Metrics. There is no sidebar item: the dashboard and the entry editor tell you when something needs a look.

## What gets recorded {#recorded}

A connection's action can declare that it **hands work off** (the integration SDK's `hands_off`, see [Integrations → Hand-offs](integrations.md#hand-offs)). Nothing for a workflow author to add: when a **Run integration** step calls such an action, Marvin writes the record itself.

| What happened | The record |
|---|---|
| the call went out | **In flight** |
| the call itself failed (the other system refused it, was unreachable, a credential was wrong) | **Failed**, with the connection's message (never a credential) |
| the other side reported back | **Succeeded** or **Failed**, or still **In flight** if it says it is waiting |

The same goes for a hands-off action Marvin runs **outside a workflow step**: an [event connection](integrations.md#hand-offs) such as the site rebuild's **Deploy** (Cloudflare Pages), which a [site rebuild](../operations.md#site-rebuilds) runs when it sends `webhook_triggered`. That record has no workflow and no entry. An action that only sometimes hands off (Buttondown's **Create issue email**: a send does, a draft does not) records only when it did.

Each record keeps the entry the work was about, the connection, the Marvin workflow whose step made the call, what was asked of the other side (for an n8n workflow, its path), the run's id and a link to it on the other side, a message, when it was sent and finished, and the attempt (a retry of the same hand-off counts up; it does not add a record).

The words are Marvin's: **In flight**, **Succeeded**, **Failed**. A connection turns its own words into these (n8n says `success`, `error` and `waiting`).

### No reply {#no-reply}

A record still in flight a day after it was sent shows as **No reply**. It is not a status of its own and nothing is failed for you: it is the same record, flagged, so a lost report is visible. If the other side reports later, the record settles as usual.

## Reporting back: the Record an automation result step {#step}

Reporting back is a step of the **plugin's own workflows** for the connections that ship them. Cloudflare Pages' three notification workflows settle the build (by its deployment id, in Cloudflare's own words); Buttondown's `buttondown-email-sent` settles a send when Buttondown posts `email.sent`. They name no connection: Marvin reads the other side's words through the connection that installed the incoming webhook. A late **started** never reopens a result that already succeeded or failed (deliveries are not ordered). A report that matches nothing (a build started by a git push, an email sent from Buttondown's own dashboard) is listed as a new result.

The other side reports back however it can (typically a call to an [incoming webhook](incoming-webhooks.md) that starts a workflow). That workflow settles the record with a **Record an automation result** step; see [Workflows → Record an automation result](workflows.md#record-an-automation-result).

## The page {#page}

The page and its entry in the Automation tab appear only once a result exists. Until then there is nothing to show, and nothing in the way.

- **Status** tiles: **In flight**, **No reply**, **Failed**, **Succeeded**, each with a count; tap one to filter. The counts leave out the ones you dismissed.
- **Connection** and **search** (the entry, the target, the message, the run id).
- A row is compact on every screen: the entry, the connection with its logo, what was asked, a status badge, when, and the message. **Tap a row** to open it.
- An open result has **Open entry**, **Open the run** (the link on the other side, when the connection gave one), and, for admins:
    - **Retry** repeats the hand-off. See [Retry](#retry).
    - **Dismiss** marks a failure as dealt with, or a hand-off still in flight as one you no longer expect a reply to (a reply that can never match it, a run cancelled on the other side). It stops counting as failed, in flight or No reply and reads *Dismissed*; the record stays until it is pruned. A late reply still settles it, and a failure reported again asks for a look again. A succeeded result has nothing to dismiss.

Editors and above can read the page. Retry and Dismiss are for **admins** and above, because a retry calls the other system with the workspace's credentials.

### Retry {#retry}

Retry runs the **hand-off step of the Marvin workflow that made the call, again, for the same entry**, as the entry is now. Only that one step runs, not the rest of the workflow (which may have posted or emailed). It runs under the workflow author's role, as every run of the workflow does.

A repeat that goes out is **In flight** again, as the same record (the attempt goes up by one). One that fails again stays **Failed**, with the new message. The connection's usual error handling does not schedule more retries behind your back: you are the retry.

Marvin refuses a Retry it cannot do honestly, and says why:

- the workflow was deleted, or is switched off;
- the workflow no longer has that step, or has several that look the same;
- the entry is gone, or no longer matches the workflow's conditions;
- the step reads from the run that first started it (the event's payload, an earlier step's output), which is over: **open the entry and run the workflow again** instead;
- a result that came back from a report with no workflow behind it (nothing of ours to repeat).

## Where it shows up {#attention}

- **Dashboard**: under *Needs attention*, **Hand-offs that failed** and **Hand-offs with no reply** link to the page filtered to them. A hand-off in flight is routine and is not a to-do.
- **Entry editor**: under the status, a line for an entry with a recent hand-off: *Sent to ⟨connection⟩ · in flight*, *no reply yet*, or *⟨connection⟩ failed: ⟨message⟩*, with **Open the run**.

## Retention {#retention}

A daily system task, `prune_automation_results`, keeps the table small: a **succeeded** result (or one you dismissed) goes **30 days** after it finished; one still **in flight** or **failed** that nobody dismissed goes after **180 days**, so it keeps asking for a look. `retention_days` on the task changes the 30 (`<= 0` keeps everything). See [Scheduled tasks](scheduled-tasks.md) and [Operations → Retention](../operations.md).

## API {#api}

`/api/groups/automation-results`, editors and above to read, admins and above to act:

| | |
|---|---|
| `GET /summary` | `show` (whether any result exists), `inFlight`, `noReply`, `failed`, `succeeded`, `attention`, `can.act` |
| `GET /` | the results, newest first; `status` (one or more of `in_flight`, `no_reply`, `failed`, `succeeded`), `connection` (slug), `entry_id`, `q`, `include_dismissed`, `limit`, `offset`; also `counts` and the `connections` that have results |
| `GET /{id}` | one result |
| `POST /{id}/retry` | admin; `409` with the reason when it cannot be repeated |
| `POST /{id}/dismiss` | admin; `409` for a succeeded result (a failed or in-flight one can be dismissed) |

## When n8n was the first

Until this release, the n8n plugin kept this in entry metadata (`n8n_status`, `n8n_execution_id`, `n8n_workflow`, `n8n_finished_at`, `n8n_message`) and two private smart collections, **n8n: failed** and **n8n: in flight**. The migration turns each entry's metadata into one result (`sent` and `waiting` are in flight, `success` succeeded, `error` failed; the result is attached to the workspace's n8n connection when there is exactly one), removes those keys, and removes the two collections **only where they are still exactly what the plugin created** (smart, private, the plugin's own rules, from no other blueprint). A renamed, public or edited one is yours and stays. An imported result has no workflow, so it cannot be retried; an old *sent* with no report reads as **No reply**, because nothing ever recorded when it was sent beyond when the entry last changed.

## Since

Automation results (`automation_results`, migration `d3b9f27a6c14`, the `automation_result` step, `/api/groups/automation-results`, the `prune_automation_results` system task, integration SDK 0.13.0 `hands_off`): 2026-10-25. Builds and sends from Cloudflare Pages 0.3.0 and Buttondown 0.9.0, event connections recorded, `record_if` (integration SDK 0.14.0): 2026-10-26.

## Related

- [Workflows](workflows.md) · [Integrations](integrations.md) · [n8n](n8n.md) · [Incoming webhooks](incoming-webhooks.md) · [Scheduled tasks](scheduled-tasks.md)
