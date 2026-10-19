# Workspace email branding (2026-10-19)

Jared: "Lets take a look at the email branding chain" → "All three". Decision: the workspace's own settings
(not `metadata.brand`, which holds named site images only).

## Chain after this change

| Value | Workspace email (has a group_id) | Platform email (password reset, platform alerts) |
|---|---|---|
| Name | workspace setting → site title → workspace name | Admin → "Marvin" |
| Footer | workspace setting → "Sent by <name>" | Admin → "Sent by Marvin CMS" |
| Colour | workspace setting → Admin → #4f9c84 | Admin → #4f9c84 |

Layout file: `default.html` → `EMAIL_TEMPLATE` (branded.html) → data-dir `templates/<EMAIL_TEMPLATE>`. The per-workspace
data-dir file (`templates/<group_id>/…`) and `workspace.html` are retired. Content and sender chains are unchanged.

## Steps
- [x] `group_preferences.email_branding_json` (JSON, nullable) + migration, both engines
- [x] `services/email/branding.py`: shared clean/validate (from platform_policy), workspace view/save, `effective_branding(group_id)`
- [x] `EmailTemplate.render_html(template, brand)`; EmailService renders with its workspace's brand; automation email action too
- [x] API `GET/PUT /api/groups/email-branding` (workspace admin): stored values + effective
- [x] Workspace Settings → Email: a Branding card (mirrors Admin's), placeholders show the fallbacks
- [x] Template "Send test" goes through the workspace (sender, layout, brand, real workspace name)
- [x] Remove the per-workspace layout file lookup and `workspace.html`; fix docstrings that say default.html
- [x] Tests (layering, render, test-send, no per-workspace file), docs, SDK types regenerated

## Review
- Built 2026-10-19. `services/email/branding.py` layers the workspace's values over its site title/name and the
  platform's colour; `EmailService.render` is the one place an email gets its brand (send_email, DB templates, the
  workflow email action). Validation is shared with Admin's (`platform_policy.clean_email_branding`).
- The UI's template "Send test" (`/api/platform/email/templates/{id}/test`) already went through the workspace; the
  other test route (`/api/platform/workspaces/{gid}/email-templates/{id}/test`, SDK/CLI) didn't — fixed, with the
  workspace's real name.
- `metadata.brand` was the first idea and is wrong: it holds named site images (seal, portrait), not a name or colour.
- Tests: tests/test_workspace_email_branding.py (10). SDK types regenerated (`/api/groups/email-branding`).
