# Changelog

All notable changes to the Marvin CMS server will be documented in this file.

This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!-- version list -->

## v1.0.0-rc.88 (2026-09-25)

### Features

- **blueprints**: Browse-and-apply page
  ([`cbc15e6`](https://github.com/InnerOpen/marvin/commit/cbc15e69f3b0607d9f15620b48f994d19b672167))


## v1.0.0-rc.87 (2026-09-25)

### Features

- **blueprints**: Ingest provider-declared content; retire the Instagram seed script
  ([`2b71a0c`](https://github.com/InnerOpen/marvin/commit/2b71a0c81d9bf37fa2797a2e55d8fee22bfe7e74))


## v1.0.0-rc.86 (2026-09-25)

### Features

- **blueprints**: Parameters, and a core catalog that names nobody's content
  ([`ed9216c`](https://github.com/InnerOpen/marvin/commit/ed9216c9e43558d12981b2a3fc9e2e6926e5d753))


## v1.0.0-rc.85 (2026-09-25)

### Features

- **blueprints**: Workspace API for browsing and applying blueprints
  ([`6167962`](https://github.com/InnerOpen/marvin/commit/6167962c504ea846ff44f6dcf319dfa0fd0039f8))


## v1.0.0-rc.84 (2026-09-25)

### Features

- **blueprints**: Schema, core catalog and apply semantics
  ([`ce64fe0`](https://github.com/InnerOpen/marvin/commit/ce64fe04f55ab2f4e9312f75dafa20c920a7895a))


## v1.0.0-rc.83 (2026-09-25)

### Bug Fixes

- **workspace**: Stop shipping a 'Recent' collection with every workspace
  ([`921047a`](https://github.com/InnerOpen/marvin/commit/921047ade3791e21cc424b025bbb4b6342533573))


## v1.0.0-rc.82 (2026-09-25)

### Features

- **collections**: Rolling date windows in smart rules; make the Recent default work
  ([`142eb6e`](https://github.com/InnerOpen/marvin/commit/142eb6e9c2cb615e5c901f87af1a2086c306b8ab))


## v1.0.0-rc.81 (2026-09-24)

### Bug Fixes

- **integrations**: Emoji icons and a colour for the IG types and collections
  ([`8a8d183`](https://github.com/InnerOpen/marvin/commit/8a8d183634ad9e50e04131821cb87295a0fe5fb5))


## v1.0.0-rc.80 (2026-09-24)

### Features

- **integrations**: Smart collections for IG rules and sent replies
  ([`53f896f`](https://github.com/InnerOpen/marvin/commit/53f896fb2452cfb464938545a29c9fa239eca7b8))


## v1.0.0-rc.79 (2026-09-24)

### Bug Fixes

- **integrations**: IG reply log entries are published, titled by commenter
  ([`71c65ad`](https://github.com/InnerOpen/marvin/commit/71c65adcac995daefc6298db0b79ecd435e569b4))


## v1.0.0-rc.78 (2026-09-24)

### Features

- **integrations**: Run_integration_action scheduled task + Instagram auto-reply seed
  ([`49490df`](https://github.com/InnerOpen/marvin/commit/49490df8a6fd04727d3b6a90a67436c4cb12307a))


## v1.0.0-rc.77 (2026-09-14)

### Features

- **ai**: Live agent steps — run progress polled while the run is in flight (agents v2, slice B)
  ([`4cafa46`](https://github.com/InnerOpen/marvin/commit/4cafa46619da91993be2ddec52ec6fbf14e6d171))


## v1.0.0-rc.76 (2026-09-14)

### Features

- **ai**: Ask threads — server-side agent conversations (agents v2, slice A)
  ([`49d1aae`](https://github.com/InnerOpen/marvin/commit/49d1aae1d26407a5feb5bf47d4dd6fbf77c1577f))


## v1.0.0-rc.75 (2026-09-13)

### Features

- **ai**: MCP tools placed by their own hints — read / write / destructive rows
  ([`8929438`](https://github.com/InnerOpen/marvin/commit/8929438cdd36a6f5b0ad80569676e1196cb7e327))


## v1.0.0-rc.74 (2026-09-13)

### Bug Fixes

- **ai**: Agents act instead of promising; preamble lists MCP servers; Ask in sidebar
  ([`699540f`](https://github.com/InnerOpen/marvin/commit/699540fd756494f7beda88408e036103898200f2))


## v1.0.0-rc.73 (2026-09-13)

### Features

- **ai**: Agents know what "the RAG" is + workspace_overview tool
  ([`7ab55c2`](https://github.com/InnerOpen/marvin/commit/7ab55c2d37df6eff59cd5c0cb03101295ab569d4))


## v1.0.0-rc.72 (2026-09-13)

### Features

- **ai**: Read-only view_image tool + sticky attachments in Ask
  ([`5e83570`](https://github.com/InnerOpen/marvin/commit/5e8357096e2dbe30595f5e04f25b6e15361d12ea))


## v1.0.0-rc.71 (2026-09-13)

### Features

- **ai**: Agent permission matrix + Agents settings page + Ask becomes the agent chat
  ([`de56ba9`](https://github.com/InnerOpen/marvin/commit/de56ba94fd71957ddcdf7900ff6fc2c78c20067a))


## v1.0.0-rc.70 (2026-09-13)

### Features

- **ai**: Workspace agents v1 — definable persona/model agents, run endpoint, bubble picker, MCP
  tools
  ([`75d4410`](https://github.com/InnerOpen/marvin/commit/75d4410f021ccf73bc66c15bb4261cd166ced0b7))


## v1.0.0-rc.69 (2026-09-13)

### Bug Fixes

- **email**: Unresolved template variables no longer mail the unresolved sentinel
  ([`b1c775b`](https://github.com/InnerOpen/marvin/commit/b1c775b0612a8a05c259a26c089c44026b5dd376))


## v1.0.0-rc.68 (2026-09-12)

### Bug Fixes

- **ui**: Entry-type editor no longer drops capabilities.submission on save
  ([`9dac064`](https://github.com/InnerOpen/marvin/commit/9dac064b0f34a9e723130559e233ca2826e98ac4))


## v1.0.0-rc.67 (2026-09-12)

### Bug Fixes

- **ui**: Browser fetches in email/webhook pages bypassed the session proxy
  ([`9dde843`](https://github.com/InnerOpen/marvin/commit/9dde8434a48c7cf3e95b02590508331c7b722dad))

### Features

- **forms**: Submission protection — platform defaults with per-workspace overrides
  ([`050277b`](https://github.com/InnerOpen/marvin/commit/050277b4094944d7ac32a3e0d68c3583c4b32bac))


## v1.0.0-rc.66 (2026-09-12)

### Bug Fixes

- **ui**: Update banner respected hidden only in theory
  ([`ff9051f`](https://github.com/InnerOpen/marvin/commit/ff9051fd620f023febead6077a1c442cc9b2eae5))


## v1.0.0-rc.65 (2026-09-12)

### Features

- **app**: Public /api/app/about/version for the admin update banner
  ([`76aec4e`](https://github.com/InnerOpen/marvin/commit/76aec4ef21fb0605ceaf9859a76763a3628b89b1))


## v1.0.0-rc.64 (2026-09-12)

### Features

- **ui**: "new version available" banner in the admin
  ([`7666f53`](https://github.com/InnerOpen/marvin/commit/7666f53fef446796673c47ccc1a70829781ba2d1))


## v1.0.0-rc.63 (2026-09-12)

### Bug Fixes

- **ui**: Workflow builder keeps what it cannot edit, and edits the new step fields
  ([`57956e7`](https://github.com/InnerOpen/marvin/commit/57956e7162922f6f07f281d2ef4b2218cdc1c3d1))

### Features

- **webhooks**: A "workflow" webhook type, and delivery logs for workflow steps
  ([`680997a`](https://github.com/InnerOpen/marvin/commit/680997a7225a12973fcd4615ee01425780176cb3))


## v1.0.0-rc.62 (2026-09-11)

### Bug Fixes

- **publish**: Never serve entries of non-publishable types
  ([`0e676a2`](https://github.com/InnerOpen/marvin/commit/0e676a230a50c50c4527b6adc4208b894416f939))


## v1.0.0-rc.61 (2026-09-11)

### Features

- **automations**: Webhook step — method on raw urls, templates in stored urls
  ([`b88e403`](https://github.com/InnerOpen/marvin/commit/b88e4035a6f91fabf3146151ed3ea9d03284b5c9))


## v1.0.0-rc.60 (2026-09-11)

### Features

- **automations**: Entity_query on the entry step
  ([`65ffb64`](https://github.com/InnerOpen/marvin/commit/65ffb648e66d06383bcbc70f1d53fb99989baf1f))


## v1.0.0-rc.59 (2026-09-11)

### Features

- **automations**: Record external ids on entries and target by metadata
  ([`1380e92`](https://github.com/InnerOpen/marvin/commit/1380e92e6b4500b29d5a26eb81f00faac89303a8))


## v1.0.0-rc.58 (2026-09-11)

### Features

- **hooks**: Log the key structure of an incoming payload (keys only)
  ([`4223e10`](https://github.com/InnerOpen/marvin/commit/4223e107ce6e86b96098e0a8acf94f02a184f435))


## v1.0.0-rc.57 (2026-09-11)

### Bug Fixes

- **hooks**: Log the shape of a rejected webhook signature
  ([`41f9f98`](https://github.com/InnerOpen/marvin/commit/41f9f98a204bcc1c8ae4389531c751bc7d6f3a77))


## v1.0.0-rc.56 (2026-09-11)

### Chores

- **chart**: Pin iwobble publicApiUrl to the tunnel host
  ([`2321d42`](https://github.com/InnerOpen/marvin/commit/2321d4243d38ca2153c6a8868d9e2d748d760667))

- **ui**: Vendor-neutral placeholders on the incoming-webhook signing fields
  ([`5d5913f`](https://github.com/InnerOpen/marvin/commit/5d5913fa9c7107de3505af3184c39baea69f3fd6))

### Features

- **ui**: Edit incoming-webhook signing on the card
  ([`ccbf5ca`](https://github.com/InnerOpen/marvin/commit/ccbf5caaa6e34954b974b970d2a98d10f0f949fe))

- **ui**: Generate an incoming-webhook signing key (stored as a secret, shown once)
  ([`d5bbc5d`](https://github.com/InnerOpen/marvin/commit/d5bbc5d78821ff5f5e6aad9061de4c2ea453f008))


## v1.0.0-rc.55 (2026-09-11)

### Features

- **hooks**: Optional HMAC signature verification for incoming webhooks
  ([`a275465`](https://github.com/InnerOpen/marvin/commit/a2754652c396a605e9dad3f18c334a6087d27cb2))


## v1.0.0-rc.54 (2026-09-11)

### Bug Fixes

- **automations**: A non-2xx webhook response fails the step
  ([`fa4f72f`](https://github.com/InnerOpen/marvin/commit/fa4f72f69cc9a4f3c1a79ad130bf4861f47975d6))


## v1.0.0-rc.53 (2026-09-11)

### Bug Fixes

- **automations**: Resolve {{SECRET}} refs in configured webhook headers
  ([`6935bb3`](https://github.com/InnerOpen/marvin/commit/6935bb34f25c2b58a5e77a90d33a00c6a5b1d0e8))


## v1.0.0-rc.52 (2026-09-11)

### Bug Fixes

- **automations**: Entry context tolerates partial entry objects
  ([`c1821a3`](https://github.com/InnerOpen/marvin/commit/c1821a3506bf8a48a2c8034faf9af7703739e175))

### Features

- **automations**: Entry context carries summary and schema fields
  ([`433e949`](https://github.com/InnerOpen/marvin/commit/433e949e4d8280a8905df40723b803971d8d3c8f))


## v1.0.0-rc.51 (2026-09-11)

### Features

- **automations**: Form_submission_received can trigger an automation
  ([`8f1443d`](https://github.com/InnerOpen/marvin/commit/8f1443d14a9adaa2481c624d2370c75a9fe8c89a))


## v1.0.0-rc.50 (2026-09-11)

### Features

- **automations**: Auth_scheme on the webhook action (Token, not only Bearer)
  ([`a65ba7d`](https://github.com/InnerOpen/marvin/commit/a65ba7d0e065097a31d389db0bc3035904d440bb))


## v1.0.0-rc.49 (2026-09-11)

### Bug Fixes

- **deps**: Httpx is a runtime dependency, not an optional extra
  ([`90fb7af`](https://github.com/InnerOpen/marvin/commit/90fb7afffc55fd60892d59261250766870429ef4))

### Chores

- **chart**: Relax the iwobble backend liveness probe
  ([`7271c1b`](https://github.com/InnerOpen/marvin/commit/7271c1b0b51fadb45bfaac9a7e7a6b7a7bc06988))


## v1.0.0-rc.48 (2026-09-11)

### Features

- **publish**: Carry entry data and description on list items
  ([`fadb3f5`](https://github.com/InnerOpen/marvin/commit/fadb3f5220cbc6971bfcd723920e50385bd18441))


## v1.0.0-rc.47 (2026-09-04)

### Bug Fixes

- **ai**: Agent 500 — run_agent read body.register (renamed to tone_register)
  ([`4de61e5`](https://github.com/InnerOpen/marvin/commit/4de61e5aff6a0e66bd806cb7af2fa3a6eadf4632))


## v1.0.0-rc.46 (2026-09-01)

### Bug Fixes

- **media**: Preserve transparency in crop/grade (was flattening onto black)
  ([`bc21db3`](https://github.com/InnerOpen/marvin/commit/bc21db31a623e013aa61dfad52b3d0d3acff3ce7))


## v1.0.0-rc.45 (2026-09-01)

### Features

- **forms**: Rate limiting + CAPTCHA on the entry-type submit path (Phase 1b)
  ([`0fdc23e`](https://github.com/InnerOpen/marvin/commit/0fdc23e28fd00e84adf2984c22c228186fb49be5))


## v1.0.0-rc.44 (2026-09-01)

### Features

- **forms**: Serve submittable entry-type schema from the publishing GET
  ([`f189cce`](https://github.com/InnerOpen/marvin/commit/f189cced0562d05f9178286d130cf60e88303aa6))


## v1.0.0-rc.43 (2026-09-01)

### Bug Fixes

- **events**: Form_submission_received is no longer a dead event
  ([`6e30d18`](https://github.com/InnerOpen/marvin/commit/6e30d1832141c3cf500927cd268680e114fd1587))


## v1.0.0-rc.42 (2026-09-01)

### Features

- **forms**: Route public submits to submittable entry types (forms → entries)
  ([`c192c6c`](https://github.com/InnerOpen/marvin/commit/c192c6c1e722bf403af842b1fcae253e173706d7))


## v1.0.0-rc.41 (2026-09-01)

### Bug Fixes

- **forms**: Read FormRead schema from the ORM's schema_json attribute
  ([`901e8e2`](https://github.com/InnerOpen/marvin/commit/901e8e2b170cc16b08a7bccac75c6f99674bd78f))

### Chores

- **deploy**: Pin iwobble asset URL env + commit cloudflared connector
  ([`57146ad`](https://github.com/InnerOpen/marvin/commit/57146ad6fe2341a62752afb44eb85a73253de3ad))

### Features

- **forms**: Emit form_submission_received on public form submit
  ([`a5a8de2`](https://github.com/InnerOpen/marvin/commit/a5a8de2ea845e53304b15ba1703a495f810b456c))


## v1.0.0-rc.40 (2026-08-31)

### Chores

- Remove committed .mcp.json
  ([`b907103`](https://github.com/InnerOpen/marvin/commit/b9071038d11eecfaa5236840dd6b91541dfefe01))

### Features

- **storage**: STORAGE_LOCAL_PUBLIC_BASE_URL for absolute local-asset URLs
  ([`7a800ca`](https://github.com/InnerOpen/marvin/commit/7a800ca014b49faa4682a1230d9da314020f988f))


## v1.0.0-rc.39 (2026-07-30)

### Bug Fixes

- **ai**: Add missing tone_register field to AIComposeEntryRequest
  ([`f5a9e26`](https://github.com/InnerOpen/marvin/commit/f5a9e2644238705c794aac3abbdc80f5e7c68d1c))

### Chores

- **chart**: Wire OpenAI key into k8s via marvin-ai secret reference
  ([`ad48f4f`](https://github.com/InnerOpen/marvin/commit/ad48f4fbd3995970b1b5cc0a11d3d7d42b68f6b5))


## v1.0.0-rc.38 (2026-07-30)

### Features

- **frontend**: Route browser API calls through a same-origin proxy
  ([`2bc7bb8`](https://github.com/InnerOpen/marvin/commit/2bc7bb8705b2604cb0c8144dd6ae1c7328a12bc1))


## v1.0.0-rc.37 (2026-07-30)

### Bug Fixes

- **frontend**: Add missing scheduled-tasks admin proxy routes
  ([`39c7d1e`](https://github.com/InnerOpen/marvin/commit/39c7d1ed66e0a73127e93511520fbdbaaad3d844))


## v1.0.0-rc.36 (2026-07-30)

### Bug Fixes

- Honor AUTH_COOKIE_NAME setting on the frontend (and backend logout)
  ([`4fcf05a`](https://github.com/InnerOpen/marvin/commit/4fcf05a35cf7b4a9936c5632f8e75470ef9a142d))


## v1.0.0-rc.35 (2026-07-30)

### Bug Fixes

- **frontend**: Make auth cookie Secure flag runtime-configurable
  ([`aa86f3f`](https://github.com/InnerOpen/marvin/commit/aa86f3f6db7b62af8bbe71b81d8835c8db7bb830))


## v1.0.0-rc.34 (2026-07-30)

### Bug Fixes

- **chart**: Set corsOrigins in values-k8s for cross-port NodePort UI
  ([`50fcded`](https://github.com/InnerOpen/marvin/commit/50fcdedd20a5463f926ab4b0be257ee874d15396))


## v1.0.0-rc.33 (2026-07-29)

### Features

- **api**: Enable production CORS for split UI/API deployments
  ([`43b9a53`](https://github.com/InnerOpen/marvin/commit/43b9a5381c7419f5e00ea39a75817084c74065a7))


## v1.0.0-rc.32 (2026-07-29)

### Documentation

- **chart**: Add values-k8s.yaml for plain-Kubernetes deploys
  ([`ce7bd79`](https://github.com/InnerOpen/marvin/commit/ce7bd7928fee6d0a578d834dadc0de1c44a4d4f4))

### Features

- **chart**: Support pinning Service NodePorts
  ([`1ae6f34`](https://github.com/InnerOpen/marvin/commit/1ae6f34ed8e52d1462acdb56385a91fec0af662f))


## v1.0.0-rc.31 (2026-07-28)

### Performance Improvements

- **logs**: Silence health-probe access-log noise
  ([`7b3e38e`](https://github.com/InnerOpen/marvin/commit/7b3e38e63d665357661c7622ebb2ee65bed60e13))


## v1.0.0-rc.30 (2026-07-28)

### Continuous Integration

- Add runner smoke test to verify in-cluster ARC runners
  ([`b251d0f`](https://github.com/InnerOpen/marvin/commit/b251d0feb495f662c4613f87304270708d011954))

- Remove runner smoke test
  ([`56880d4`](https://github.com/InnerOpen/marvin/commit/56880d4fa8b4e4d1d0c977cb5005edf4c40d537c))

- **deploy**: Add manual OpenShift redeploy workflow
  ([`bda2f86`](https://github.com/InnerOpen/marvin/commit/bda2f8680f7bbef11639055afa3f8081d3588372))

### Features

- **helm**: Add iwobble deployment values (split + NFS + plugins)
  ([`a50da5e`](https://github.com/InnerOpen/marvin/commit/a50da5ee3ead9fc6d80e147d8c0120a614665b9a))


## v1.0.0-rc.29 (2026-07-27)

### Bug Fixes

- **frontend**: Honor X-Forwarded-Proto so checkOrigin works behind a TLS proxy
  ([`528d1af`](https://github.com/InnerOpen/marvin/commit/528d1af088892444522a2b51c7ff0163ac9f29b0))

### Features

- **helm**: Split UI/API into separate routes, API internal by default
  ([`073054e`](https://github.com/InnerOpen/marvin/commit/073054e5a40447c40e6e176a299f45b66413a71b))


## v1.0.0-rc.28 (2026-07-26)

### Bug Fixes

- **events**: Allow system-scoped events in the audit log
  ([`bca8a09`](https://github.com/InnerOpen/marvin/commit/bca8a096ccd8569f602a591b3c0af23c429c1f81))

### Features

- **events**: Emit secret_* and variable_* CRUD events
  ([`07337cf`](https://github.com/InnerOpen/marvin/commit/07337cf0a9aa6679ba46ec0a0c79e4c9998ee44f))

- **events**: Migrate event notifiers to apprise integrations (additive)
  ([`e95ace6`](https://github.com/InnerOpen/marvin/commit/e95ace6fc7ed8c3e226c943bdeff9ec9517e3621))


## v1.0.0-rc.27 (2026-07-25)

### Features

- **backup**: Include variables, AI settings, and secrets with a per-workspace key
  ([`eb24c5f`](https://github.com/InnerOpen/marvin/commit/eb24c5fded7ee36a05955322b9e16740a48ae89b))

- **backup**: Include workspace connections & config in export/import
  ([`74e94b3`](https://github.com/InnerOpen/marvin/commit/74e94b30d2a5bddd68574f674347e7a15161c40b))

### Refactoring

- **smtp**: Store the SMTP password in the secret backend via secret_ref
  ([`003f177`](https://github.com/InnerOpen/marvin/commit/003f177d7b3dade08050e34cb53e503f914e2264))


## v1.0.0-rc.26 (2026-07-25)

### Bug Fixes

- **backup**: Skip Marvin-managed collections on restore
  ([`dfdfdfb`](https://github.com/InnerOpen/marvin/commit/dfdfdfb2c8212c124846834e4520da4c7226386e))


## v1.0.0-rc.25 (2026-07-25)

### Bug Fixes

- **frontend**: Pin marvin-sdk to next.28 so the built image has the tags module
  ([`82dcb3e`](https://github.com/InnerOpen/marvin/commit/82dcb3e1355f6cb09eab2e82b2b144b048e613b6))


## v1.0.0-rc.24 (2026-07-25)

### Features

- **scheduler**: Make the tick interval a setting and wire the chart's schedulerInterval
  ([`b6f453b`](https://github.com/InnerOpen/marvin/commit/b6f453b6d812eb20d9b95b737ad74c5a7bc58586))


## v1.0.0-rc.23 (2026-07-25)

### Features

- **scheduler**: Make the leadership lease TTL a setting
  ([`fe88ffe`](https://github.com/InnerOpen/marvin/commit/fe88ffeb344d90616ad297be53f6f367cfabfaa1))


## v1.0.0-rc.22 (2026-07-25)

### Features

- **frontend**: Serve stored media through the frontend
  ([`8fc71da`](https://github.com/InnerOpen/marvin/commit/8fc71da996194e3ce7047902cfd8827b01db4407))


## v1.0.0-rc.21 (2026-07-25)

### Features

- **docker**: Build separate backend and frontend images alongside the combined one
  ([`0f55896`](https://github.com/InnerOpen/marvin/commit/0f55896be67dc8a3cb735468ff14ba17e7bc8386))

- **helm**: Add combined | split deployment mode
  ([`5230b96`](https://github.com/InnerOpen/marvin/commit/5230b96daf34235299dfd1a9d44a285f6f80a1bd))


## v1.0.0-rc.20 (2026-07-25)

### Bug Fixes

- **webhooks**: Let production read webhooks stored with localhost/private URLs
  ([`edc4cbe`](https://github.com/InnerOpen/marvin/commit/edc4cbe6d9872871a0bab2c587505b120a2883da))


## v1.0.0-rc.19 (2026-07-24)

### Bug Fixes

- **ci**: Lowercase the image name in the release image guard
  ([`284c2a4`](https://github.com/InnerOpen/marvin/commit/284c2a46b4163b743d69e65ea6448ccb3952718c))


## v1.0.0-rc.18 (2026-07-24)

### Bug Fixes

- **ci**: Publish the production image on release, not lambda; guard against it
  ([`ea1dd79`](https://github.com/InnerOpen/marvin/commit/ea1dd79eb49edfec8eb50a133d3279ff8fb02724))

### Refactoring

- **frontend**: Use console.debug for DEV_MODE request tracing
  ([`66bc195`](https://github.com/InnerOpen/marvin/commit/66bc195d9a27f6236d5d92f16c3c7c7c0c34850f))


## v1.0.0-rc.17 (2026-07-24)

### Features

- **frontend**: Resolve the backend URL at runtime, not build time
  ([`9af4254`](https://github.com/InnerOpen/marvin/commit/9af42548a97625ea726606ad8afb252b7816429c))


## v1.0.0-rc.16 (2026-07-24)

### Bug Fixes

- **scheduler**: Elect one leader so replicas stop duplicating scheduled work
  ([`acf9aa5`](https://github.com/InnerOpen/marvin/commit/acf9aa5809070ce14e8bb1d396c683664e6716c7))


## v1.0.0-rc.15 (2026-07-24)

### Bug Fixes

- GET /api/admin/groups returned 500 for any workspace containing a user with no username.
  ([`c0fd3a3`](https://github.com/InnerOpen/marvin/commit/c0fd3a31de5d318c83a3f2f0e2f0f9a9afe196ed))

- **config**: Make the frontend actually bind to the port FRONTEND_URL advertises
  ([`4b4e520`](https://github.com/InnerOpen/marvin/commit/4b4e5201837dbff18929a93df4401c465f406752))

### Features

- **frontend**: Add the platform Create User page
  ([`c0fd3a3`](https://github.com/InnerOpen/marvin/commit/c0fd3a31de5d318c83a3f2f0e2f0f9a9afe196ed))


## v1.0.0-rc.14 (2026-07-24)

### Bug Fixes

- **frontend**: Repair broken links on the workspace dashboard
  ([`b98a56d`](https://github.com/InnerOpen/marvin/commit/b98a56dfcb984d869c449ba220e3aaa4b36a3fd5))

### Continuous Integration

- Pin actions to commit SHAs and move off the Node 20 runtime
  ([`f60f3ed`](https://github.com/InnerOpen/marvin/commit/f60f3ed5a8164818b9ee14629f2f8287febe6804))


## v1.0.0-rc.13 (2026-07-24)

### Bug Fixes

- **ci**: Gate release publishing on semantic-release's own output
  ([`5099132`](https://github.com/InnerOpen/marvin/commit/50991321d04554f6837b3f676805b7393f64b325))

### Continuous Integration

- **release**: Keep uv.lock in sync with the version bump
  ([`13e0147`](https://github.com/InnerOpen/marvin/commit/13e01472d1ae15c272acb1f74511f52e155d9890))


## v1.0.0-rc.12 (2026-07-24)

### Features

- **helm**: Support init containers for installing integration plugins
  ([`82341ec`](https://github.com/InnerOpen/marvin/commit/82341ecdd6ecf9179a35607df7c2c6a9cd5066e3))


## v1.0.0-rc.11 (2026-07-24)

### Bug Fixes

- **frontend**: Redirect instead of 500 on protected pages when logged out
  ([`8f57aa4`](https://github.com/InnerOpen/marvin/commit/8f57aa44144f5d35b057014a668b3e95c165f3d6))

- **helm**: Make the chart actually deploy the app
  ([`281d527`](https://github.com/InnerOpen/marvin/commit/281d5278d6121dd91eae3f06734da60e7a2b2254))


## v1.0.0-rc.10 (2026-07-24)

### Bug Fixes

- **helm**: Point chart probes at the new root health endpoints
  ([`04251e5`](https://github.com/InnerOpen/marvin/commit/04251e56e41d92ef4f99a045286bb14de981233e))


## v1.0.0-rc.9 (2026-07-24)

### Features

- **health**: Add root /healthz, /livez, /health, /readyz probes
  ([`9251b51`](https://github.com/InnerOpen/marvin/commit/9251b51adc75e900d7029991966312232b135f00))


## v1.0.0-rc.8 (2026-07-24)

### Features

- **docker**: Build and serve the frontend alongside the API in one image
  ([`5d3cec9`](https://github.com/InnerOpen/marvin/commit/5d3cec91a0f5585350edf8caa9b4d722e2070bfe))


## v1.0.0-rc.7 (2026-07-24)

### Bug Fixes

- **alembic**: Drop the enum types on downgrade so the schema is reversible
  ([`b524990`](https://github.com/InnerOpen/marvin/commit/b524990bd63e33375b03279324e50a2a2767617d))


## v1.0.0-rc.6 (2026-07-24)

### Bug Fixes

- **admin**: Make force-delete of a workspace actually cascade
  ([`e8998be`](https://github.com/InnerOpen/marvin/commit/e8998be7e3241dd6409a7468933e7bef163873e3))

### Code Style

- **ci**: Use the --json shortcut instead of the long --output json form
  ([`0207545`](https://github.com/InnerOpen/marvin/commit/0207545459bb33b3b594dc477aab86174fe616da))

### Testing

- **ci**: Assert the active workspace from JSON instead of grepping prose
  ([`09b3292`](https://github.com/InnerOpen/marvin/commit/09b329269a1fb350ffeb9d141fa1f2c0c76d8e59))

- **ci**: Cover workspace deletion now that force-delete cascades
  ([`788110a`](https://github.com/InnerOpen/marvin/commit/788110a02e11c26ab52975c48cd42415ca1bebd2))

- **ci**: Exercise workspace selection via `workspace use` / `workspace current`
  ([`47149e3`](https://github.com/InnerOpen/marvin/commit/47149e3673010505de08716949ff9262728c759e))


## v1.0.0-rc.5 (2026-07-24)

### Bug Fixes

- **ci**: Authenticate the CLI e2e run and probe a health endpoint that exists
  ([`07f4c80`](https://github.com/InnerOpen/marvin/commit/07f4c80e605345168b0adc22951cee96bebc2c16))

- **ci**: Rewrite the CLI e2e suite against the CLI's real command surface
  ([`3d13e03`](https://github.com/InnerOpen/marvin/commit/3d13e0308bba9cee5a837dec20b5a074fc12136d))


## v1.0.0-rc.4 (2026-07-24)

### Bug Fixes

- **alembic**: Stop silently dropping every index from autogenerated migrations
  ([`4789dbd`](https://github.com/InnerOpen/marvin/commit/4789dbde631e90470838b566aa0dc70e62c76dd5))

- **docker**: Stop shipping demo seed data and auto-importing it in production
  ([`3d4f056`](https://github.com/InnerOpen/marvin/commit/3d4f0565746e458dd32d3a5806ac2e0f52a88035))

- **models**: Reconcile model index/default declarations with the real schema
  ([`0bb4306`](https://github.com/InnerOpen/marvin/commit/0bb43065370b681f1a4d6122c82bf798eab25f57))

### Chores

- **lock**: Sync uv.lock to the 1.0.0rc3 version bump
  ([`2463309`](https://github.com/InnerOpen/marvin/commit/24633099a1fac66a87fce88c3214dcbd29676dcc))

### Code Style

- Clear the repo-wide ruff backlog and unbreak the CI format gate
  ([`28872ac`](https://github.com/InnerOpen/marvin/commit/28872acc9cee50c6ddcc0c5ec7f9240f62382ea1))

### Refactoring

- **alembic**: Squash 41 migrations into a single baseline
  ([`4038b56`](https://github.com/InnerOpen/marvin/commit/4038b56d1c1099dead735b49b1d9ba637e830f2e))


## v1.0.0-rc.3 (2026-07-24)

### Bug Fixes

- **migrations**: Make the webhook_type enum change reversible on Postgres
  ([#20](https://github.com/InnerOpen/marvin/pull/20),
  [`de14656`](https://github.com/InnerOpen/marvin/commit/de146566f1bfbeae10083e871d3a4bc98d8f0e4c))


## v1.0.0-rc.2 (2026-07-24)

### Bug Fixes

- **changelog**: Add the insertion flag so releases update CHANGELOG.md
  ([#19](https://github.com/InnerOpen/marvin/pull/19),
  [`89d0ea1`](https://github.com/InnerOpen/marvin/commit/89d0ea1c1869e32f0e84db166144df63b25015b4))


## v1.0.0-rc.1 (2026-07-24)

- Initial Release

## [0.2.0] - 2026-07-10

Initial version tracking setup with Python Semantic Release.

### Added
- Semantic versioning automation
- Automated changelog generation
- GitHub Actions release workflow

[0.2.0]: https://github.com/InnerOpen/marvin/releases/tag/v0.2.0
