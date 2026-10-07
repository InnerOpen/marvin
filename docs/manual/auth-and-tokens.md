# Auth and tokens

Marvin has three credentials: a session for people using the admin, personal API tokens that act as a user, and API clients that a site or MCP client uses against one workspace. Secrets and variables cover the credentials your automations send to other systems.

## Signing in

`POST /api/auth/token` takes a username/password form, returns `{"access_token": …}` and also sets it as an HttpOnly cookie named by `AUTH_COOKIE_NAME` (default `marvin.access_token`). The admin frontend uses the cookie; `get_current_user` accepts either the cookie or `Authorization: Bearer <jwt>`. A session JWT lives `TOKEN_TIME` hours (default 48) and is signed with the server secret from `DATA_DIR/.secret` (generated on first production start). After `SECURITY_MAX_LOGIN_ATTEMPTS` failures (default 5) the user is locked out for `SECURITY_USER_LOCKOUT_TIME` hours (default 24).

Two external providers can replace the password check:

| Provider | Routes | Settings |
|---|---|---|
| OIDC | `GET /api/auth/oauth` starts the login, `GET /api/auth/oauth/callback` finishes it | `OIDC_AUTH_ENABLED`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_CONFIGURATION_URL`, `OIDC_SIGNUP_ENABLED`, `OIDC_USER_GROUP`, `OIDC_ADMIN_GROUP`, `OIDC_AUTO_REDIRECT`, `OIDC_PROVIDER_NAME`, `OIDC_REMEMBER_ME`, `OIDC_USER_CLAIM`, `OIDC_NAME_CLAIM`, `OIDC_GROUPS_CLAIM`, `OIDC_SCOPES_OVERRIDE`, `OIDC_TLS_CACERTFILE` |
| LDAP | the same `POST /api/auth/token` form, handled by the LDAP provider | `LDAP_AUTH_ENABLED`, `LDAP_SERVER_URL`, `LDAP_TLS_INSECURE`, `LDAP_TLS_CACERTFILE`, `LDAP_ENABLE_STARTTLS`, `LDAP_BASE_DN`, `LDAP_QUERY_BIND`, `LDAP_QUERY_PASSWORD`, `LDAP_USER_FILTER`, `LDAP_ADMIN_FILTER`, `LDAP_ID_ATTRIBUTE`, `LDAP_MAIL_ATTRIBUTE`, `LDAP_NAME_ATTRIBUTE` |

Self-registration is off unless `ALLOW_SIGNUP=true` (OIDC has its own `OIDC_SIGNUP_ENABLED`, default on).

## Roles

A user has one platform role, `NONE` or `SUPER_ADMIN`, and one workspace role per membership. Super admins pass every workspace-role check by default (`require_workspace_role(…, allow_platform_admin=True)`), and the content and settings gates also pass legacy `admin` users.

| Workspace role | Rank | Can (from `roles.py` helpers) |
|---|---|---|
| `OWNER` | 5 | everything an admin can |
| `ADMIN` | 4 | manage workspace settings, members, publishing (API clients), entry types and forms; AI tools that read or run settings; everything an editor can |
| `EDITOR` | 3 | create, edit, approve, publish and delete (move to the Trash, restore, delete forever) any entry; manage assets, resources, collections and tags; read form submissions; AI write tools |
| `AUTHOR` | 2 | create entries and edit or delete their own until approved or published (never approve, publish or schedule one), upload assets, add tags |
| `VIEWER` | 1 | read; every content write answers 403 |

The content routes enforce these with the helpers in `marvin.routes._base.checks` (`require_workspace_role`, `require_workspace_editor`, `require_workspace_admin`, `require_can_create_entry`, `require_can_edit_entry`), before anything is looked up, so a member below the gate gets 403 rather than a 404 that confirms an id exists. Reads of content (lists, gets, counts, collection members) are open to every member. The admin hides the create, edit and delete controls a role can't use and shows a read-only note instead. The full route table is in [`docs/admin-model.md`](https://github.com/InnerOpen/marvin/blob/develop/docs/admin-model.md) (Content route gates).

**Workspace settings are admin-only.** Integrations (including running an action, a health check or an option list), outgoing and incoming webhooks, workflows, scheduled tasks, SMTP profiles, email event subscriptions and test sends, variables and secrets, AI providers and MCP servers, export and backups, and the invitation list need OWNER or ADMIN, for reads as well as writes; other members get 403 and the admin page shows an admins-only note. Member pages still read the integration provider catalog, webhook and task-type lists, secret slugs, email templates, workspace preferences and AI settings. Scheduling a platform maintenance task type (the `admin_only` ones) needs a platform super admin. Before rc.197 several of these settings routes and every content write had no role check.

**AI and MCP tools** follow the same roles: every write tool (`attach_*`, `detach_*`, `add_to_collection`, `remove_from_collection`, `import_asset`, `revise_entry`, `compose_entry`, `archive_entries`, `trash_entries`, `restore_entries`) needs EDITOR, and `list_scheduled_tasks`, `get_scheduled_task_history`, `list_workflows`, `run_workflow`, `describe_event` and `get_ai_settings` need ADMIN. An AUTHOR's AI operation on an entry they can't edit returns its output without applying or staging it (`writeback: "not_permitted"`). See [Agents and Ask](whats-new/agents-and-ask.md).

The route dependencies are `require_workspace_owner`, `require_workspace_admin`, `require_workspace_editor`, `require_workspace_author`, `require_workspace_viewer` and `require_workspace_member`.

## Personal API tokens (`marvin_tk_`)

Create them from **Profile → Manage Tokens** (`/user/api-tokens`) or with `POST /api/users/self/api-tokens`; the same prefix offers list, get, `PATCH`, `DELETE` and `POST …/{token_id}/revoke`. Send it in the `Authorization: Bearer <token>` header. `get_current_user` detects the `SECURITY_TOKEN_PREFIX_USER` prefix, verifies the bcrypt hash and updates `last_used_at`; the token then **is the user**. There are no scopes: a personal token can do exactly what its owner can do in each workspace, as decided by the workspace role above. Only the hash is stored, so the plaintext is available once: creating or rotating a token shows it in a dialog with a copy button and a warning that it won't be shown again, and wipes it from the page however the dialog is closed. Since rc.183 the token never goes into the page URL, where it used to end up in browser history and in the access logs of every proxy in between.

## API clients (`marvin_sk_`)

An API client is a per-workspace credential for sites, `marvin-astro`, `marvin-mcp` and other readers of the publishing API. Manage them at **Settings → Publishing → Site Clients** (the **API Clients** page, `/publishing/clients`; the old `/site-clients` page redirects there) or with `/api/platform/api-clients` (`GET`, `POST`, `GET /{id}`, `PATCH /{id}`, `DELETE /{id}`, `POST /{id}/rotate-token`, `GET /{id}/preview`). The token is returned by create and rotate only, and the admin shows it once in the same kind of dialog (never in the URL or the browser console). Each client's card offers **Edit** (name, description and permissions, saved with `PATCH`, so changing what a site may read no longer means a new token), **Preview**, **Rotate Token**, **Disable** / **Enable** and, on a disabled client only, **Delete**, which confirms with the client's last-used date. The API refuses to delete an enabled client (409 "Disable the client before deleting it."), so a live site's token can't vanish in one step. Every one of these routes, reads included, is for workspace `OWNER`s and `ADMIN`s and platform super admins (the shared `require_workspace_admin` gate, as for incoming webhooks); other members get 403, and the admin pages say so instead of listing clients. A platform-wide admin controller exists at `src/marvin/routes/admin/platform/site_clients_controller.py`, but the admin router does not mount it, so it is not reachable.

Permissions are a JSON map of key to boolean checked by `PermissionChecker` (`src/marvin/core/permissions.py`):

| Key | Grants | Default on create |
|---|---|---|
| `read:published_entries` | published entries | `true` |
| `read:collections` | collections | `true` |
| `read:assets` | assets and asset files | `true` |
| `read:draft_entries` | nothing: no publishing route checks it; `read:all_entries` grants drafts. No longer offered in the admin form | `false` |
| `read:all_entries` | every entry regardless of status | `false` |
| `read:resources` | resources | `false` |
| `write:public_entries` | public submit to a submittable entry type (**Submit Public Entries** in the form) | `false` |
| `read:forms`, `write:forms` | legacy forms | `false` |
| `read:form_submissions`, `write:form_submissions` | legacy form submissions; submit also accepts `write:form_submissions` (**Submit Forms** in the form) | `false` |

The create and edit forms group the keys the routes check under **Content** and **Forms**, and list any other key a client holds under **Other** so it can be removed (see [Publishing API → Permission keys](whats-new/publishing-api.md#permission-keys)).

## Secrets and variables

Workspace **secrets** (`/api/groups/secrets`) never come back in a list or a read; **variables** (`/api/groups/variables`) are readable plain text. Creating, changing, deleting and revealing a secret (`POST /api/groups/secrets/{id}/reveal`, API only) are for workspace OWNERs and ADMINs and platform super admins, and so is the secret list (`GET /api/groups/secrets`: names, descriptions, dates). Other members can still list the slugs (`GET /api/groups/secrets/slugs`), which workflow and webhook forms offer, but never the values or the full list. Before rc.182 any member could create, overwrite or delete a secret, and before rc.183 reveal checked the legacy platform admin flag instead of the workspace role. Both are managed under **Settings → General → Environment** (`/workspace/settings/environment`). Both are referenced as `{{SLUG}}` in outgoing-webhook headers and bodies, workflow webhook steps, incoming-webhook `signing_secret_ref`, CAPTCHA settings, an integration's credential field and email templates. `services/secrets/resolver.py` resolves a secret first, then a variable. An unresolved slug is left as `{{SLUG}}` when `PRODUCTION=false` and replaced with a sentinel that drops the containing header when `PRODUCTION=true`.

`SECRET_BACKEND` selects where secret values live: `database` (default), `disk` (`SECRETS_DIR`, default `DATA_DIR/secrets/`), `env`, `vault` (`VAULT_ADDR`, `VAULT_TOKEN`, `VAULT_MOUNT`, `VAULT_PATH_PREFIX`) or `bitwarden` (`BITWARDEN_ACCESS_TOKEN`, `BITWARDEN_PROJECT_ID`, `BITWARDEN_API_URL`, `BITWARDEN_IDENTITY_URL`).

## Token security settings

| Setting | Default | Meaning |
|---|---|---|
| `SECURITY_TOKEN_PREFIX_USER` | `marvin_tk_` | prefix of personal tokens; also how the server tells a token from a JWT |
| `SECURITY_TOKEN_PREFIX_CLIENT` | `marvin_sk_` | prefix of API client tokens |
| `SECURITY_TOKEN_RANDOM_BYTES` | `32` | entropy; 32 bytes is a 43-character base64url body |
| `SECURITY_BCRYPT_ROUNDS` | `12` | bcrypt cost for passwords, personal tokens and client tokens |
| `SECURITY_MAX_LOGIN_ATTEMPTS` | `5` | failures before lockout |
| `SECURITY_USER_LOCKOUT_TIME` | `24` | lockout length in hours |
| `TOKEN_TIME` | `48` | session JWT lifetime in hours |
| `AUTH_COOKIE_NAME` | `marvin.access_token` | session cookie |

!!! warning "`/openapi.json` stays public"
    `API_DOCS=false` sets `DOCS_URL` and `REDOC_URL` to `None`, which removes Swagger UI and ReDoc. `app.py` does not pass `openapi_url`, so FastAPI keeps serving the schema at `/openapi.json`.

## MCP and OAuth

Marvin has no OAuth authorization server. `marvin-mcp` authenticates with `MARVIN_SITE_CLIENT_TOKEN`, an API client token, plus `MARVIN_API_URL` and `MARVIN_WORKSPACE_SLUG`; MCP clients that call the platform API as a person use a personal token. OIDC is only a way to sign people into the admin. See [Marvin as an MCP server](whats-new/marvin-as-mcp-server.md).
