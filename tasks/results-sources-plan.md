# Automation results: Cloudflare Pages builds and Buttondown sends (2026-10-20)

Jared: "what about the others Like Buttondown and Cloudflare pages" → "do the plan, don't worry about the issue-type".
Builds on `tasks/automation-results-plan.md` (n8n first; live 2026-10-20).

## Core + integration SDK (phase 1)
- **Hand-offs core runs itself are recorded too.** Today only the workflow `integration` step records a `hands_off` action.
  The site rebuild runs the deploy target's integration action from the `webhook_triggered` event subscription (event
  connections), not a workflow step: record it there with the same hook (workflow none; target and remote id from the
  declaration; failure recorded with the redacted message).
- **SDK 0.14.0: `HandsOff.record_if`** — an output key that must be truthy for the hand-off to be recorded (empty = always).
  For an action that sometimes hands off and sometimes doesn't (Buttondown: draft vs send). Checked at registration
  against the output schema like the other keys.
- Tests, docs (`whats-new/automation-results.md`, `integrations.md` hands_off section, SDK README).

## Cloudflare Pages v0.3.0 (phase 2)
- `deploy` declares `HandsOff(remote_id="deployment_id", remote_url="url", statuses={...Cloudflare's words → Marvin's})`.
- The three notification workflows (started / succeeded / failed) each add an `automation_result` step (remote_id = the
  notification's deployment id; failure message = the build log tail, as the toast shows). They keep emitting the
  site_deployment_* events and toasts.
- Blueprint parameter `integration` stays only where the build-log step needs it; the result step infers the connection from
  the webhook.

## Buttondown v0.9.0 (phase 2)
- `create_issue_email` declares `HandsOff(remote_id="email_id", remote_url="url", record_if=<true only when it sent>)`.
  Draft and off are not hand-offs.
- Webhooks: add `email.sent` to the events `connect_webhooks` subscribes; a new workflow `buttondown-email-sent` settles
  the result (`automation_result`, remote_id = the payload's email id, status succeeded).
- **Must not change `buttondown-issue-on-publish`'s definition** (Mash & Burn edited it to send Bench Notes; Update would
  overwrite the edit). No send-failure event exists: a send that never completes shows as No reply.

## Release
Integration SDK v0.14.0 tag → Marvin pin; plugins tagged and pinned; TS SDK if the API changes; existing workspaces click
Update on each card once (the new/changed workflows).
