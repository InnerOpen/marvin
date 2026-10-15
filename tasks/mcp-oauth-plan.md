# Plan: remote MCP server with OAuth sign-in, hosted by Marvin (2026-10-14)

Jared: "update the code to the MCP server so that it has a authentication mechanism so we do not have to store the key. Kinda like the BrainMCP" → "plan the MCP sign-in". Drafted by a planning agent from the code (read-only); nothing built yet. Backlog: ~/brain/10-Tasks/TASKS.md → "remote MCP with OAuth sign-in".

Status: slice 1 built 2026-10-14 (see "Slice 1 as built"); slices 2–5 to do. Every claim below cites code I read. Items I could not verify are marked **(unverified)**.

---

## 0. Summary

The proposed shape holds up, with four changes:

1. **Use the `mcp` SDK for the MCP protocol, but write the OAuth server endpoints as FastAPI routes.** `mcp[cli]>=1.28.1` is already a dependency and 1.28.1 is installed. Its auth handlers would bring back two of BrainMCP's bugs (§1.6).
2. **The consent page goes on admin.iwobble.com, behind Cloudflare Access.** Marvin's session cookie only exists on the admin host. Putting a login form on api.iwobble.com would reopen the public login page that Access was put in place to close (§3).
3. **New OAuth tables, not new scope columns on `long_live_tokens`.** OAuth tokens need expiry, rotation, a client and a workspace binding, and none of that fits a personal token (§2.1).
4. **Pull the tool gating out of `operations_controller.invoke_tool` into a shared service before writing any MCP code.** The local npm server and the remote server then go through the same role, matrix, source and bulk-write gates. The scope check is added on top of those (§4).

---

## 1. Findings from the code

### 1.1 Auth stack
- `get_current_user` (`/home/jared/code/Marvin/src/marvin/core/dependencies/dependencies.py:150-217`):
  - reads the bearer token, or falls back to the cookie `settings.AUTH_COOKIE_NAME` (`marvin.access_token`);
  - any token starting with `SECURITY_TOKEN_PREFIX_USER` (`marvin_tk_`) goes to `repos.api_tokens.validate_token`, and that token **is the user**;
  - anything else is decoded as an HS256 JWT (`sub`, optional `long_token`).
  - A token with a new prefix (e.g. `marvin_at_`) fails the JWT decode and gets a 401 on the REST API. That is exactly what we want: OAuth tokens are only valid at `/mcp`.
- Prefixes and settings (`/home/jared/code/Marvin/src/marvin/core/settings/settings.py:479-494`): `marvin_tk_` (user), `marvin_sk_` (site client), `SECURITY_TOKEN_RANDOM_BYTES=32`, `SECURITY_BCRYPT_ROUNDS=12`. `TOKEN_TIME=48` h (line 330), which admins can override through `platform_policy.security("TOKEN_TIME")` (`core/security/security.py:159`).
- Personal tokens:
  - model `LongLiveToken` (`db/models/users/users.py:47-114`) has columns `token_hash` (bcrypt), `token_lookup` (SHA-256), `enabled`, `last_used_at`, `revoked_at`, `user_id`, `created_by`. There is **no workspace, scope or expiry column**.
  - repo: `repos/users/long_live_tokens.py`; lookup: `find_token` in `core/security/hasher.py:116-135` (SHA-256 lookup, then bcrypt verify).
  - routes: `routes/users/api_token_controller.py` (`/api/users/self/api-tokens`, create/rotate/revoke/delete). Each action emits `api_token_created|rotated|revoked` via `_announce`.
- Workspace scoping: `BaseUserController.group_id` is `user.active_group_id or user.group_id` (`routes/_base/base_controllers.py:170-181`).
  - So a personal token acts in whatever workspace the user last switched to.
  - That is also why the local MCP's `MARVIN_WORKSPACE_SLUG` does not actually scope `marvin_<tool>` calls (the brain note says to switch with `PUT /api/self/workspaces/current`).
  - A remote grant has to carry its own `group_id` and must never read or change `active_group_id`.
- Login: the backend `POST /api/auth/token` (`routes/auth/auth_controller.py:110-185`) throttles per account and per IP through `services/security/login_throttle.py` + `auth_throttles` (a generic `(scope, key, count, window_start, locked_until)` table, `db/models/platform/auth_throttles.py`).
  - The admin UI logs in through the Astro endpoint `frontend/src/pages/api/auth/login.ts`, which sets a **host-only cookie on the admin host** (SameSite=Lax, httpOnly).
  - All browser API calls go through the same-origin proxy `frontend/src/pages/api/[...path].ts`, which turns the cookie into `Authorization: Bearer`.
  - **Consequence: a page served from api.iwobble.com cannot see the user's session.**
- `FRONTEND_URL` / `BASE_URL` are `https://admin.iwobble.com` in prod (chart `config.publicUiUrl`, `marvin-chart/values-iwobble.yaml:43`, live since 2026-10-14).
- **The backend has no "public API URL" setting.** `config.publicApiUrl` only reaches the frontend, as `PUBLIC_MARVIN_API_URL` (`marvin-chart/templates/deployment-split.yaml:207-215`). OAuth needs a fixed issuer, so a backend setting is required (§2.4).
- CORS: production only allows `CORS_ORIGINS` (`app.py:236-268`); the iwobble value is `admin.iwobble.com` plus the `.apps` route.

### 1.2 Tool registry, invoke route, write gating
- Registry: `services/ai/tools/base.py`.
  - `ToolSpec` fields: `name`, `description`, `input_schema`, `min_role`, `sources`, `read_only`, `bulk_write`, `ask_first`.
  - `ToolContext` fields: `session`, `group_id`, `user`, `provider`, `source`, …
  - `caller_role(ctx)` maps legacy `admin` to OWNER and otherwise looks up the user's membership role.
- I enumerated the registry with `uv run`: **53 tools**.
  - All but `compose_entry` include the `mcp` source; `compose_entry` withholds it on purpose (`builtins_authoring.py:9-22`) so it does not collide with the TS hand-written `marvin_compose_entry`.
  - None of the input schemas contains `$schema`.
  - Every tool with `read_only=False` is either in a write category or is `run_agent` (category `agents_run`, which counts as "not a write", but the child run can write).
- `GET /api/ai/tools` and `POST /api/ai/tools/{name}/invoke` (`routes/ai/operations_controller.py:89-216`) gate in this order:
  1. `min_role` against `_user_role()` (line 3206);
  2. `_check_invocation_source(body.source, spec.sources)` (line 3217): the tool's declared sources ∩ the workspace's `WorkspaceAISettingsModel.invocation_sources`. The `mcp` key is already a per-workspace UI toggle labelled "External MCP hosts" (`services/ai/operations/base.py:44-54`);
  3. `unattended_refusal(router_agent, name, category, role)` (`services/ai/agents.py:601-623`): a direct call stands in for the workspace's router agent `marvin`. Block and Ask-first both refuse, and any write is refused below EDITOR (`resolve_policy`, lines 565-598);
  4. `bulk_writes.unattended(spec, ctx)` (`services/ai/tools/bulk_writes.py:200-204`): bulk writes and ask-first calls (archiving or trashing a published entry) refuse instead of parking.
  - `GET /tools` applies the same matrix filter, so blocked tools are never advertised.
- **There is no budget check on `/tools/{name}/invoke`.** `_check_budget` is only called on operation execute and agent runs. `compose_entry`, `revise_entry` and `search_content` use the provider through invoke without one. This is a pre-existing gap that a public endpoint makes bigger (Q13).
- AI operations (`marvin_op_*` in TS) go through `execute_operation` (`operations_controller.py:218-337`), about 120 lines of controller logic including `_write_back`. An operation with `writeback == {}` only proposes (`services/ai/operations/base.py:145-149`). Exposing these remotely needs an extraction first, so I defer them (Q9).

### 1.3 Event types and audit
- `EventTypes.api_token_created|rotated|revoked`, `api_rate_limit_exceeded`, `token_refreshed`, `login_failed_multiple_times` (`services/event_bus_service/event_types.py:101, 298-304, 408`). Payload model: `EventAPITokenData` (line 1089, "Never the token value or its hash").
- Catalog: `services/events/event_catalog.py:1393-1440`. `_PLATFORM_SCOPE` (lines 2176-2201) makes these platform-scope and `audit_locked`. New OAuth events go in the same set.

### 1.4 Platform settings and policy pattern
- `services/platform_policy.py`: rows in `platform_settings` (`PlatformSettingsService.get/set`), a 15 s cache, an admin value wins over the env var, `SecurityField` int ranges. Admin API: `routes/admin/platform_policy_controller.py` (`GET/PUT /security`). UI: `frontend/src/pages/admin/site-settings.astro`.
- The new policy key `remote_mcp` follows this pattern exactly.

### 1.5 Frontend pages
- `frontend/src/pages/user/api-tokens.astro` (251 lines, "Personal API Tokens", reveal-once modal) and `api-tokens/new.astro`.
- `frontend/src/pages/user/cli-and-mcp.astro` (140 lines). It renders `claude mcp add marvin --env MARVIN_USER_TOKEN=… -- npx -y @inneropen/marvin-mcp` and a Desktop JSON, using `getBrowserApiBaseUrl()` and the current workspace slug.
- Auth helpers: `requireAuth` in `frontend/src/lib/auth.ts`; `safeReturnPath` (`lib/session.ts:65`) accepts `/oauth/consent?req=…`.
- There are no CSRF tokens anywhere. The UI relies on SameSite=Lax plus the same-origin proxy.

### 1.6 The `mcp` Python SDK (1.28.1, `.venv/.../mcp`)
Useful as-is:
- `server/lowlevel` `Server` with `list_tools` / `call_tool(validate_input=…)` / prompts / resources.
- `StreamableHTTPSessionManager(stateless=…, json_response=…, security_settings=…, session_idle_timeout=…)`.
- `LATEST_PROTOCOL_VERSION = "2025-11-25"`.
- Unknown session ids get a 404 (`streamable_http_manager.py:336-341`), which per spec tells the client to re-initialize.
- The Starlette `Request` is passed into handler context as `request_context.request` (`streamable_http.py:268-274`, `lowlevel/server.py:747-771`). Per-request auth can therefore be read from `request.state`. A contextvar would not work, because handlers run in the session's task, not the request's.
- Pydantic models `OAuthMetadata` (including `client_id_metadata_document_supported`), `ProtectedResourceMetadata`, `OAuthClientMetadata`.

Not suitable for us:
- `server/auth/middleware/client_auth.py`: if the client registered as `client_secret_post` it reads only the form body; if `client_secret_basic`, only the header. It also requires `client_id` in the form. That is **BrainMCP's ChatGPT failure exactly** (DCR said post, ChatGPT sent Basic, result `invalid_client`). It also compares `client.client_secret` in plaintext, which forces plaintext storage.
- `handlers/register.py`: rejects any registration whose `grant_types` lack `refresh_token`, and hands back a plaintext secret for the provider to store.
- The provider interface is async while Marvin's DB layer is sync.
- **Decision:** our own FastAPI routes for the authorization server (about 400 lines), the SDK for MCP transport, sessions and JSON-RPC, and the SDK's pydantic models for metadata shapes.

Mounting gotchas:
- Starlette `Mount("/mcp")` answers `POST /mcp` with a 307 to `/mcp/`. Register a `Route("/mcp", endpoint=<ASGI app>, methods=["GET","POST","DELETE"])` instead, as FastMCP does.
- `session_manager.run()` must be entered inside `app.py` `lifespan_fn`, and it can only run **once per instance**. Tests that build several TestClients need a fresh manager per lifespan.
- Starlette 1.8.0's GZip middleware already skips `text/event-stream`, so the app-wide `GZipMiddleware` (`app.py:236`) will not buffer SSE.

### 1.7 What marvin-mcp (TypeScript, `~/code/MarvinMCP/src`) adds beyond forwarding
- `capabilities/tools/index.ts`: projects `GET /api/ai/tools` as `marvin_<name>`, but wraps every tool as `{args: record}` and pastes the real schema into the description. The remote server should expose the real `input_schema`.
- `capabilities/operations/index.ts`: hand-wired `marvin_compose_entry`, plus `marvin_op_<slug>` with slug-pattern exclusions (`/delete|destroy|remove|publish|admin/`).
- `capabilities/workflows/index.ts`: `marvin_wf_<slug>` for enabled workflows with `trigger.type === "mcp"` (the registry's `run_workflow` already covers this).
- Resources: `marvin://workspace`, `/site`, `entry-types`, `collections[/{slug}]`, `resources[/{slug}]`, `entries/{slug}`, `capabilities`.
- 7 prompts: `review_workspace_structure`, `create_site_page`, `prepare_release_update`, `audit_content_model`, `review_collections`, `review_assets`, `review_resources`. They are static text and are worth porting word for word.
- Publish-API read tools that use the site client token. The registry's `find_entries`, `list_*` and `get_*` replace them, so no site token is needed remotely.

### 1.8 Deployment facts that matter
- Prod: Postgres (CNPG), split mode, 1 backend replica, uvicorn `workers=1`, rolling update with maxSurge 1.
- **Every develop push goes to prod automatically** (Promote workflow). Two consequences:
  - in-memory MCP sessions die on every deploy;
  - the feature must be **off by default** behind a platform switch.
- The api host is deliberately not behind Access. admin and admin-dev are behind Access: email OTP, 30-day sessions, Jared's two addresses plus Grace.
- The zone has no WAF rules and Bot Fight Mode is off. BrainMCP on the same zone works with claude.ai and ChatGPT.
- Cloudflare returns `1010` to Python `urllib` (BrainMCP note). Test the public host with curl or a real MCP client.
- Dev DB is a copy of prod and **holds prod's `.secret`**, so a hashed prod token copied into dev would validate there. Audience binding (§6) is what stops it.

---

## 2. Architecture and data model

```
claude.ai / ChatGPT / Claude Code
   │ 1. POST /mcp → 401 WWW-Authenticate: Bearer resource_metadata="https://api.iwobble.com/.well-known/oauth-protected-resource/mcp"
   │ 2. GET PRM → GET /.well-known/oauth-authorization-server
   │ 3. POST /oauth/register (DCR)
   │ 4. browser → GET api.iwobble.com/oauth/authorize?…PKCE…&resource=…/mcp
   │        └─ creates pending request row → 302 https://admin.iwobble.com/oauth/consent?req=<id>
   │ 5. [Cloudflare Access OTP if needed] → [Marvin /login?return=… if needed] → consent page
   │        └─ form POST (same origin) → Astro → POST api /api/oauth/requests/<id>/approve (session JWT)
   │        └─ 303 → client redirect_uri?code=…&state=…&iss=…
   │ 6. POST /oauth/token (Basic or post) → access (1 h) + refresh (rotating)
   └ 7. /mcp (streamable HTTP, stateful) → tools from the registry, scoped to grant.workspace + grant.scope
```

### 2.1 Tables
New model file `src/marvin/db/models/platform/oauth.py`. Migration via `task py:migrate -- "remote mcp oauth"`, then hand-trimmed. Conventions: `sa.JSON` (never JSONB), `GUID()`, named unique constraints and indexes, explicit `String(N)` lengths (Postgres enforces them; there is a column-length test).

| Table | Columns | Notes |
|---|---|---|
| `oauth_clients` | `id` GUID PK; `client_id` String(64) unique; `client_secret_hash` String(64) null (SHA-256); `token_endpoint_auth_method` String(32); `redirect_uris` JSON; `grant_types` JSON; `client_name` String(200); `client_uri`, `logo_uri` String(500) null; `software_id`/`software_version` String(100) null; `registered_ip` String(64); `created_at`/`update_at`; `last_used_at` | Created by DCR. Unused for 7 days → purged. |
| `oauth_authorization_requests` | `id` GUID PK; `ref_lookup` String(64) unique (SHA-256 of the `req` value in the URL); `client_fk`; `redirect_uri` String(1000); `state` String(1000) null; `code_challenge` String(128); `requested_scope` String(200); `resource` String(500); `consent_nonce_hash` String(64); `status` String(16) (`pending\|approved\|denied\|expired`); `user_id` null; `group_id` null; `granted_scope` null; `code_lookup` String(64) null unique; `code_expires_at`, `code_used_at`; `expires_at` (30 min); `created_ip` | The pending request travels **by URL ref, never by cookie** (BrainMCP lesson). The code lives on the same row. Stored in the DB, so it survives a deploy mid-sign-in (another BrainMCP lesson). |
| `oauth_grants` ("connected apps") | `id` GUID PK; `user_id` FK users (cascade); `group_id` FK groups (cascade); `client_fk`; `scope` String(200); `resource` String(500); `client_name_snapshot`, `redirect_host` String(200); `created_at`; `last_used_at`; `last_ip` String(64); `last_user_agent` String(300); `revoked_at`; `revoked_reason` String(64) (`user\|admin\|reuse_detected\|membership_lost\|policy`) | One per approval. This is the row the UI lists and revokes. |
| `oauth_tokens` | `id` GUID PK; `grant_id` FK (cascade); `kind` String(8) (`access\|refresh`); `token_lookup` String(64) unique index; `expires_at`; `rotated_at` null (refresh only); `replaced_by` GUID null; `created_at` | Opaque tokens, SHA-256 only. |

**Why not reuse `long_live_tokens`:**
- personal tokens have no expiry, no client, no workspace, and their semantics are "token = user";
- `get_current_user` accepts them across the whole REST API;
- they are bcrypt-verified, which costs about a CPU-quarter-second per check at 12 rounds on a 1-CPU pod, and MCP checks a token on every request.

**Why SHA-256 is enough:** the tokens carry 256 bits of randomness, the same reasoning `token_lookup` already documents. Opaque tokens plus a DB lookup give instant revocation, and one indexed query per request is fine.

### 2.2 Token formats and lifetimes
| Thing | Format | Lifetime |
|---|---|---|
| client_id | `marvin_oc_<22 b64url>` (public) | until purged (unused for 7 d) |
| client secret | `marvin_cs_<43>` | no expiry (`client_secret_expires_at: 0`) |
| pending request ref | 32 bytes b64url | 30 min |
| authorization code | `marvin_ac_<43>` | 5 min, single use |
| access token | `marvin_at_<43>` | 60 min (policy `MCP_ACCESS_TOKEN_MINUTES`, 5–1440) |
| refresh token | `marvin_rt_<43>` | 30 days idle, rotated on every use (`MCP_REFRESH_TOKEN_DAYS`, 1–365); absolute grant cap 180 d (`MCP_GRANT_MAX_DAYS`) |

- None of these may start with `marvin_tk_` or `marvin_sk_`.
- The prefixes let secret scanners (gitleaks, GitHub custom patterns) catch leaks.
- Make them module constants, or settings beside `SECURITY_TOKEN_PREFIX_*` for consistency.

### 2.3 Endpoints (all on the API host)
Root level, outside `/api`, included like `health_router` (`app.py:390-394`). New package `src/marvin/routes/oauth/`:
- `GET /.well-known/oauth-protected-resource/mcp` and `GET /.well-known/oauth-protected-resource`
  - body: `{resource: "<PUBLIC>/mcp", authorization_servers: ["<PUBLIC>"], scopes_supported: ["marvin:read","marvin:write"], bearer_methods_supported: ["header"], resource_name: "Marvin"}`
- `GET /.well-known/oauth-authorization-server`
  - `issuer`, `authorization_endpoint`, `token_endpoint`, `registration_endpoint`, `revocation_endpoint`
  - `response_types_supported: ["code"]`, `grant_types_supported: ["authorization_code","refresh_token"]`
  - `code_challenge_methods_supported: ["S256"]`, `token_endpoint_auth_methods_supported: ["client_secret_basic","client_secret_post","none"]`
  - `authorization_response_iss_parameter_supported: true`, `scopes_supported`
  - leave `client_id_metadata_document_supported` out until CIMD exists
- `POST /oauth/register` (RFC 7591)
- `GET /oauth/authorize`
- `POST /oauth/token` (authorization_code, refresh_token)
- `POST /oauth/revoke` (RFC 7009)
- `GET|POST|DELETE /mcp`

Under `/api`, authenticated by a **session JWT** (PATs refused):
- `GET /api/oauth/requests/{ref}`: what the consent page shows.
- `POST /api/oauth/requests/{ref}/approve` with `{workspace_id, access: "read"|"write", consent_nonce}`, returns `{redirect_to}`.
- `POST /api/oauth/requests/{ref}/deny`, returns `{redirect_to}` carrying `error=access_denied`.
- `GET /api/users/self/connected-apps`, `POST /api/users/self/connected-apps/{grant_id}/revoke`.
- `GET /api/admin/connected-apps` and `POST …/{id}/revoke` (super admin).
- `GET/PUT /api/admin/platform/remote-mcp` (policy), placed next to `platform_policy_controller.py`.
- `GET /api/app/about` gains `remoteMcpUrl` when the switch is on, so the UI can print it.

### 2.4 Settings and policy
- New backend setting `PUBLIC_API_URL` (e.g. `https://api.iwobble.com`); issuer = it, resource = `+ "/mcp"`.
  - Chart: pass `config.publicApiUrl` to the backend too (`marvin-chart/templates/deployment-split.yaml`, `deployment.yaml`).
  - If unset and `PRODUCTION`, refuse to enable remote MCP. In dev, derive it from the request and log a warning.
- Platform policy key `remote_mcp` (new section in `services/platform_policy.py`):
  - `enabled` (bool, env `MCP_REMOTE_ENABLED=false`);
  - the three lifetimes above;
  - `extra_redirect_uris` (list of exact https URIs or `https://host/path*` prefixes);
  - `allow_dynamic_registration` (bool, default true).
- When the switch is off, `/mcp`, `/oauth/*` and `/.well-known/oauth-*` return 404, and existing grants stop working but are kept.

### 2.5 Code layout
- `src/marvin/services/ai/tool_gateway.py`: the extracted gating (§4). Used by `operations_controller.list_tools/invoke_tool` **and** the remote MCP.
- `src/marvin/services/mcp_remote/`:
  - `oauth.py`: clients, requests, codes, tokens, grants, rotation, reuse detection;
  - `redirects.py`: allowlist and loopback rules;
  - `policy.py`: settings, wrapping `platform_policy`;
  - `projection.py`: ToolSpec → `mcp.types.Tool`, schema sanitising, scope filter, annotations;
  - `connector_tools.py`: `search` / `fetch`;
  - `prompts.py` / `resources.py`: ported from TS;
  - `server.py`: lowlevel `Server` with handlers that run sync tool code through `anyio.to_thread.run_sync` with their own `session_context()`. **This matters:** the async handlers would otherwise block the single uvicorn worker;
  - `asgi.py`: auth wrapper, session↔grant binding, request logging, rate limit.
- `src/marvin/services/scheduler/tasks/purge_oauth_records.py`: expired requests, codes, tokens; unused clients; grants dead for 90 d.

---

## 3. Consent UX and where it lives

**Recommendation: `frontend/src/pages/oauth/consent.astro` on admin.iwobble.com, behind Cloudflare Access.**

Flow:
- `GET /oauth/authorize` on the api host checks client_id, redirect_uri, response_type, PKCE and resource, writes the pending row, and redirects with 302 to `{FRONTEND_URL}/oauth/consent?req=<ref>`.
- The page calls `requireAuth(Astro.cookies, Astro.redirect, Astro.url.pathname + Astro.url.search)`, so an unsigned-in user goes to `/login?return=/oauth/consent?req=…` and comes back.
- It fetches `GET /api/oauth/requests/{ref}` server-side with the cookie's bearer.

The page shows:
- "**{client_name}** (as it calls itself) wants to use Marvin as **{user}**. After you approve, you go back to **{redirect_host}**." The redirect host is the verified fact and gets the most prominent placement.
- **Workspace**: a select of the user's memberships only. Options are disabled, with the reason, where the workspace turned off AI from "External MCP hosts".
- **Access**: radio, **Read-only (default)** or **Read & write**. Read & write is disabled when the role is below EDITOR, or when the client asked only for `marvin:read`.
  - One-line explanation: "Writes make drafts and links; trashing or archiving published entries is always refused here."
- Approve / Deny buttons. Approve disables itself on submit (BrainMCP's double-submit lesson). "Signed in as X · not you? Sign out".

Submission:
- An ordinary HTML form POST to the same Astro page. The handler calls approve/deny with the bearer and the hidden `consent_nonce`, then answers 303 to `redirect_to`. No JS is needed.
- A second approve returns "Already approved, you can close this window", not an error.
- The response sends `Content-Security-Policy: frame-ancestors 'none'` and `X-Frame-Options: DENY` against clickjacking. No page sets these today.

The Cloudflare Access trade-off:

| | Consent on admin (behind Access): **recommended** | Backend-rendered page on api.iwobble.com |
|---|---|---|
| Session | Reuses the real Marvin session (password and OIDC alike) | api host never sees the cookie, so it needs its **own login form** |
| Exposure | Access plus Marvin login, two gates | A public password form on the api host undoes the Access decision of 2026-10-10 and needs its own throttle and CSRF |
| Friction | First time in a fresh browser or webview: email OTP, then Marvin login. ChatGPT desktop's webview has no cookies, so expect an OTP on each reconnect (rare thanks to refresh tokens) | One login |
| Who can connect | Only Access-allowlisted people (Jared ×2, Grace). That is a feature here | Anyone with a Marvin account |
| Self-hosters without Access | Works the same | Works the same |
| Code | Astro page + 3 small API routes | HTML templates, CSRF, a second login path |

- Only the browser touches admin.iwobble.com. Every server-to-server call (discovery, register, token, `/mcp`) stays on the api host, which must stay outside Access.
- If the api host is ever put behind Access, it needs bypasses for `/mcp`, `/oauth/*` and `/.well-known/*`.
- **CSRF:**
  - the form posts same-origin, and the cookie is SameSite=Lax, so it is never sent on a cross-site POST;
  - approve also requires the per-request `consent_nonce` (hash stored on the row);
  - the request must still be `pending` and unexpired;
  - approve accepts only a session JWT, never a `marvin_tk_` PAT, so a script holding a PAT cannot mint grants silently.
- Optional hardening (Q16): have the Astro handler forward `Cf-Access-Jwt-Assertion`, and have the backend verify it against the team domain and AUD when configured.

---

## 4. Tool projection and scope enforcement

### 4.1 Extract the gateway first (no behaviour change)
`services/ai/tool_gateway.py`:
- `visible_tools(session, group_id, user, *, source="mcp", allow_writes=True, extra=()) -> list[ToolSpec]`: today's `list_tools` filter (`mcp` in sources, `role >= min_role`, `resolve_policy != BLOCK` against the router agent), plus the scope filter.
- `invoke_unattended(session, group_id, user, name, args, *, source="mcp", allow_writes=True) -> dict`: today's `invoke_tool` body.
  - min_role → `check_invocation_source` (moved out of the controller) → `unattended_refusal` → scope check → `bulk_writes.unattended` → JSON decode → rollback on error.
- Use `caller_role(ToolContext)` (str-compare) rather than the controller's UUID-equality `_user_role`. Working notes record a real bug from str/UUID `group_id` comparisons, so pass a `UUID` `group_id`.
- `operations_controller.list_tools/invoke_tool` become thin wrappers. Existing `tests/test_invoke_follows_matrix.py`, `test_builtin_agent_matrix.py` and `test_content_role_gates.py` must stay green.

### 4.2 Scope rules (enforced twice, each enough on its own; BrainMCP pattern)
- `marvin:read`: a tool is visible and callable only if `spec.read_only is True` **and** `not category_writes(category_of(spec.name, read_only=spec.read_only))`.
  - That excludes `run_agent` (`read_only=False`; a child run would inherit the user's role, not the scope).
  - Enforced in `tools/list` **and** again in `tools/call`. A call outside scope returns a tool error: "This connection is read-only".
- `marvin:write` (implies read): everything `visible_tools` returns, still under the router's permission matrix, the bulk-write gates and ask-first refusals.
  - Nothing a remote client sends can park for approval, so trash and archive of published entries are always refused. That matches today's local MCP.
- Re-evaluated **on every request**:
  - user still exists;
  - still a member of `grant.group_id`, or platform admin. If not, the grant is revoked with reason `membership_lost`;
  - current role, so a demotion takes effect immediately;
  - workspace `invocation_sources["mcp"]` still on;
  - platform switch on;
  - token resource equals this server's resource.
- Consent cannot grant write when the role is below EDITOR. All write tools need EDITOR today (`resolve_policy:596`).
- Optional third layer, if measurement shows read tools write nothing incidental: run read-scope calls in a `SET TRANSACTION READ ONLY` Postgres transaction. **(unverified:** `search_content` or `view_image` may write usage or log rows; measure first.)

### 4.3 Projection details
- Names: plain registry names (`find_entries`, `get_entry`, …); clients namespace by connector anyway (Q3). Plus `search` and `fetch`.
- `inputSchema` = the real `spec.input_schema`:
  - sanitise recursively by stripping every `$schema`;
  - force `{"type":"object","properties":{}}` when the schema is empty;
  - **never send `outputSchema`** (BrainMCP: ChatGPT silently drops tools whose schema is not 2020-12);
  - call with `validate_input=False`, matching how `/invoke` passes args to lenient handlers today. Tighten later.
- Annotations:
  - `readOnlyHint = spec.read_only` (claude.ai groups and approval-gates tools on this);
  - `destructiveHint` for categories `entries_trash`, `entries_archive`;
  - `openWorldHint` for `import_asset`, `run_workflow`;
  - `title` = humanised name.
- Extra tools:
  - `compose_entry` (write scope): its ToolSpec already exists but withholds `mcp`, so the remote projection adds it explicitly (`extra=("compose_entry",)`).
  - `get_workspace` (read): `workspace_overview` plus site settings.
- Results:
  - `content=[TextContent(json)]`;
  - `isError=true` when the handler returns `{"error": …}`.
  - Keep `reviewLink` and URLs untouched (tool descriptions already tell models to pass them on verbatim).
- `initialize.instructions`: workspace name, access level, "use `search_content` / `find_entries` first", "give `reviewLink` verbatim", "write tools create drafts".
- Prompts:
  - port the 7 TS prompts word for word into `prompts.py`. `prompts/list` must answer: BrainMCP found that `-32601` broke availability probes;
  - drop `review_*` prompts that reference write behaviour from read sessions.
- Resources: `marvin://workspace`, `marvin://entries/{slug}`, `marvin://collections/{slug}`, `marvin://resources/{slug}`, all backed by the same registry handlers. `resources/templates/list` must answer as well.
- ChatGPT connector tools (`connector_tools.py`):
  - `search(query)` → `{results:[{id,title,url,text}]}`, using `search_content` (semantic) and falling back to `find_entries` text search when there is no provider. Ids look like `entry:<uuid>`, `asset:<uuid>`, `resource:<uuid>`.
  - `fetch(id)` → `{id,title,text,url,metadata}` through `get_entry` / `get_asset` / `get_resource`. `url` = `services/entry_urls.best_entry_url` (public site) or else `ui_links.entry_edit_url`.
  - Both read-only and always present.
- Keep `@inneropen/marvin-mcp` as is for local/offline use. Add a README pointer: "prefer the remote server; no token to store".

### 4.4 Transport and sessions (`asgi.py`)
- Stateful `StreamableHTTPSessionManager(stateless=False, json_response=False, session_idle_timeout=3600)`.
  - SSE responses send headers right away, which keeps long tool calls (compose, about 30–90 s) clear of Cloudflare's 100 s 524 limit **(unverified;** test with `compose_entry`).
  - `security_settings` = DNS-rebinding protection on, with `allowed_hosts` = public API host, the dev host, the LAN `.apps` route and localhost. **Check in dev that cloudflared keeps the `Host` header (unverified).**
- The wrapper, per request:
  - (a) logs one line: method, path, status, UA, hasAuth, client_id, grant_id. Never tokens;
  - (b) resolves the bearer to a grant, or answers 401 with `WWW-Authenticate: Bearer resource_metadata="<absolute PRM URL>"`, and `error="invalid_token"` when a token was presented;
  - (c) captures `mcp-session-id` from the initialize response and stores session→grant in memory;
  - (d) if a bearer is present but its grant differs from the session's grant, answers 403;
  - (e) **GET/DELETE without Authorization are accepted when the session id is live and its grant still valid** (the codex-mcp-client lesson). POST without a bearer is always 401;
  - (f) puts `{grant, user_id, group_id, scope}` on `scope["state"]`, which handlers read through `request_context.request.state`.
- Sessions are lost on every deploy. The SDK answers 404 and clients should re-initialize (MCP spec). Claude does this. **ChatGPT behaviour after a 404 is unverified**, and slice 3 includes an explicit "deploy while connected" check. If ChatGPT fails it, fall back to `stateless=True` plus a GET that answers an SSE keep-alive. That needs testing too, because BrainMCP saw ChatGPT treat a 405 on GET as a dead connection.
- More than one backend replica would need sticky sessions or stateless mode. Today there is 1.

---

## 5. Client compatibility matrix

| Client | How the user adds it | What the server must do | Notes |
|---|---|---|---|
| **claude.ai and Claude Desktop custom connector** (same account setting; Anthropic's servers make the calls) | claude.ai → Customize → Connectors → Add custom connector → URL `https://api.iwobble.com/mcp`, Auth "Sign in now", OAuth client "Register automatically (DCR)" | 401 + PRM discovery; AS metadata; DCR; PKCE S256; `resource` param; redirect `https://claude.ai/api/mcp/auth_callback` (also allow `https://claude.com/api/mcp/auth_callback`); refresh; streamable HTTP; `readOnlyHint` | Connector URLs can't be edited: remove and re-add. CIMD is Claude's recommended default; until we add it, pick DCR (BrainMCP note). |
| **Claude Code** | `claude mcp add --transport http --scope user marvin https://api.iwobble.com/mcp`, then `/mcp` → Authenticate | DCR with `token_endpoint_auth_method: none` (public client) + PKCE; **loopback redirect** `http://localhost:<port>/callback` (RFC 8252: any port, exact path); refresh | Do not also add claude.ai's connector **and** a local entry, or tools show up twice (BrainMCP lesson). |
| **ChatGPT** (web connectors / developer mode; desktop app, whose MCP layer is `codex-mcp-client`) | Settings → Connectors / Apps → add MCP URL `https://api.iwobble.com/mcp` (developer mode for full tools) | DCR; **`client_secret_basic`** at /token (header wins over body, client_id taken from the header); redirect `https://chatgpt.com/connector_platform_oauth_redirect`; authorize opened in a **webview without the cookie** from its own fetch (so the req ref goes in the URL); **stateful sessions + GET SSE**; **GET/DELETE without Authorization**; no `$schema` / `outputSchema`; `prompts/list` and `resources/templates/list` answer; **only `search` and `fetch` are used outside developer mode** | The exact ChatGPT redirect URIs in 2026 are **unverified**; make the allowlist admin-editable and log rejected redirect URIs. The webview will hit Access OTP plus Marvin login. |
| MCP Inspector (browser, dev aid) | URL | CORS on metadata, register, token and `/mcp` | Optional; dev only. |
| Codex CLI | `codex mcp login` | Same as ChatGPT | Not a target. BrainMCP found it a poor test client. |
| Local `@inneropen/marvin-mcp` | unchanged | — | Gains the shared gateway for free (same gates). |

---

## 6. Security review items and tests

### 6.1 Review checklist
1. **Redirect URI allowlist**, checked at DCR **and** at authorize (exact match against the registered list).
   - Built-ins: the claude.ai and claude.com callbacks, ChatGPT's callback, loopback `http://127.0.0.1|localhost|[::1]:*/*`.
   - Plus `extra_redirect_uris` from policy.
   - Errors before the redirect URI is validated show an error page and **never redirect**.
2. **PKCE S256 required**; `plain` and missing are rejected (OAuth 2.1).
3. **Resource / audience (RFC 8707):** `resource` must equal `PUBLIC_API_URL/mcp` (or be absent, then defaulted). It is stored on the grant and checked on every `/mcp` request. This also blocks prod tokens on api-dev, whose DB copy holds prod's secret and hashes.
4. **Client auth:**
   - accept Basic and post for any confidential client;
   - `none` only for clients that registered `none`;
   - constant-time compare of SHA-256 hashes;
   - `invalid_client` gets a 401 with `WWW-Authenticate: Basic`, and **every rejection is logged at warn** (BrainMCP: silent 401s cost hours).
5. **Codes:** 5 min, single use, bound to client, redirect_uri and code_challenge. Reuse → `invalid_grant` **and** revoke every token issued from that code (RFC 6749 §4.1.2).
6. **Refresh rotation and reuse detection:**
   - a rotated refresh token presented again after a 30 s grace → revoke the grant and emit `mcp_token_reuse_detected`;
   - inside the grace → `invalid_grant` without revoking (absorbs client retry races);
   - scope may narrow on refresh, never widen.
7. **Consent CSRF and clickjacking:** see §3.
8. **Approve needs a session JWT, not a PAT.**
9. **Consent phishing:**
   - DCR `client_name` is shown as unverified; the redirect host is shown as fact;
   - DCR rate-limited to 10/h/IP;
   - when CIMD lands, it gives a verified client identity.
10. **Rate limits:**
    - DCR 10/h/IP (`auth_throttles` scope `oauth:register`, fits `String(32)`);
    - authorize 30/h/IP;
    - token failures 20 per 10 min per IP and per client_id → 429 + `Retry-After`;
    - `/mcp` tool calls 60/min per grant (in-memory sliding window; single process), answered with a JSON-RPC error, plus one `api_rate_limit_exceeded` event per window. That event exists but nothing sends it today.
11. **AI budget:** the gateway should apply `_check_budget`-equivalent logic to provider-using tools (Q13).
12. **Audit events** (platform scope, `audit_locked`, catalog category Security, in `_PLATFORM_SCOPE`), payloads never containing token values or hashes:
    - `mcp_connection_authorized`
    - `mcp_connection_revoked` (by user, admin or system)
    - `mcp_token_reuse_detected`
    - optional hidden `oauth_client_registered`
    - Entity changes made by tools already emit their own events with `user_id`. Consider adding `via: "mcp:<client_name>"` metadata **(unverified** whether the event bus has a slot for it).
13. **Platform switch** off by default; **per-workspace** gate through the existing `invocation_sources.mcp`.
14. **No secrets in logs.** Banner and startup lines print only counts (BrainMCP lesson).
15. **Logging** for every `/mcp`, `/oauth/*` and `/.well-known/*` request, and for unmatched paths under those prefixes. The prod request-logging middleware only runs in dev today (`app.py:271-294`).
16. **Cloudflare:**
    - the api host must stay outside Access;
    - if Bot Fight Mode or WAF rules are ever enabled, exempt `/mcp`, `/oauth/*` and `/.well-known/*` (Anthropic and OpenAI servers make those calls);
    - "Always Use HTTPS" was off on the zone as of 2026-09-21; the metadata must say https regardless.
17. **Dev DB refresh:** add OAuth grants to `sqlite_to_postgres --pause-outbound` (revoke copied grants), belt and braces on top of the audience check.
18. **Threading:** sync handlers off the event loop; one DB session per call; roll back on error.

### 6.2 Unit and integration tests (pytest, Postgres; `tests/test_remote_mcp_*.py`)
- `test_remote_mcp_metadata.py`:
  - PRM and AS metadata shapes;
  - issuer = `PUBLIC_API_URL`;
  - S256 only, both auth methods present;
  - 404 when the switch is off.
- `test_remote_mcp_dcr.py`:
  - allowlisted, loopback-any-port and policy-extra URIs accepted; others rejected;
  - `grant_types` missing `refresh_token` tolerated;
  - rate limit;
  - secret only returned once and stored hashed.
- `test_remote_mcp_authorize.py`:
  - unknown client or unregistered redirect → error page, no Location;
  - missing or plain PKCE → redirect with `invalid_request`;
  - bad resource → `invalid_target`;
  - creates a pending row and 302s to `FRONTEND_URL/oauth/consent?req=`;
  - **no Set-Cookie**.
- `test_remote_mcp_consent.py`:
  - PAT → 403;
  - non-member workspace → 403;
  - write with role below EDITOR → 403;
  - workspace with `mcp` off → 403;
  - wrong nonce → 403;
  - expired → 410;
  - deny → `access_denied` + state;
  - double approve → idempotent;
  - authorize and consent from **two independent clients / cookie jars** (BrainMCP reproduction).
- `test_remote_mcp_token.py`:
  - PKCE verifier mismatch;
  - code reuse revokes;
  - redirect mismatch;
  - Basic, post, Basic with client_id only in the header, `none`;
  - wrong secret → 401 `invalid_client`;
  - refresh rotation; reuse after grace revokes the grant and emits the event; reuse inside grace does not;
  - scope narrowing;
  - expired refresh;
  - RFC 7009 revoke.
- `test_remote_mcp_transport.py` (Starlette TestClient + SDK client over ASGI):
  - no token → 401 with an absolute `resource_metadata`;
  - expired, revoked, wrong-audience tokens, PATs and JWTs → 401;
  - session bound to grant (another grant's token → 403);
  - GET/DELETE without auth on a live session OK; bogus session → 404/401;
  - switch off → 404.
- `test_remote_mcp_scope.py`:
  - **pinned against the whole registry**: for a read grant, `tools/list` ∩ {spec with `read_only=False`} = ∅, and calling each such tool returns an error;
  - `run_agent` absent for read grants;
  - a write grant follows `unattended_refusal` (trash a published entry → refused);
  - demoting the user to VIEWER mid-grant → writes refused;
  - removing membership → 401 and grant revoked;
  - **mutation-check this suite** (deliberately break the filter and see tests fail), as BrainMCP did.
- `test_remote_mcp_schemas.py`: no `$schema` anywhere and no `outputSchema` in `tools/list`; every `inputSchema.type == "object"`; tool names unique; `search` and `fetch` present.
- `test_remote_mcp_connector_tools.py`: the `search` / `fetch` contract shapes.
- `test_remote_mcp_events.py`: events dispatched, platform scope, audit-locked, no token material in the payload.
- Gateway refactor: the existing matrix and role tests unchanged, plus a parity test that `GET /api/ai/tools` before and after extraction returns the same list for each role.
- Migration and column-length tests, following the existing pattern.

### 6.3 End-to-end script (like BrainMCP's)
`scripts/e2e/remote_mcp_oauth.py`, httpx, with env `MARVIN_E2E_API`, `MARVIN_E2E_USER`, `MARVIN_E2E_PASSWORD`, `MARVIN_E2E_WORKSPACE`:
1. `POST /mcp` → 401, parse `resource_metadata`.
2. PRM → AS metadata.
3. DCR with redirect `http://127.0.0.1:53682/cb`.
4. `GET /oauth/authorize` (no redirects followed) → `req` taken from the Location.
5. `POST /api/auth/token` → JWT (stands in for the browser login; Access does not cover the api host).
6. `GET /api/oauth/requests/{req}` with the JWT → nonce → approve with `access=read` → read the code from `redirect_to`.
7. `/oauth/token` using **Basic** auth.
8. `initialize` → `tools/list` (count; assert no `$schema` / `outputSchema`) → `find_entries` → a write tool refused.
9. Refresh → old refresh rejected → revoke → `/mcp` 401.
10. Repeat with `access=write` → `compose_entry` creates an inbox draft → trash it from the UI afterwards.
11. Run the whole flow a second time with a fresh client, to check the cookie-less path.

Also run the official SDK client (`mcp.client.streamable_http` + `OAuthClientProvider` with a scripted redirect handler) as a conformance check.

Against the public host: if Cloudflare answers `1010` to the Python client, use the curl variant or the LAN route `marvin-api-marvin-dev.apps.ocp4.iwobble.com`. Note that the issuer and resource stay the public host, so the audience check must use `PUBLIC_API_URL`, not the request host.

---

## 7. Slices
Each slice ships with a push to develop. Promote takes it to marvin-dev, then prod. Keep the switch **off in prod** until slice 3 has been verified on dev.

**Slice 1: gateway extraction + data model + policy switch (dark).**
- `services/ai/tool_gateway.py`, controller wrappers (with the parity test).
- Migration for the 4 tables, `PUBLIC_API_URL` setting + chart wiring.
- `remote_mcp` policy + admin card in `admin/site-settings.astro`.
- Metadata endpoints (404 when off), purge task.
- Verify on dev: the existing suite is green; `/api/ai/tools` is unchanged for the local MCP (run marvin-mcp against api-dev); with the switch on in dev, `curl https://api-dev.iwobble.com/.well-known/oauth-authorization-server` shows issuer `https://api-dev.iwobble.com`; prod unchanged (404).

**Slice 2: authorization server + consent + connected apps.**
- DCR, authorize, consent API, `oauth/consent.astro`, token, revoke, events.
- "Connected apps" section on `user/api-tokens.astro` with Revoke; super-admin list.
- `/mcp` exists but only checks the token: 401 with `WWW-Authenticate`, or `initialize` with zero tools.
- Verify on dev: the e2e script up to token + refresh + revoke; a real browser pass through admin-dev (Access OTP → login → consent → redirect to the loopback catcher); revoke from the UI kills the refresh token.

**Slice 3: read-only MCP.**
- `StreamableHTTPSessionManager` in the lifespan, `asgi.py` (sessions, GET/DELETE rule, logging, rate limit), read-scope projection, sanitised schemas, annotations, prompts, resources, `instructions`.
- Consent offers **read-only only**.
- Verify on dev: e2e read flow; Claude Code `claude mcp add --transport http marvin-dev https://api-dev.iwobble.com/mcp` → authenticate → `find_entries`; a claude.ai custom connector on api-dev lists the read tools and runs one; **deploy while connected** (push a trivial commit) and confirm the client recovers.
- Then turn on in prod, connect claude.ai to `https://api.iwobble.com/mcp`, and update `user/cli-and-mcp.astro` with a "Connect without a token" section (URL, `claude mcp add --transport http`, connector steps).

**Slice 4: read & write.**
- Write scope at consent (EDITOR+), `compose_entry` extra, matrix enforcement through the gateway, budget check, token reuse detection on, `mcp_token_reuse_detected`, per-grant rate limit + `api_rate_limit_exceeded`.
- Verify on dev: a write grant composes a draft (it shows in the inbox with review link); a read grant is refused; trashing a published entry is refused with the matrix message; demoting the user mid-session refuses writes. Then prod.

**Slice 5: ChatGPT + docs + polish.**
- `search` / `fetch`, ChatGPT verification in developer mode **and** normal mode (search/fetch only), ChatGPT redirect URIs confirmed from logs.
- Docs: rewrite `docs/manual/auth-and-tokens.md` "MCP and OAuth" (it currently says "Marvin has no OAuth authorization server") and `docs/manual/whats-new/marvin-as-mcp-server.md`; marvin-mcp README pointer.
- Optional follow-ups: CIMD (`client_id_metadata_document_supported`, fetch with an SSRF guard), per-workspace resource URLs `/mcp/w/<slug>`, AI operations projection after extracting `execute_operation`, the Access JWT check.

---

## Slice 1 as built (2026-10-14)

Built as planned, with these differences, so later slices start from the code rather than the text above:

- The gateway is `services/ai/tool_gateway.py`: `visible_tools`, `invoke_unattended`, `check_invocation_source`
  (the controller's `_check_invocation_source` now delegates to it) and `is_read_tool` (the read scope). The role is
  `tools.base.user_role(user, group_id)`, which `caller_role` now wraps. There is no `extra` argument yet; slice 4 adds it
  with `compose_entry`. Gates 1, 2 and 5 raise HTTPException; slice 3 maps those to MCP tool errors.
- The budget check (decision 13) reads a new `ToolSpec.uses_ai` flag, set on `search_content`, `compose_entry`,
  `revise_entry`, `view_image` and `run_agent`; `tests/test_tool_gateway.py` fails if a handler reaches `ctx.provider`
  without it. Over budget the invoke route answers 429 with the limit's message, like the other AI routes.
- Parity was checked twice: a one-off dump of 573 calls (every tool, seven caller kinds, several sources, MCP turned
  off, a failing handler, over budget) from a HEAD worktree and a patched worktree, identical except the four
  over-budget AI tools; and `tests/test_tool_gateway.py`, which keeps the old controller logic as a frozen oracle.
- `oauth_authorization_requests` gained `grant_id` (FK to the grant, SET NULL), so a reused code can revoke what it
  issued (§6.1 item 5) without another migration.
- The admin API is `GET/PUT /api/admin/platform-policy/remote-mcp`, beside the existing `/security` route, not
  `/api/admin/platform/remote-mcp`. Env defaults: `MCP_REMOTE_ENABLED`, `MCP_ACCESS_TOKEN_MINUTES`,
  `MCP_REFRESH_TOKEN_DAYS`, `MCP_GRANT_MAX_DAYS`. `remote_mcp()` returns the policy in force.
- The purge is the system task `purge_oauth_records` in `services/scheduled_tasks/handlers/oauth.py` (the existing
  handler layout), daily, listed in `database_report.TABLES`.
- Dev has the switch on through `MCP_REMOTE_ENABLED=true` in `values-dev.yaml`; prod has nothing set, so it is off.
- Not done in slice 1, as planned: §6.1 item 17 (revoking copied grants on a dev refresh) belongs with slice 2, once
  grants exist.

## Slice 2 as built (2026-10-14)

- `services/mcp_remote/oauth.py` (clients, pending requests, consent, codes, tokens, grants), `redirects.py` (Claude's
  and ChatGPT's callbacks, loopback any port, policy extras), `limits.py` (in-memory rate limits — one backend process —
  and the three audit events). Routes: `routes/oauth/authorization.py` (register, authorize, token, revoke, /mcp token
  check) and `routes/oauth/api.py` (consent API, connected apps self + admin), the consent page
  `frontend/src/pages/oauth/consent.astro`, Connected apps on `user/api-tokens.astro`, `admin/connected-apps.astro`.
- The consent nonce is regenerated each time the page loads (only its hash is kept), so approve needs the page the
  same session just loaded. Approve/deny/GET refuse personal tokens and long-lived JWTs (403).
- Reuse detection (planned for slice 4) is already on: a rotated refresh token used again after 30 s revokes the grant
  and sends `mcp_token_reuse_detected`; a code used twice revokes its grant.
- Rate limits are in memory (register 10/h, authorize 30/h, token failures 20/10 min, per IP) instead of
  `auth_throttles`; the per-grant /mcp limit stays with slice 4.
- `/mcp` answers initialize (no tools), tools/list (empty) and ping for a valid token; 401 with `WWW-Authenticate:
  Bearer resource_metadata=…` otherwise. Membership lost → the grant is revoked on the next call.
- Dev refresh: `refresh_dev.revoke_copied_mcp_grants` (grants revoked as `dev_refresh`, tokens and pending sign-ins
  deleted).
- Tests: `tests/test_remote_mcp_oauth.py` (29); mutation-checked (PKCE, nonce, reuse revocation each caught).

## Decisions (Jared, 2026-10-14: "your recommendations for mcp")

All 16 questions below are decided as recommended: consent on admin.iwobble.com behind Access; one workspace per
connection; plain tool names; read-only preselected (read & write for EDITOR+); access 1 h, refresh 30 days idle
rotating, 180-day cap; reuse the "External MCP hosts" toggle; no static `marvin_tk_` bearer at `/mcp`; prod switch off
until slice 3 is verified on dev; AI operations and per-workflow tools deferred; CIMD later; redirect allowlist;
memberships only for super admins; AI budget enforced in the shared gateway (local MCP included); keep the npm server;
super-admin connected-apps page; Access JWT check later.

## 8. Questions for Jared (recommendation first)
1. **Where does consent live?** Recommend: admin.iwobble.com behind Access, reusing your Marvin login. A login form on api.iwobble.com would reopen the public login page.
2. **One workspace per connection?** Recommend yes: pick it at consent, and connect again for another workspace. Later, optional `/mcp/w/<slug>` URLs so Mash & Burn and Grace's site can be separate connectors.
3. **Tool names:** plain registry names (`find_entries`) or the local server's `marvin_find_entries`? Recommend plain; clients already prefix with the connector name.
4. **Default access at consent:** Recommend read-only preselected; read & write only for EDITOR+.
5. **Lifetimes:** Recommend access 1 h, refresh 30 days idle (rotating), 180-day hard cap, then sign in again.
6. **Per-workspace switch:** reuse the existing "External MCP hosts" AI source toggle, or add a separate "remote" toggle? Recommend reuse (one idea: assistants over MCP).
7. **Accept personal `marvin_tk_` tokens as a static bearer at `/mcp`** for clients that can't do OAuth? Recommend no for now; the npm package covers token use.
8. **Rollout:** Recommend switch off in prod until slice 3 is verified on dev, then on.
9. **AI operations (`marvin_op_*`) and per-workflow tools remotely:** Recommend defer (registry tools + `compose_entry` + `run_workflow` cover the main cases).
10. **CIMD** (Claude's default "published identity" option): Recommend a later slice; DCR first, as with BrainMCP.
11. **Redirect allowlist:** fixed list (claude.ai, claude.com, chatgpt.com, loopback) + admin-editable extras, or accept any https? Recommend the allowlist.
12. **Platform admins:** can a super admin connect to workspaces they aren't a member of? Recommend no; memberships only.
13. **AI budget on MCP tool calls** that use the provider (compose, revise, search): Recommend yes, enforce in the shared gateway. This also changes the local MCP, which skips the check today.
14. **Local `@inneropen/marvin-mcp`:** Recommend keep it; mark remote as the recommended path; no deprecation.
15. **Super-admin "all connected apps" page with revoke:** Recommend yes (2 users today, cheap).
16. **Verify the Cloudflare Access JWT on consent approval** as an extra check: Recommend later, optional.

---

## 9. Uncertain items to settle while building
- Whether cloudflared keeps the `Host` header (affects DNS-rebinding `allowed_hosts`).
- ChatGPT's 2026 redirect URI(s), and whether non-developer mode still limits tools to `search` / `fetch`.
- How ChatGPT reacts to a 404 on an unknown session after a deploy (decides stateful vs stateless).
- Whether SSE response headers go out before the tool finishes (Cloudflare 100 s limit on long compose calls).
- Whether any read-only tool writes incidental rows (decides the read-only Postgres transaction layer).
- Whether Python httpx gets Cloudflare's `1010` the way urllib did (affects the e2e against public hosts).
- Whether Claude's DCR registers `none` or `client_secret_post` (the plan accepts both).

### Critical Files for Implementation
- /home/jared/code/Marvin/src/marvin/routes/ai/operations_controller.py (lines 89-216, 3206-3245: the gating to extract)
- /home/jared/code/Marvin/src/marvin/services/ai/tools/base.py and /home/jared/code/Marvin/src/marvin/services/ai/agents.py (lines 525-623: matrix and `unattended_refusal`)
- /home/jared/code/Marvin/src/marvin/core/dependencies/dependencies.py and /home/jared/code/Marvin/src/marvin/core/security/hasher.py (auth paths, token lookup pattern)
- /home/jared/code/Marvin/src/marvin/app.py (lifespan for the session manager, root-level routes, middleware)
- /home/jared/code/Marvin/src/marvin/services/platform_policy.py and /home/jared/code/Marvin/src/marvin/services/events/event_catalog.py (policy switch, audit events)
- /home/jared/code/Marvin/frontend/src/pages/user/api-tokens.astro, /home/jared/code/Marvin/frontend/src/pages/user/cli-and-mcp.astro, /home/jared/code/Marvin/frontend/src/pages/api/[...path].ts (consent page and connected-apps UI patterns)
- /home/jared/code/Marvin/.venv/lib/python3.12/site-packages/mcp/server/streamable_http_manager.py and .../mcp/server/auth/middleware/client_auth.py (what to reuse vs. avoid)

---

**TLDR.** Everything Marvin needs is already in the repo: `mcp` 1.28.1 is installed, the tool registry holds 53 tools with `read_only` flags and a permission matrix, there is a policy-settings pattern and audit events. Two code facts set the design. First, the session cookie only lives on admin.iwobble.com, so the consent page belongs there behind Cloudflare Access. Second, the SDK's built-in OAuth handlers would repeat BrainMCP's ChatGPT Basic-auth failure, so Marvin should write its own OAuth endpoints and use the SDK only for the MCP transport. Read-only is enforced twice (the tool list and the call), and every request re-checks role, membership, the per-workspace MCP toggle and the token's audience.

Next: approve or adjust the 16 questions, mainly Q2 (one workspace per connection), Q3 (tool names), Q6 (reuse the toggle) and Q13 (budget). Then build slice 1. It is a no-behaviour-change refactor plus tables and stays dark in prod, so it is safe even though every develop push deploys. The largest open risk is how ChatGPT handles losing its session on deploy, which slice 3 tests on purpose.