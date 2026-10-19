# Workflow: HTTP request step + template filters (2026-10-19)

Jared: "Do th 1 and 2" — items 1 and 2 of `tasks/n8n-review.md`. Goal: most of the remaining ranked items become
recipes instead of plugins.

## 1. `request` step ("Call a web API")
A separate kind from `fetch`, which is a public read that never fails a run. `request` sends workspace data out, so it
needs admin rights (WEBHOOK_MIN_ROLE), like `webhook`.
- `url`, `method` (GET default; POST, PUT, PATCH, DELETE, HEAD), `query` (dict, appended URL-encoded), `headers`
  (`{{SLUG}}` secrets resolved, as webhook headers are), `body` with `body_type` (json default for an object/list;
  form; text).
- Auth: `secret_ref` and `auth_scheme` as on webhook; `Basic` base64-encodes a "user:pass" secret.
- Sends through core's guarded client (services/integrations/http_client.py): public hosts only, every redirect
  re-checked, a size cap. MarvinHttpHelper gains a public `request()`.
- `retries` (0–3): a network blip, 429 or 5xx is retried with a growing pause; `timeout_seconds` (1–60, default 15).
- `fail_on_error` (default true): a non-2xx fails the step with the response's text; false gives it as output.
- `idempotency_key` and `idempotency_window_hours` reuse the webhook gate.
- Output: `status`, `ok`, `content_type`, `headers` (lower-cased), `json`, `text` (trimmed), `url`.
- Dry run: the request shown, not sent; credential headers masked (webhook's `_preview_headers`).
- Wiring: schema RequestAction + ACTION_MODELS + Action union, executor, editor labels (both copies), editor form
  (fields + output keys), authoring note + url check, docs.

## 2. Template filters
`${path|filter|filter:arg|filter:"a b",x}`: a chain, left to right; args comma-separated, quotes optional.
- Text: `default`, `upper`, `lower`, `capitalize`, `title`, `trim`, `truncate:N`, `replace:old,new`, `slug`,
  `strip_html`, `escape`, `markdown` (the email converter), `url`.
- Lists: `join[:sep]`, `split[:sep]`, `first`, `last`, `length`.
- Dates: `date[:format[,timezone]]` (ISO text, a date or epoch seconds; strftime; default %Y-%m-%d).
- Numbers: `round[:digits]`.
- Data: `json`, `base64`, `sha256`, `md5`.
- An unknown filter or a wrong argument count is refused when the workflow is saved (today it silently gives nothing);
  at run time an unknown filter still gives None.
- `filters.py` holds the parser, the filters and the save-time check; matcher._lookup applies the chain.

## Not in scope
- Moving the `webhook` step onto the guarded client: about 20 tests patch httpx.request. Tracked separately.

## Steps
- [x] filters.py + matcher wiring + save-time check + authoring syntax docs
- [x] MarvinHttpHelper.request; actions/request.py; schema; registry
- [x] editor labels + editor form; authoring note + checks
- [x] tests (filters, request: send/auth/retry/fail/dry-run/role/SSRF/idempotency); docs; SDK types if the spec changes

## Review
- Built 2026-10-19. `services/automation/filters.py` (24 filters, chain parser, save check); `actions/request.py` on
  `MarvinHttpHelper.request` (new). The editor has a guided form for the step. The authoring guide lists the filters
  and a request note. The manual has "Call a web API" and "Filters".
- The n8n review suggested Google Sheets via the generic step. That doesn't work: Google's OAuth tokens expire within the
  hour and `{{SLUG}}` doesn't resolve in a URL. Examples use Airtable (a long-lived personal access token). Sheets needs
  an integration.
- The OpenAPI spec is unchanged (workflow definitions are JSON), so there's no SDK change.
- Tests: tests/test_workflow_request_and_filters.py (48).
