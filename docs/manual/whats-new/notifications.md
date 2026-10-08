# Notifications

**Settings → Automation → Notifications** (`/automation/notifications`, workspace owners and admins) sends the workspace's own failures past the bell: a workflow or scheduled task that fails, a connection that needs attention. It does for one workspace what [Platform alerts](../offsite-backup.md#getting-alerts-outside-marvin) does for the platform, with the same channels and the same code. It replaces the **Integration alerts** card that used to sit on the integrations' **Alerts & health** page.

## What it does

**Which events notify.** One switch per kind:

| Kind | Event | Default |
| --- | --- | --- |
| Workflow failed | `automation_failed`; "working again" on the next `automation_ran` | on |
| Scheduled task failed | `scheduled_task_failed`; "working again" on the next `scheduled_task_completed` | on |
| Integration needs attention | `integration_attention_needed` (and its reminders); "working again" on `integration_attention_resolved` | on |
| AI operation failed | `ai_operation_failed` | off |
| Webhook delivery failed | `webhook_delivery_failed` (after the delivery's retries) | off |
| Trash emptying soon | `trash_auto_empty_soon`: the Trash's auto-empty deletes items forever within a day (at most one a day). Email and connections only — push for it is each owner's and admin's Profile choice (**Trash reminders**) | off |

**Once per incident.** A workflow that keeps failing sends one alert, not one per run; when it next runs successfully, one "Workflow working again" note goes to the channels that got the alert (even one turned off since), with how many runs failed and since when. Each workflow, and each scheduled task, is its own incident. A failure an integration's [error policy](integrations.md#when-an-integration-fails) handled (sent to review, retry scheduled) doesn't alert: the integration's own *needs attention* alert says what a person must do. Integration alerts were already once per connection and error, with a reminder while they stay open (**Remind every N hours**, on this page; 0 never reminds; default 24); their "working again" notice goes back through the channels the alert went out through. AI operation and webhook delivery failures send one each.

A scheduled task run with nothing to report is normally not logged; the first successful run after a failure now always is (with its `scheduled_task_completed`), so its "working again" note goes out.

**Email** is built in and on by default. It goes to the workspace's owners and admins with an email address, or to a list you type, through the workspace's SMTP profile (Settings → Email → SMTP), else the platform's SMTP settings. Without either, the page says so and each notification is recorded as *not sent*.

**Integrations.** Any action on one of the workspace's connections that can carry a message can be a route: Slack's *Send message* (with its channel), Apprise's *Send notification*, or any other plugin's — found from the plugin's own declaration (an action with the `notify` capability, or any action of a `notify` plugin with a text input), never from a list of names. An action that takes more than the message asks for it; `{{SECRET}}` references to the workspace's secrets work there. One action can serve several routes (two channels). With nothing message-capable connected, the page says so and links to **Add a notification channel** (the Integrations page's Notify group).

**Push**, when the server has Web Push set up: to the phones and browsers of the owners and admins who turned notifications on with *Workspace alerts* in their Profile. On by default, with its own kinds, last delivery and **Send test**; without VAPID keys there is no Push channel and nothing changes. See [The app and push notifications](../app-and-push.md).

**Each channel takes every kind, or only some.** Email and each route default to every kind that is on; untick kinds on a channel to keep it to the rest (say, scheduled tasks to `#ops`, everything else by email). A kind switched off goes nowhere.

**What a message says:** what failed and why (the workflow's or task's name and error, scrubbed of credentials), the scope *Workspace — <name>*, why it was sent, and a link to the page to look at (the workflow, the task, Alerts & health). Never an event's raw payload or a connection's credential.

**Delivery and failures.** One attempt per channel, no retries. A channel that fails is logged and shows its *last delivery* (sent, not sent, failed and why) on the page; it never stops the other channels. **Send test** on each channel sends "Test notification from Marvin", even when the channel is off.

**Only this workspace's events.** Platform events (backups, storage, accounts, security) never reach a workspace's notifications, even when they were dispatched under its id; those are [Platform alerts](../offsite-backup.md#getting-alerts-outside-marvin)'. A workspace never gets another workspace's events.

**Audit.** Saving records `workspace_settings_changed` (`changed_fields: ["notifications"]`) listing what changed — routes by name, never their arguments. It queues no site rebuild.

## Upgrading

The Integration alerts card wrote ordinary event subscriptions for `integration_attention_needed`. The upgrade (migration `cfbbd1cc67e4`) moves them here so integration alerts keep going exactly where they went:

- a workspace with a connection gets explicit settings: email takes integration alerts only if the card's **Email the workspace's owners and admins** was on (a new workspace gets them by default), and each chat connection the card sent to becomes a route that takes only integration alerts (on or off as it was);
- an alert open at the upgrade still sends its "working again" notice where it went;
- the card's subscriptions are deleted. A subscription on `integration_attention_needed` set up on the Events page (another template, other recipients, other arguments) is left alone and keeps working.

Messages now use the format above rather than the **Integration Alert** email template; that template stays available for Events-page subscriptions. Downgrading drops the settings; the old card would start empty.

## API

| Method | Path | |
| --- | --- | --- |
| GET | `/api/groups/notifications` | `types` (each kind, on or off), `email` (`enabled`, `recipients` or null for owners and admins, `kinds` or null for all, `adminEmails`, `smtpReady`, `lastDelivery`), `routes` (with `kinds`, `label`, `problem`, `lastDelivery`), `targets` (what a new route can use, with each action's inputs), `integrationsAvailable`, `integrationReminderHours` |
| PUT | `/api/groups/notifications` | `types` (kind → bool; left out keeps its setting), `email`, `routes` (`id` keeps a saved route; omit for a new one), `integrationReminderHours`. 422 with the reason when something can't work (unknown kind, not an email address, a connection that can't carry messages or isn't this workspace's, a missing channel) |
| POST | `/api/groups/notifications/test` | `{"channel": "email"}` or a route id; 404 for an unsaved route |

All three are workspace ADMIN/OWNER (403 otherwise). Stored on `group_preferences` (`notifications_json`; `notifications_status_json` for the last deliveries); open incidents in `workspace_alert_incidents`. A workspace backup carries the settings (routes by their connection's slug).

Code: `services/alerting.py` (shared with platform alerts), `services/workspace_alerts.py`, `WorkspaceAlertListener`.

## Limits

- No retries: a channel that is down when an alert goes out misses it (its last delivery says so).
- AI operation and webhook delivery failures aren't grouped into incidents; leave them off if a broken provider would send many.
- A workflow failure that a retry later fixes still sent its alert; the retry's success sends the "working again" note.

## Related

- [Integrations](integrations.md#integration-alerts) — when a connection needs attention.
- [Workflows](workflows.md) and [Scheduled tasks](scheduled-tasks.md).
- [Off-site backup → Getting alerts outside Marvin](../offsite-backup.md#getting-alerts-outside-marvin) — the platform's alerts.
