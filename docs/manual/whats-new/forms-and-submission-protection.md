# Forms and submission protection

An entry type with `capabilities.submittable: true` is a form: a public POST to its submit URL becomes an `inbox` entry of that type, after rate limiting, a honeypot, CAPTCHA, schema validation and a spam policy you set once per platform and override per workspace.

## What it does

- A submittable entry type **is** the form; a submission **is** an entry (`status: "inbox"`, `created_by: null`). It uses the type's own field schema, so the site renders the form from the same schema the submission validates against.
- The submit path runs, in order: **rate limit** (per IP, per type, only when `rateLimitMax` is set; `429` when exceeded) → **honeypot** (a filled hidden field returns success without storing anything) → **CAPTCHA** (`captchaToken` in the body, verified with the provider; `400` on failure) → **validation** against the type's `fields` schema (`400 Validation failed: …`) → **submission protection** → entry creation.
- **Submission protection** classifies the submission by the first email-looking value (a field literally named `email` is preferred). Reasons: `domain_not_allowed:<d>`, `blocked_domain:<d>`, `disposable_domain:<d>`, `personal_domain:<d>`. Subdomains match (`mail.example.com` matches `example.com`). A submission with no email address gets no domain reasons.
- What a suspicious verdict means depends on `mode`: `review` (default) still accepts the entry but lands it as `needs_review` with `metadata_json.submission.review_reasons`; `reject` returns `400`; `off` skips the checks. IPs or CIDRs in `exempt_ips` skip every check.
- With `capture_client_info` on, `metadata_json.submission` also records `ip_address`, `user_agent`, `referer` and `received_at`.
- **Surge detection**: a per-form counter emits `submission_surge_detected` exactly once, on the submission that makes the count equal `surge_threshold` inside `surge_window_minutes`.
- The entry title comes from `titleTemplate` (Jinja over the submitted fields), else the first non-empty text value, else `<type name> submission <timestamp>`.
- When `notify` is on (default), the scoped `form_submission_received` event fires; `entry_created` still fires from the entry service but is not the notification event.

!!! note
    A legacy `Forms` table path still answers the same URLs when no submittable entry type matches the slug. It is transitional (see `tasks/forms-as-entry-types.md`, Phase 3).

## Where

| Surface | Path |
|---|---|
| Entry type editor, "Submission settings" fieldset (shown while **Submittable** is checked) | `/workspace/entry-types/{id}` |
| Platform defaults (admin sidebar **Submission Protection**) | `/admin/submission-protection` |
| Workspace override (**Settings → Publishing → Submission Protection**), with a per-field **Use platform default** checkbox | `/workspace/settings/submission-protection` |
| Submissions | Entries list, status `inbox` or `needs_review` |

## How to use

1. Open the entry type, tick **Submittable**, and fill the submission settings (success message, honeypot, CAPTCHA secret ref, rate limit, title template).
2. On the site, fetch the form definition and render it from `formSchema`. When `metadata.honeypotField` is non-null, include a hidden input with that name.
3. POST the field values as a JSON object to the submit URL with an API client token that has `write:public_entries`.
4. React to `form_submission_received` in a workflow (see [Workflows](workflows.md)); the payload carries `flagged`, `review_reasons`, `status`, `ip_address` and `user_agent`, so a step can skip flagged entries or forward the IP.

```bash
export MARVIN_SITE_TOKEN=...   # the API client token
curl -X POST "$MARVIN/api/publish/my-site/forms/newsletter/submit" \
  -H "Authorization: Bearer $MARVIN_SITE_TOKEN" -H "Content-Type: application/json" \
  -d '{"email": "ann@example.com", "_website": ""}'
```

## API

| Method and path | Auth | Notes |
|---|---|---|
| `GET /api/publish/{workspace_slug}/forms/{slug}` | API client, `read:published_entries` | Returns `slug`, `name`, `description`, `formSchema` (the entry type's schema) and `metadata.successMessage` / `metadata.honeypotField`. |
| `POST /api/publish/{workspace_slug}/forms/{slug}/submit` | API client, `write:public_entries` or `write:form_submissions` | Body is the submitted fields. Returns `success`, `message`, `submissionId` (the entry id), `redirectUrl`. |
| `GET` / `PUT /api/admin/submission-protection` | Platform admin | Read or replace the platform defaults (`SubmissionProtectionSettings`). |
| `GET /api/admin/submission-protection/presets` | Platform admin | `{"disposable": [...], "personal": [...]}` bundled domain lists. |
| `GET /api/groups/{group_id}/preferences/submission-protection` | Workspace member | `platformDefaults`, `workspaceOverride`, `effective`. |
| `PATCH /api/groups/{group_id}/preferences` | Workspace ADMIN/OWNER | Set `submissionProtectionJson`; a `null` field inherits the platform default. |

Event payload `form_submission_received` (`EventFormSubmissionData`): `form_id`, `form_name`, `submission_id`, `submission_data`, `workspace_id`, `workspace_name`, `status`, `flagged`, `review_reasons`, `ip_address`, `user_agent` (the last two only when client capture is on). `submission_surge_detected` carries `form_id`, `form_name`, `submission_count`, `threshold`, `window_minutes`. See [API reference](../api/index.md).

## Settings

`capabilities.submission` on the entry type (camelCase keys in `capabilities_json`):

| Key | Default | Purpose |
|---|---|---|
| `successMessage`, `redirectUrl` | none | Returned to the site after a submission. |
| `enableHoneypot`, `honeypotField` | `false`, `_website` | Hidden trap field; a filled value is dropped silently. |
| `enableCaptcha`, `captchaProvider`, `captchaSecretRef` | `false`, `hcaptcha`, none | Providers offered: `hcaptcha`, `turnstile`, `recaptcha`. The secret is a `{{SLUG}}` workspace-secret ref, never plaintext. |
| `rateLimitMax`, `rateLimitWindowSeconds` | off, `3600` | Per-IP limit for this type; the window is rounded down to whole minutes (minimum 1). |
| `notify` | `true` | Emit `form_submission_received`. |
| `titleTemplate` | none | Jinja title for the created entry, e.g. `Contact from {{ name }}`. |

Submission protection (platform defaults; every field overridable per workspace): `mode` (`review`), `blocked_domains`, `allowed_domains` (when non-empty, any other domain is flagged), `block_disposable_domains` (`true`), `block_personal_domains` (`false`), `capture_client_info` (`true`), `exempt_ips`, `surge_threshold` (off), `surge_window_minutes` (`10`). Domains are lower-cased and a leading `@` is stripped.

## Since

Forms-as-entry-types landed in v1.0.0-rc.42 (`c192c6c1`), rate limit and CAPTCHA in rc.45 (`0fdc23e2`), submission protection in rc.67 (`050277b4`), and the editor fieldset in rc.68 (`9dac064b`).

## Related

- [Workflows](workflows.md) — react to `form_submission_received` and `submission_surge_detected`.
- [Outgoing webhooks](outgoing-webhooks.md) — forward submissions to another system.
- [Glossary](../glossary.md)
