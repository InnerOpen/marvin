# Changelog

All notable changes to the Marvin CMS server will be documented in this file.

This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!-- version list -->

## v1.1.0-rc.5 (2026-10-20)

### Bug Fixes

- **workflows**: An approved run stays approved after a Wait or a retry
  ([`d76279f`](https://github.com/InnerOpen/marvin/commit/d76279f9bdf7b69a4f40680a2a363911b17df1b4))

### Features

- **plugins**: Facebook, Bluesky and Mastodon plugins; Instagram 0.6.0
  ([`89373c3`](https://github.com/InnerOpen/marvin/commit/89373c3573e6f9c277e22c6bd4f236f0d2659cbc))

- **workflows**: Post to social networks — social.post, approval-gated, every connected network
  ([`50bb808`](https://github.com/InnerOpen/marvin/commit/50bb80885a31e9b81f428f07d3c6ac0090c39afe))


## v1.1.0-rc.4 (2026-10-20)

### Bug Fixes

- **frontend**: The metrics page's tables line up
  ([`7c98019`](https://github.com/InnerOpen/marvin/commit/7c98019db29392aa1ebb3bdcbe9a18e1909af6ee))

### Testing

- The dashboard runs test passes in the first hours after midnight UTC
  ([`9e4e33f`](https://github.com/InnerOpen/marvin/commit/9e4e33f2dd8c4ec7ed54dabc2e3950efad20e5c1))


## v1.1.0-rc.3 (2026-10-19)

### Features

- **workflows**: Call a web API step (request)
  ([`3e06382`](https://github.com/InnerOpen/marvin/commit/3e06382c4fdafbe6c29aa3d74059e34f0b75c47f))

- **workflows**: Template filters
  ([`4ce0d5e`](https://github.com/InnerOpen/marvin/commit/4ce0d5eb0ae6bac76c01927f1fa17d1f877e6c13))


## v1.1.0-rc.2 (2026-10-19)

### Bug Fixes

- **frontend**: The password reset link opens a page that sets the new password
  ([`dd9ee8a`](https://github.com/InnerOpen/marvin/commit/dd9ee8a140d6abdc965931729535310b4c69af79))

### Features

- **frontend**: Marvin's own 404 and 500 pages
  ([`2eb0a8c`](https://github.com/InnerOpen/marvin/commit/2eb0a8c4eb1e10f879c431407f478643457877b3))


## v1.1.0-rc.1 (2026-10-19)

### Continuous Integration

- Run both backend suites in parallel with pytest-xdist
  ([`becc3a7`](https://github.com/InnerOpen/marvin/commit/becc3a716534f6348bc90d6d6d6315f21c0c3eb9))

### Features

- **email**: Workspace email branding
  ([`c58714e`](https://github.com/InnerOpen/marvin/commit/c58714e2dce77933aa7c310504093c0db68b7fcd))

### Testing

- Start each Postgres run on a freshly created database
  ([`3b4cf0b`](https://github.com/InnerOpen/marvin/commit/3b4cf0be91c16542e3c77b68ee8427528b0770a5))


## v1.0.1-rc.3 (2026-10-19)

### Bug Fixes

- **dev**: Task dev:generate runs and matches the committed schema exports
  ([`2cc1f37`](https://github.com/InnerOpen/marvin/commit/2cc1f3782e75d78b0e817474f599f5d5766e7eb8))

- **frontend**: The custom entry types table fits a desktop — actions stay on one line
  ([`c1e1939`](https://github.com/InnerOpen/marvin/commit/c1e1939d7bc23f53ff2ff99d7b4559245b648bc5))

- **taskfile**: Pin the test engine on the command line, not in env
  ([`dd27cc0`](https://github.com/InnerOpen/marvin/commit/dd27cc0647b85464165e10529b7a94dfcf0d3d88))

### Chores

- **dev**: Remove the schema export generator
  ([`eee08cf`](https://github.com/InnerOpen/marvin/commit/eee08cfaff6f24d4e4884f022b635e4fb525eb09))

- **dev**: Remove the stale code generators and module templates
  ([`a676a7b`](https://github.com/InnerOpen/marvin/commit/a676a7b3932af629881acde5a5075104de0a505e))

- **taskfile**: Split task ci into a quick ci and ci:full
  ([`064a2a3`](https://github.com/InnerOpen/marvin/commit/064a2a3a1ab1f893be35a003130d02189dcd2848))

- **taskfile**: Task ci, both-engine tests, helm and deploy wrappers
  ([`2508e43`](https://github.com/InnerOpen/marvin/commit/2508e431f7bb93df15ab54c77794177b8f4b6184))

### Code Style

- Clear the ruff lint findings in src and tests
  ([`1c6c072`](https://github.com/InnerOpen/marvin/commit/1c6c072f3775c26c149d624ccbe9c912619f6a49))

- Format src and tests with the uv.lock ruff
  ([`9aff59e`](https://github.com/InnerOpen/marvin/commit/9aff59ed33b0ddee29071f1d80688a61bfe561e7))

### Continuous Integration

- Install from uv.lock, one ruff version, lint gates pushes and PRs
  ([`13567d1`](https://github.com/InnerOpen/marvin/commit/13567d14513288a93849d55c9c4de0bf2a9c96d9))

- Lint, format check, the SQLite suite in parallel, frontend tests (~3 min). ci:full adds the
  Postgres suite in
  ([`064a2a3`](https://github.com/InnerOpen/marvin/commit/064a2a3a1ab1f893be35a003130d02189dcd2848))

- The push gates locally (ruff lint + format check, the suite on SQLite and Postgres, frontend
  tests) plus an
  ([`2508e43`](https://github.com/InnerOpen/marvin/commit/2508e431f7bb93df15ab54c77794177b8f4b6184))

### Documentation

- Archive the July build-era status reports and old plans
  ([`25815a6`](https://github.com/InnerOpen/marvin/commit/25815a68344f60539348e8d1ece2c1696a7521f5))

- Delete OPENSHIFT_DEPLOYMENT and verify_configuration.py
  ([`336ba3d`](https://github.com/InnerOpen/marvin/commit/336ba3d3b128026fc69c04b580c85311cca439e0))

- Fold still-true reference into the manual
  ([`737e1e0`](https://github.com/InnerOpen/marvin/commit/737e1e01e32306faa71e8b0e0684ccbb635d2618))

### Testing

- Run the suite in parallel with pytest-xdist
  ([`7491111`](https://github.com/InnerOpen/marvin/commit/7491111a82f924bc9e130be36116da7b19c727a6))


## v1.0.1-rc.2 (2026-10-19)

### Bug Fixes

- **frontend**: Entry types on a phone are compact rows again — tap a row to edit
  ([`5346cee`](https://github.com/InnerOpen/marvin/commit/5346cee86751c26a163c5a920d90e74116f2ac35))

### Continuous Integration

- **release**: Don't attach the Helm chart to a prerelease — develop's rc tags have no GitHub
  Release
  ([`eda7805`](https://github.com/InnerOpen/marvin/commit/eda78058da4c64ce8916e7d9cfc4ae8c075218bf))

### Documentation

- **tasks**: Plan — cookie consent banner and privacy policy components (decisions recorded)
  ([`cec335c`](https://github.com/InnerOpen/marvin/commit/cec335c2c56f95f2395e9e752291101c7beaef12))


## v1.0.1-rc.1 (2026-10-19)

### Bug Fixes

- **admin**: Features Status shows what is in force, and where it comes from
  ([`6653379`](https://github.com/InnerOpen/marvin/commit/6653379114c4245c15b41e6c93750528d9f4bd66))

- **frontend**: Custom entry types can be edited on a phone — Edit was ~1000px off-screen in an
  11-column table
  ([`df22ebd`](https://github.com/InnerOpen/marvin/commit/df22ebd212620c9f1621c9ac9d37075cc76d5538))

### Continuous Integration

- Develop prereleases get a tag but no GitHub Release; the SQLite Kind test waits for its pods to
  exist
  ([`d4b706a`](https://github.com/InnerOpen/marvin/commit/d4b706ae86bb1d3f5585fbd308fa497fc2177328))


## v1.0.0 (2026-10-19)

### Chores

- **plugins**: Marvin-storage-s3 0.4.0 — its own object-storage logo
  ([`579b91e`](https://github.com/InnerOpen/marvin/commit/579b91ed42460b290bd23c50d420a2121ced4b06))

### Continuous Integration

- **cli**: Delete the test workspace with --skip-backup
  ([`4c037da`](https://github.com/InnerOpen/marvin/commit/4c037dac14365311913941c4d787cd28a415dfa4))


## v1.0.0-rc.384 (2026-10-19)

### Bug Fixes

- **frontend**: Connected apps can be disconnected on a phone — Disconnect was pushed off-screen
  ([`4ac8ffd`](https://github.com/InnerOpen/marvin/commit/4ac8ffd946da261ab6d329a59e50a7dcb0e4642a))

- **frontend**: The workspace page and its delete panel fit a 390 px screen
  ([`03853d2`](https://github.com/InnerOpen/marvin/commit/03853d2ce3d0b6d741fad0c6c3d948b9eb25bfe6))

### Chores

- **alembic**: Users_group_id_nullable follows the platform SMTP/alerts migrations
  ([`9eb42d4`](https://github.com/InnerOpen/marvin/commit/9eb42d4b80372ae107b183c9e58390deee5b5ec3))

- **deploy**: Drop promote-iwobble.sh — promote.sh does the work
  ([`f1e9d86`](https://github.com/InnerOpen/marvin/commit/f1e9d8688fb9facbc2e50ffcfe8eb9b45a396b7e))

- **dev**: Slim the character kit — Marvin builds packs; keep prompts and references
  ([`203225f`](https://github.com/InnerOpen/marvin/commit/203225f4dec20ef004011435ceaefc9247e3eb21))

- **dev**: Task audit:dead — vulture + knip on demand
  ([`57aeab1`](https://github.com/InnerOpen/marvin/commit/57aeab1fc55a56fe1cbaff69081f45aec4dbd6a3))

- **scripts**: Drop stale manual test scripts
  ([`312d0fc`](https://github.com/InnerOpen/marvin/commit/312d0fcb20f02163441d6723a2e17e3a4a0c53b1))

- **scripts**: Drop the Mash & Burn seed script
  ([`54302e2`](https://github.com/InnerOpen/marvin/commit/54302e247ecf9a72df4bf08ea7d5094b3d319152))

### Documentation

- First boot is Admin, workspaces delete safely, files wait out a grace period
  ([`9e49601`](https://github.com/InnerOpen/marvin/commit/9e49601c898556dd978146bf2f07f596ac8bfbf8))

- **tasks**: Plan — retire the platform workspace (decisions recorded)
  ([`cf562a4`](https://github.com/InnerOpen/marvin/commit/cf562a4f73245259ae13e68ad817a1b116f4e05a))

- **tasks**: Plan — SQLite back as the fresh-install default engine
  ([`7c6d7aa`](https://github.com/InnerOpen/marvin/commit/7c6d7aa2544ea70b7496470a7d34a4d09213f407))

- **tasks**: SQLite plan — decisions recorded (all as recommended)
  ([`39b8217`](https://github.com/InnerOpen/marvin/commit/39b82178f582b36fe53dc83885e7200591bf4516))

### Features

- **admin**: Platform SMTP and Platform channels pages, docs, and stage 1 status
  ([`a83ab07`](https://github.com/InnerOpen/marvin/commit/a83ab074f10573f4ecf0811ccc3f4ca23f971395))

- **alerts**: Platform alert channels that belong to no workspace
  ([`959da3a`](https://github.com/InnerOpen/marvin/commit/959da3acb408d91ab785779eef2b22893c1173c0))

- **backup**: The backup engine backs up, records and restores SQLite again, beside Postgres
  ([`e2c0c4b`](https://github.com/InnerOpen/marvin/commit/e2c0c4bff0bc4e59141e87dfb2daae48069bf9c5))

- **ci**: The suite runs on SQLite and Postgres; docs say SQLite is back
  ([`f14bc10`](https://github.com/InnerOpen/marvin/commit/f14bc103b6842c479f9384da4448cf9f719d027c))

- **db**: Dashboard, admin and models run the same on SQLite and Postgres
  ([`e82be71`](https://github.com/InnerOpen/marvin/commit/e82be71c5d63b9501e2cd05ca48338958a85e571))

- **db**: Races that SQLite's single writer used to lose are closed
  ([`ff5ef0a`](https://github.com/InnerOpen/marvin/commit/ff5ef0a47f226bcae97fa13198cfc9df1b3c7610))

- **db**: SQLite is a supported engine again, and the fresh-install default
  ([`521c33b`](https://github.com/InnerOpen/marvin/commit/521c33b1c4763676e930f1d11a3bdbe249666403))

- **email**: Platform SMTP with per-field Admin overrides over the environment
  ([`67df146`](https://github.com/InnerOpen/marvin/commit/67df1465f540e0f2f276f79d1dba4da4fe814564))

- **frontend**: A user with no workspace is sent to Admin or a waiting-for-an-invite page
  ([`d76f1e4`](https://github.com/InnerOpen/marvin/commit/d76f1e4bf9f411a9e67b3ce08384be589526d856))

- **frontend**: Delete a workspace with a preview, a backup and the typed name; list files awaiting
  a purge
  ([`4ee205d`](https://github.com/InnerOpen/marvin/commit/4ee205dfb7412d898b69062b11727d2461e36a41))

- **migration**: Copy the platform workspace's SMTP profile and alert integrations into platform
  settings
  ([`0df2fef`](https://github.com/InnerOpen/marvin/commit/0df2fefe9cd8a52b224fd0adadd15940933e5c55))

- **secrets**: A platform secret scope (workspace_secrets.group_id NULL)
  ([`1bdcaa6`](https://github.com/InnerOpen/marvin/commit/1bdcaa6a70085598a8f90fe17a823df08a0447ac))

- **workspace**: Fresh installs create no workspace; retire the platform marker
  ([`728e30b`](https://github.com/InnerOpen/marvin/commit/728e30b93b37db208698e17962eed534b3fd0d13))

- **workspace**: Safer workspace deletion and a deferred purge of its stored files
  ([`45e8eed`](https://github.com/InnerOpen/marvin/commit/45e8eed90809c9641dd332c7203332b44299f070))

- **workspace**: Users can be in no workspace; Admin works without one
  ([`3de164d`](https://github.com/InnerOpen/marvin/commit/3de164d8d2e46ab472322993bb3ff9565837cb8f))

### Refactoring

- Drop unused schemas and helpers
  ([`727f56b`](https://github.com/InnerOpen/marvin/commit/727f56be1e2e694b26566bcd9ed0795994b15d8d))

- Remove dead backend files and the broken Lambda entry
  ([`859406c`](https://github.com/InnerOpen/marvin/commit/859406c7e9c0f95d10dcb0ef5dfa618c91d1e3ac))

- Remove the legacy plugin loader (AppPlugins) — entry points are the plugin system
  ([`ded6223`](https://github.com/InnerOpen/marvin/commit/ded622382c78eb099f9d28874b1eaf2cc740a80e))

- **frontend**: Drop unused exports
  ([`f4528d4`](https://github.com/InnerOpen/marvin/commit/f4528d4e4736c0401beb2ee6f340194e545d6c6c))

- **frontend**: Drop unused files and the 0g dependency
  ([`faa4a63`](https://github.com/InnerOpen/marvin/commit/faa4a631910cae1415a3a34eccbcadf0a3012183))

### Testing

- Keep a developer's .env SMTP out of the suite
  ([`9598684`](https://github.com/InnerOpen/marvin/commit/95986847f94e785e33831808779af869c174d26e))

- No-workspace fixture removes the member's API tokens before the user
  ([`ac02dcc`](https://github.com/InnerOpen/marvin/commit/ac02dccdfb0ee2adaf61f3587f9a97ba0a518b7d))

- Platform events have no workspace, so their fixtures clean up by user
  ([`c902b6f`](https://github.com/InnerOpen/marvin/commit/c902b6f82d71abb148e0057154cabbc13f52c0c0))

- **alerts**: The platform channels page test tolerates real message plugins installed alongside the
  fakes
  ([`1fddc8e`](https://github.com/InnerOpen/marvin/commit/1fddc8ea69b2752a1ecc4e5dd85fabb71074b570))


## v1.0.0-rc.383 (2026-10-19)

### Bug Fixes

- **workflows**: Describe_event lists an entry update's diff under updateDiff, not workflowTrigger
  ([`276244a`](https://github.com/InnerOpen/marvin/commit/276244a415fc2a5e758ee8a83c11ecdde01bf17b))

- **workflows**: The guide's records section holds the metric, snapshot and schema check steps —
  actions fits its budget again
  ([`8f01cc0`](https://github.com/InnerOpen/marvin/commit/8f01cc0fbc794168606a2b5795721924f94c4f20))

### Chores

- **alembic**: Mcp_upload_links follows entry_snapshots
  ([`592fac6`](https://github.com/InnerOpen/marvin/commit/592fac6ef8c17b949e32a8acae8f03209b44b83c))

### Features

- **agents**: A read-only agent hands the job to one that may do it — with what it found
  ([`3e68fd1`](https://github.com/InnerOpen/marvin/commit/3e68fd15f7b44ec1741908c8af0776df1185092f))

- **mcp**: MCP Apps image viewer for show_image
  ([`b2ef7dc`](https://github.com/InnerOpen/marvin/commit/b2ef7dc74194b15c2d6a2972349797bba5898033))

- **mcp**: Per-workspace connector URLs, /mcp/w/<slug>
  ([`e29f3ff`](https://github.com/InnerOpen/marvin/commit/e29f3fff39237ff5af781d62cd7a576bfa8df0cd))

- **mcp**: Photo upload links for chat assistants
  ([`619bb34`](https://github.com/InnerOpen/marvin/commit/619bb344d7f845672b0b69b2cbcf001054d88986))

- **workflows**: Classify a form submission — a workflow reads it as ${form_submission.*}, and
  classify-form-submission works on it
  ([`273f038`](https://github.com/InnerOpen/marvin/commit/273f03860db50821713779863f49d659d0b9383d))

- **workflows**: Make a call once — idempotency keys on webhook and integration steps
  ([`9706967`](https://github.com/InnerOpen/marvin/commit/97069676611b6297fa563d9fe44c20a62cdd4c8d))

- **workflows**: React to a type field changing — changed_fields, before and after name it
  ([`277aa7a`](https://github.com/InnerOpen/marvin/commit/277aa7a708242c6e92fb260d18f83570ade9490b))

- **workflows**: Save and restore a version of an entry — a snapshot step and
  /entries/{id}/snapshots
  ([`21d1434`](https://github.com/InnerOpen/marvin/commit/21d1434c2c62241fad1309926ecf2f9aaee62104))


## v1.0.0-rc.382 (2026-10-18)

### Bug Fixes

- **assistant**: The agent knows the greeting the bubble showed
  ([`75ea3f1`](https://github.com/InnerOpen/marvin/commit/75ea3f160e4950bc68fe013156b153293bfa5b50))

### Chores

- **publish**: API clients lose read:assets and read:resources
  ([`abffb57`](https://github.com/InnerOpen/marvin/commit/abffb57827361f3528c5ab05bb4a876156b169d3))

### Continuous Integration

- **sdk**: The SDK gate installs from uv.lock, like the image
  ([`2ab13b1`](https://github.com/InnerOpen/marvin/commit/2ab13b19ededd91e4cfcff0acd10787fafd5c702))


## v1.0.0-rc.381 (2026-10-18)

### Bug Fixes

- **sites**: An asset used only in an entry's field or the brand counts as on the site
  ([`6d7d043`](https://github.com/InnerOpen/marvin/commit/6d7d04324a863da8b6496508608f533ee0c236c5))

- **sites**: Rebuild only when something a site serves changes — emptying the Trash no longer
  rebuilds
  ([`56c4391`](https://github.com/InnerOpen/marvin/commit/56c4391fe7da6637263e493cf15614554847477e))

- **workflows**: An operational event names the workflows that caused it, not whichever had run in
  its chain
  ([`b47fcac`](https://github.com/InnerOpen/marvin/commit/b47fcacb9b07e73cc45aae907d28e4d9bc1720eb))

- **workflows**: The guide fits its budgets again with every new step
  ([`9a337dd`](https://github.com/InnerOpen/marvin/commit/9a337dd51de60c684574ba50b8b5321b8e5cd7e1))

### Documentation

- **tasks**: Review of the 2026-10-18 Workflow Library and publishing work
  ([`5313907`](https://github.com/InnerOpen/marvin/commit/531390765dd638c1bbf636e107ad85fe1cd5c6e0))

- **workflows**: Roadmap row 22 names the commit that delivered custom events
  ([`367cc67`](https://github.com/InnerOpen/marvin/commit/367cc672d656aa1edababce30b80fbfc9ba0165a))

- **workflows**: The library's roadmap and catalogue match what ships
  ([`9c12941`](https://github.com/InnerOpen/marvin/commit/9c12941fc75190580f698c287eb75cd9d32f6407))

### Features

- **admin**: System shows the embedding model and its versions; Plugins shows available updates
  ([`07def60`](https://github.com/InnerOpen/marvin/commit/07def609617fa7afd5a87d2f976e4e124f744cd1))

- **publish**: Entries resolve their asset and resource fields; the last resource route goes
  ([`73daa0a`](https://github.com/InnerOpen/marvin/commit/73daa0a056900848c5cdfd782ba9b423ca1a499a))

- **publish**: The publishing API serves entries and the site — assets and resources come with their
  entries
  ([`4e71f42`](https://github.com/InnerOpen/marvin/commit/4e71f42074482b6a104c920827daf561e09ab5d0))

- **workflows**: A metric step can add to the count — each event once
  ([`c265d9c`](https://github.com/InnerOpen/marvin/commit/c265d9c4f8256dbfb4fd9acfe8f869ecf0e191e0))

- **workflows**: Check against a schema — a step that validates JSON and reports what's wrong
  ([`241af62`](https://github.com/InnerOpen/marvin/commit/241af627e19ef596fe5e7b90a7a90edfe823ca3a))

- **workflows**: Custom events — a workspace names its own, workflows send and react to them
  ([`2a450a8`](https://github.com/InnerOpen/marvin/commit/2a450a82d8fb285de448728210c14316bbdd2d4d))

- **workflows**: Email a person — a step that writes to a member of the workspace
  ([`a5b4b54`](https://github.com/InnerOpen/marvin/commit/a5b4b54f1495da1a815262a035b5221f85fff76c))

- **workflows**: Metrics — a step records an observation per variant and window; a page lists them
  ([`89d9bb7`](https://github.com/InnerOpen/marvin/commit/89d9bb7b10f1491db210e8c4b572a168de78f6a7))

- **workflows**: Operational events as triggers — a workflow can answer a failed webhook, a budget
  alert or a stuck integration
  ([`2f1d13a`](https://github.com/InnerOpen/marvin/commit/2f1d13af4100aa9337352a7293e500acdaf4017e))

- **workflows**: Run branches side by side and join them — all or any, merged in order
  ([`378554e`](https://github.com/InnerOpen/marvin/commit/378554e3cef312dc1ae4aef4d5772c06481d9692))

### Testing

- **workflows**: Repair tasks sharing a title list oldest first, so the health-companion test
  doesn't depend on row order
  ([`d3b88e9`](https://github.com/InnerOpen/marvin/commit/d3b88e92ba90610ae58f41aee8be181b8be79eba))


## v1.0.0-rc.380 (2026-10-17)

### Features

- **logos**: AI providers show their logos; integration plugins bumped to the versions that ship one
  ([`de653f6`](https://github.com/InnerOpen/marvin/commit/de653f6063409f7c8bc87a0ef2b521c17c2f6a8f))


## v1.0.0-rc.379 (2026-10-16)

### Bug Fixes

- **character**: Picking a library character always names the assistant (or agent) after it
  ([`439b0f9`](https://github.com/InnerOpen/marvin/commit/439b0f96feb93970134526e2b774854ecc679886))


## v1.0.0-rc.378 (2026-10-16)

### Features

- **character**: Library characters carry their persona — pick copies it, Reset re-copies; agents
  get their own; portable pack .zip
  ([`00c1bf8`](https://github.com/InnerOpen/marvin/commit/00c1bf83fe6e950c28f1796265a286c37c901ebb))


## v1.0.0-rc.377 (2026-10-16)

### Features

- **character**: A lone PNG upload names the character from its file name (Elvira.png → Elvira); a
  .zip's name and the Name box still win
  ([`c113ea8`](https://github.com/InnerOpen/marvin/commit/c113ea824ff13a061c8774205e73e5e4590aedcc))


## v1.0.0-rc.376 (2026-10-16)

### Features

- **ui**: Assets and Resources get the Entries search; slim lists; Trash counts; integration logos
  in the sidebar
  ([`43c05cb`](https://github.com/InnerOpen/marvin/commit/43c05cbb6e56f7dbc01c7e2ee98ae00cb7be5046))


## v1.0.0-rc.375 (2026-10-16)

### Features

- **nav**: Integration collections fold under their integration; Entries is Cards · List
  ([`bee2cb1`](https://github.com/InnerOpen/marvin/commit/bee2cb170dc9422f9f1e6e7d808ca7f5a48eca6b))


## v1.0.0-rc.374 (2026-10-16)

### Features

- **entries**: A List view with small pictures, and Cards · List on every collection
  ([`3c09209`](https://github.com/InnerOpen/marvin/commit/3c0920927cd520208a84e36630331b8372d2a406))


## v1.0.0-rc.373 (2026-10-16)

### Features

- **entries**: Beaker-style search — a title box, status buttons, and stacked condition rows
  ([`ef7dab7`](https://github.com/InnerOpen/marvin/commit/ef7dab756793fd774405889fed61f890261e6bfc))


## v1.0.0-rc.372 (2026-10-16)

### Bug Fixes

- **entries**: One search only — the chips; the right-hand search box and menus are gone
  ([`5b40843`](https://github.com/InnerOpen/marvin/commit/5b408436870152f97fa6f2cb8cafb2a8b3ee208d))

- **nav**: All entries sits under Content, above Collections (Jared)
  ([`b29bf85`](https://github.com/InnerOpen/marvin/commit/b29bf858111ddcb1cddd58741e8e1f9349310ba3))

- **nav**: An "All entries" row at the top of the sidebar's Entries group
  ([`ee3ea1a`](https://github.com/InnerOpen/marvin/commit/ee3ea1a9914f49ec4f55ef6ad3bdb3656b19b6bc))


## v1.0.0-rc.371 (2026-10-16)

### Bug Fixes

- **entries**: A compact condition editor, one value at a time
  ([`3e13dfd`](https://github.com/InnerOpen/marvin/commit/3e13dfd4cbe936e6c090e0c11f247aa64808783e))


## v1.0.0-rc.370 (2026-10-16)

### Bug Fixes

- **entries**: The condition editor's checkbox list wraps inside the editor
  ([`7915f61`](https://github.com/InnerOpen/marvin/commit/7915f61687bbb4be2ccc75c4fa80af97acea5802))


## v1.0.0-rc.369 (2026-10-16)

### Features

- **entries**: One search bar — the quick filters set chips, the search box still filters as you
  type
  ([`1c3620f`](https://github.com/InnerOpen/marvin/commit/1c3620f84e029ba64a6cf3a2e9c81a4a6dc206f8))


## v1.0.0-rc.368 (2026-10-16)

### Bug Fixes

- **entries**: The condition editor stays hidden until "+ Add condition"
  ([`a5789aa`](https://github.com/InnerOpen/marvin/commit/a5789aa251dc60884c6963689a9f88b475658148))


## v1.0.0-rc.367 (2026-10-16)

### Features

- **entries**: Structured search — add a condition, then another, then another
  ([`6102c98`](https://github.com/InnerOpen/marvin/commit/6102c986f45e2b6c851011594ff90c1c0a2c2ca9))


## v1.0.0-rc.366 (2026-10-16)

### Bug Fixes

- **assets**: A new version is labelled by its bytes, not its original's type
  ([`a699894`](https://github.com/InnerOpen/marvin/commit/a699894546a2db77109ad42270fba142eef51df4))


## v1.0.0-rc.365 (2026-10-16)

### Bug Fixes

- **ai**: Send a picture to the model with the type its bytes say
  ([`33492c0`](https://github.com/InnerOpen/marvin/commit/33492c0c3f58a1a419281951e610984431dca867))


## v1.0.0-rc.364 (2026-10-16)

### Features

- **agents**: A read-only agent's referral reaches an agent that can write, in one click
  ([`46fd6ab`](https://github.com/InnerOpen/marvin/commit/46fd6abbb13c30bc5ebd4a53c828b2a1c2b9c784))


## v1.0.0-rc.363 (2026-10-16)

### Features

- **assets**: Say which pictures search can't find, and let a person describe them
  ([`0ce247f`](https://github.com/InnerOpen/marvin/commit/0ce247fac92dbfaec4cfeec3734693270b9df1f5))


## v1.0.0-rc.362 (2026-10-15)

### Bug Fixes

- **ai**: Ask may open the entries it finds; compose researches for itself
  ([`8a86db5`](https://github.com/InnerOpen/marvin/commit/8a86db5ce984fbf7b757ab2c30ae4213b137b13b))


## v1.0.0-rc.361 (2026-10-15)

### Bug Fixes

- **ai**: Say when to compose vs save a draft, and that search returns snippets
  ([`33f8a9d`](https://github.com/InnerOpen/marvin/commit/33f8a9da235ff0eeace441c48332f298890b44b9))


## v1.0.0-rc.360 (2026-10-15)

### Features

- **ai**: Create_draft and update_draft — save a draft the caller wrote, with no AI of Marvin's
  ([`4697fa3`](https://github.com/InnerOpen/marvin/commit/4697fa3f1b618388ea202df050c02b1d5e16fa19))

### Testing

- **mcp**: Search_content is listed while there is an embedding model
  ([`85e3a37`](https://github.com/InnerOpen/marvin/commit/85e3a37b02ca913d9709849098662aff5c0042df))


## v1.0.0-rc.359 (2026-10-15)

### Features

- **ai**: Marvin's own embedding model — search no longer depends on the chat provider
  ([`6c6ca06`](https://github.com/InnerOpen/marvin/commit/6c6ca06b89c58ccc94ad0f9b22af149a7a8c2137))


## v1.0.0-rc.358 (2026-10-15)

### Bug Fixes

- **mcp**: Hide search_content where the workspace has no embedding model
  ([`b482f7c`](https://github.com/InnerOpen/marvin/commit/b482f7cf46c6d9f51e6eda3c7c92e78917635128))


## v1.0.0-rc.357 (2026-10-15)

### Features

- **ai**: Test connection asks the workspace's model for a structured answer
  ([`6045580`](https://github.com/InnerOpen/marvin/commit/6045580c4abfc9f4208c47a08115104715569abe))

- **mcp**: ChatGPT's search and fetch, a per-connection request limit, and the docs
  ([`bd88217`](https://github.com/InnerOpen/marvin/commit/bd882176ba9aeab9524f0df3ac832460fa41549d))


## v1.0.0-rc.356 (2026-10-15)

### Features

- **mcp**: Compose_entry over the remote MCP server — a connection can create drafts
  ([`0fc8902`](https://github.com/InnerOpen/marvin/commit/0fc890205f74352799a81fc94cbb473d4747f6d4))


## v1.0.0-rc.355 (2026-10-15)

### Bug Fixes

- **ai**: A slug that parses as a UUID (an Instagram media id) resolves by slug
  ([`d5dd5ac`](https://github.com/InnerOpen/marvin/commit/d5dd5ac789e70a9f8c103dc545e42b2f45179ee4))

### Chores

- **mcp**: Log each remote tool listing and call (name, outcome, content types)
  ([`5cc75dd`](https://github.com/InnerOpen/marvin/commit/5cc75dde13e9129f0d8951023a731c42c3f4d198))


## v1.0.0-rc.354 (2026-10-15)

### Bug Fixes

- **ai**: Marvin-ai-anthropic 0.3.1 — a leading thinking block no longer breaks completions
  ([`e52d2b8`](https://github.com/InnerOpen/marvin/commit/e52d2b8c7030882661c593c9fcf74f14e2b69900))

### Features

- **mcp**: Show_image — the remote MCP server hands back the picture itself
  ([`2bf5a07`](https://github.com/InnerOpen/marvin/commit/2bf5a07437b526c1ec0afbfad6baeff9cb1446ba))


## v1.0.0-rc.353 (2026-10-15)

### Bug Fixes

- **ai**: Marvin-ai-anthropic 0.3.0 — structured output works on claude-sonnet-5-5
  ([`6269eb8`](https://github.com/InnerOpen/marvin/commit/6269eb8fe992fc807807d13a71ff1936c2d55312))


## v1.0.0-rc.352 (2026-10-15)

### Features

- **ai**: Find_entries rows carry updatedAt and publishedAt
  ([`1cb3263`](https://github.com/InnerOpen/marvin/commit/1cb3263c728e93a9eb975e5416788ba273de6ec5))


## v1.0.0-rc.351 (2026-10-15)

### Bug Fixes

- **deps**: Keep mcp below 2 — the remote MCP server is built on 1.x's low-level Server
  ([`e5d6591`](https://github.com/InnerOpen/marvin/commit/e5d6591230ed88c92420bdd1b1c8064db1fd5a7d))


## v1.0.0-rc.350 (2026-10-15)

### Features

- **mcp**: Remote MCP slice 3 — Marvin's tools, prompts and resources at /mcp
  ([`56b37be`](https://github.com/InnerOpen/marvin/commit/56b37beea3f777da01b4501e2843954945cdc689))


## v1.0.0-rc.349 (2026-10-15)

### Bug Fixes

- **storage**: The Storage settings page declares its breadcrumb (settings.storage)
  ([`26375e6`](https://github.com/InnerOpen/marvin/commit/26375e6907883810e41d72815b80c55b6f7987ef))

### Features

- **mcp**: Remote MCP slice 2 — OAuth sign-in, consent page and connected apps
  ([`d013079`](https://github.com/InnerOpen/marvin/commit/d01307961161229a2899ada97a262401671022d3))


## v1.0.0-rc.348 (2026-10-15)

### Features

- **storage**: Bring your own storage, slice 5 — a workspace's own backups in its own private bucket
  ([`d9ab2d1`](https://github.com/InnerOpen/marvin/commit/d9ab2d1650b2ffed6436c468f6a3052c2d055dc7))


## v1.0.0-rc.347 (2026-10-15)

### Features

- **ai**: One gateway for unattended tool calls, with the AI budget
  ([`6f7f384`](https://github.com/InnerOpen/marvin/commit/6f7f384348804d70cc8f0bb847b466c9254abe1f))

- **mcp**: Remote MCP slice 1 — OAuth tables, the remote_mcp switch (off), discovery metadata, purge
  ([`0339548`](https://github.com/InnerOpen/marvin/commit/0339548900a81fc9baa18c639b3ddc32aaa287d0))


## v1.0.0-rc.346 (2026-10-15)

### Features

- **storage**: Bring your own storage, slice 4 — hourly bucket checks, backup visibility, bundle
  switch
  ([`b5d46fe`](https://github.com/InnerOpen/marvin/commit/b5d46fe7f047643fea8e6d5f9f30e3207cdae1f1))


## v1.0.0-rc.345 (2026-10-15)

### Features

- **storage**: Copy events — workspace_storage_copy_started and _finished
  ([`445c40f`](https://github.com/InnerOpen/marvin/commit/445c40f02d62a43b1bf5c1cf67bf31e73d3a1b72))


## v1.0.0-rc.344 (2026-10-15)

### Documentation

- **tasks**: MCP OAuth plan — all sixteen questions decided as recommended
  ([`da9dc92`](https://github.com/InnerOpen/marvin/commit/da9dc92394feece90434660ba49c35bbf1f4974b))

### Features

- **storage**: Bring your own storage, slice 3 — copy a workspace's existing files into its own
  bucket
  ([`2f3ff06`](https://github.com/InnerOpen/marvin/commit/2f3ff0649765c2668637043d2c9bddc76b3ffbff))


## v1.0.0-rc.343 (2026-10-14)

### Documentation

- **tasks**: Remote MCP with OAuth sign-in plan — five slices, sixteen questions
  ([`506088f`](https://github.com/InnerOpen/marvin/commit/506088f16b29f1b0ce109b55c8cbab8b6da316c0))

### Features

- **storage**: Bring your own storage, slice 2 — Workspace → Storage page, API, Check connection,
  policy switch
  ([`74ed875`](https://github.com/InnerOpen/marvin/commit/74ed8752f5e4d29dd255f9f2ccde8a6bafac8d05))


## v1.0.0-rc.342 (2026-10-14)

### Bug Fixes

- **assets**: Drop the upload service's second smart-collection join, which failed on every upload
  ([`8a50883`](https://github.com/InnerOpen/marvin/commit/8a50883daa4769ad11b4901dcf9f6cbae47d64bc))


## v1.0.0-rc.341 (2026-10-14)

### Features

- **user**: Command line & MCP page — install and sign in the CLI, connect the MCP server, with this
  Marvin's API address
  ([`e90e693`](https://github.com/InnerOpen/marvin/commit/e90e6934ace2fe67458af2c381fa14e018bb0c02))


## v1.0.0-rc.340 (2026-10-14)

### Bug Fixes

- **storage**: A workspace connection's access key ID can be a workspace secret; the own-bucket
  check ignores keys
  ([`4278fa5`](https://github.com/InnerOpen/marvin/commit/4278fa5454596d59d94bcd3524aebfc9434c7698))


## v1.0.0-rc.339 (2026-10-14)

### Features

- **storage**: Bring your own storage, slice 1 — a workspace's uploads can go to its own bucket
  (inert: policy off)
  ([`e98f551`](https://github.com/InnerOpen/marvin/commit/e98f5518b038f83a1b23898189ad327f5e94ace5))


## v1.0.0-rc.338 (2026-10-14)

### Bug Fixes

- **dev**: A dev refresh drops the previous refresh's pause records before pausing
  ([`7898827`](https://github.com/InnerOpen/marvin/commit/789882703544b27a67d83d7c95008af8907caabe))

### Code Style

- **collections**: The Sidebar control is a switch
  ([`fe72885`](https://github.com/InnerOpen/marvin/commit/fe728856b0f714d524b1f6b5c663dc40ac3328e1))

### Documentation

- **postgres**: Dev holds production's .secret, so copied secrets decrypt there
  ([`dc408a4`](https://github.com/InnerOpen/marvin/commit/dc408a4fa15b2b432d40b5ebcdf3f5e4fab9beb5))

- **tasks**: Bring-your-own-storage decisions — all ten answered
  ([`d39584a`](https://github.com/InnerOpen/marvin/commit/d39584abef5bf25cf52ba61ad45312ecd729c075))


## v1.0.0-rc.337 (2026-10-14)

### Documentation

- **manual**: The tools-on-demand note sits in the usage section, not a section of its own
  ([`2f96b88`](https://github.com/InnerOpen/marvin/commit/2f96b88b787f22757936098acd65438ae08cbd08))

- **tasks**: Bring-your-own-storage plan — ws: locations, five slices, open questions
  ([`94c5077`](https://github.com/InnerOpen/marvin/commit/94c50775850fc09e96bb2f6acbde1b9457818030))

### Features

- **admin**: Overview lists recent sign-ins and plugins with a newer release
  ([`93ab333`](https://github.com/InnerOpen/marvin/commit/93ab3333dbcf93408539d9998746ef71d625472b))

- **ai**: Tools on demand — all-tools agents start lean and load a tool group when a question needs
  it
  ([`e5674ff`](https://github.com/InnerOpen/marvin/commit/e5674ffcfb9554fd5b05371e49253da6f77aa00a))

- **collections**: A Sidebar switch picks which collections the sidebar lists
  ([`22c89fc`](https://github.com/InnerOpen/marvin/commit/22c89fcfdeeec39939a7e69ab52cd369d715942d))

### Testing

- **workflows**: The authoring test accepts workflow tools named in load_tools
  ([`a9145e0`](https://github.com/InnerOpen/marvin/commit/a9145e095ca60a7cda3188447096552ba417cc77))


## v1.0.0-rc.336 (2026-10-14)

### Bug Fixes

- **workflows**: Workflow limit lookups clamp to range and ignore a value that isn't a number
  ([`034947a`](https://github.com/InnerOpen/marvin/commit/034947ad23f4971e635a18a32d7dea49728f1f75))

### Documentation

- **manual**: Admin overview, security and branding, workspace limits, workflow run retention
  ([`075ff55`](https://github.com/InnerOpen/marvin/commit/075ff552a1659646d44e2ac60e34307fcf3f2f41))

### Features

- **admin**: Overview health strip, workspaces and AI spend; Security and email Branding settings;
  dead settings gone
  ([`fb32bcc`](https://github.com/InnerOpen/marvin/commit/fb32bccec1f65f2697337d3e6947a3a789169387))

- **retention**: Prune_workflow_runs — finished workflow runs and their steps go after 90 days
  ([`3593d35`](https://github.com/InnerOpen/marvin/commit/3593d3550682ad3403712fb124329581118d2219))

- **workspace**: Limits a workspace sets — agent steps, chat memory, bulk-change threshold, workflow
  steps, approval wait
  ([`70ac614`](https://github.com/InnerOpen/marvin/commit/70ac614343fb895f9fa87ddf6bf11a057c04cb5d))


## v1.0.0-rc.335 (2026-10-14)

### Bug Fixes

- **security**: Reset links expire; one password minimum everywhere; template edits survive
  restarts; agent steps a setting
  ([`c7a80e8`](https://github.com/InnerOpen/marvin/commit/c7a80e879cf73e9c986175d339186c894f14287e))

### Documentation

- **manual**: Reset links expire; one minimum password length
  ([`5d06752`](https://github.com/InnerOpen/marvin/commit/5d067529bc9541619fe4c40b570c91e2fef85ad1))


## v1.0.0-rc.334 (2026-10-14)

### Bug Fixes

- **chart**: Set BASE_URL / FRONTEND_URL — prod's reset and invite emails linked to localhost
  ([`ec93ddf`](https://github.com/InnerOpen/marvin/commit/ec93ddf61f12fcbb77dab19eb04b4cef96bc9c87))

- **email**: A password reset's "Platform" is a badge with a reason, not a button-shaped label
  ([`d103e91`](https://github.com/InnerOpen/marvin/commit/d103e912565f7f27cc4f9f34a6399654990fac3d))

### Chores

- **frontend**: SDK 3.2.0-next.28 → 5.12.0 — the bubble shows the provider's reason, not "Server
  error: 502"
  ([`e211787`](https://github.com/InnerOpen/marvin/commit/e211787092523b80120bf382e0644833a639121d))

- **integrations**: Marvin-integration-instagram 0.5.3 — token refresh passes the token as a
  parameter
  ([`3bc71ad`](https://github.com/InnerOpen/marvin/commit/3bc71ad9adc1989f598ccf1bfbf77d4b6351126d))

### Code Style

- **tests**: Lint the cache-rate test
  ([`1dcb26c`](https://github.com/InnerOpen/marvin/commit/1dcb26c4d8db9bf77f7e5666799eb50219464573))

### Documentation

- **manual**: Database & cleanup, and Scheduled Tasks grouped by owner
  ([`feec8b0`](https://github.com/InnerOpen/marvin/commit/feec8b001ccab3c27975254f5cd0ccd0eaf43fa9))

### Features

- **admin**: Maintenance becomes Database & cleanup — the largest tables and what keeps each in
  check
  ([`3380d7f`](https://github.com/InnerOpen/marvin/commit/3380d7fc35f60a3663308419d989a2029a8e6309))

- **admin**: Scheduled Tasks lists System first, then each workspace's under its name; Events uses
  the full width
  ([`90a4360`](https://github.com/InnerOpen/marvin/commit/90a43608673aa76cd8081f25402d2a694c742201))

- **ask**: Search conversations — titles and everything said, with the words around each hit
  ([`94bd4b8`](https://github.com/InnerOpen/marvin/commit/94bd4b8928d216c1c2671042d6ea93fe220c6998))

- **incoming-webhooks**: "N received" opens the last calls and what each carried
  ([`3a413bf`](https://github.com/InnerOpen/marvin/commit/3a413bfaf8f7fdde3b958ccfe46f855eebabe5b0))

### Testing

- **ai**: The cache-rate test stands in for the Anthropic plugin; the caching note sits under the
  usage card
  ([`0d2a6b0`](https://github.com/InnerOpen/marvin/commit/0d2a6b0f08318af5b6be06578dbf1b22c6da7a51))


## v1.0.0-rc.333 (2026-10-14)

### Chores

- **ai**: Marvin-ai-google 0.1.1 — default model gemini-3.8-flash (Google retired 2.5-flash for new
  keys)
  ([`42c8520`](https://github.com/InnerOpen/marvin/commit/42c852045f15ecec93ce8829af1427f85294bfd3))

### Code Style

- **dashboard**: One frame, two column stacks, every section a panel
  ([`f2e6893`](https://github.com/InnerOpen/marvin/commit/f2e6893796584eb5631ed3816f2b685f0e8be2c7))

- **dashboard**: Recent activity joins the left column so the two stacks end level
  ([`ce8ac7d`](https://github.com/InnerOpen/marvin/commit/ce8ac7d0162f44bd86643a5e15772418cd514e92))

### Features

- **ai**: Prompt caching — cached tokens reported, priced at the cache rates, shown per run
  ([`3f27221`](https://github.com/InnerOpen/marvin/commit/3f2722145fa753899506316ac7a9c5f7739c3b65))


## v1.0.0-rc.332 (2026-10-14)

### Features

- **approvals**: A picture's decision stays with the asset — stamped on its metadata, shown,
  filterable
  ([`6c99c7f`](https://github.com/InnerOpen/marvin/commit/6c99c7f4c853583e0a54c059d8489b94a619581e))


## v1.0.0-rc.331 (2026-10-14)

### Chores

- **ai**: Marvin-ai-openai 0.1.1 — prices for gpt-image-2 and the other current image models
  ([`dd47b30`](https://github.com/InnerOpen/marvin/commit/dd47b30e5e5978628e2d9d8fa25c4780de82eaa4))

### Features

- **assets**: A generated image links its entry and workflow; asset and resource lists stack on a
  phone
  ([`ff8a227`](https://github.com/InnerOpen/marvin/commit/ff8a2275ee93de17d068b8f74696ffa88a470961))


## v1.0.0-rc.330 (2026-10-14)

### Bug Fixes

- **workflows**: The editor knows attach_asset — label, fields, and the manual
  ([`2d1967c`](https://github.com/InnerOpen/marvin/commit/2d1967cfd7a1697bc564cf535759b1805de03bb0))


## v1.0.0-rc.329 (2026-10-14)

### Bug Fixes

- **workflows**: Attach_asset declares what it sends (asset_attached_to_entry)
  ([`7826699`](https://github.com/InnerOpen/marvin/commit/7826699f715cb88b013612d19a6ce11c667e3982))


## v1.0.0-rc.328 (2026-10-14)

### Bug Fixes

- **assets**: A row or a card opens its asset wherever it's tapped
  ([`35dfba6`](https://github.com/InnerOpen/marvin/commit/35dfba68d9f84aab49d75c998824165f28793fa7))


## v1.0.0-rc.327 (2026-10-14)

### Features

- **workflows**: An approval can show a picture, and attach_asset links one only once approved
  ([`68d8392`](https://github.com/InnerOpen/marvin/commit/68d8392a6a9d0c1dc50dfa95c9c55aee7da7868a))


## v1.0.0-rc.326 (2026-10-14)

### Bug Fixes

- **frontend**: A JSON body is sent as JSON — approving a workflow from the page failed with 422
  ([`7d458f5`](https://github.com/InnerOpen/marvin/commit/7d458f528bb06068e9036c927123c78259a54576))


## v1.0.0-rc.325 (2026-10-14)

### Chores

- **integrations**: Instagram 0.5.2 — the recipe makes a JPEG copy before posting
  ([`2bff003`](https://github.com/InnerOpen/marvin/commit/2bff0030e2dcf11d716f1651a2fc7fa619b0d8ee))

### Features

- **integrations**: OpenAI Images 0.4.0, and a labelled Check connection button on every card
  ([`15a182b`](https://github.com/InnerOpen/marvin/commit/15a182bb8e994e49f54a9936cc66f1bffdaa20bd))


## v1.0.0-rc.324 (2026-10-14)

### Features

- **integrations**: Instagram 0.5.1 — post to the feed, with the plugin's own recipe
  ([`39a3f27`](https://github.com/InnerOpen/marvin/commit/39a3f27b0cef963b3754282ad9e2b8ee68bb5a9c))


## v1.0.0-rc.323 (2026-10-14)

### Features

- **publishing**: Typed privacy & cookies block in Site Settings
  ([`1395816`](https://github.com/InnerOpen/marvin/commit/139581636f743a060d29cc643a35d86ddd46baa5))

### Refactoring

- **ai**: One runner records and runs an operation for the route and the workflow step
  ([`e028cc4`](https://github.com/InnerOpen/marvin/commit/e028cc45cdf89ec117ac754f45d091e11a1ca950))

- **backup**: Drop the SQLite paths from the backup engine
  ([`694bd7b`](https://github.com/InnerOpen/marvin/commit/694bd7bea1f9d7344da36c9d7c11e88d6c6eb687))


## v1.0.0-rc.322 (2026-10-14)

### Chores

- **settings**: Drop the "Custom Fields — coming soon" card
  ([`84c29eb`](https://github.com/InnerOpen/marvin/commit/84c29eb47da20b41fc645504ad0f0469b1c729dc))

- **tasks**: Lessons live in the Brain, not the repo
  ([`1113e71`](https://github.com/InnerOpen/marvin/commit/1113e71aa6c5648e22d1866dd33f10a4c9102b58))

### Features

- **dashboard**: Second pass — pick up where you left off, published by week, content by type
  ([`f8bb372`](https://github.com/InnerOpen/marvin/commit/f8bb372fc1b00efba502e2a06f5fab251796447c))

### Testing

- **library**: Date-based waits take the event date from the workspace's calendar
  ([`a59ff23`](https://github.com/InnerOpen/marvin/commit/a59ff23095f1b9c6ae9c3c74c982ea432f83e84b))


## v1.0.0-rc.321 (2026-10-14)

### Bug Fixes

- **settings**: The Preferences card opens the site form instead of saying "coming soon"
  ([`088609c`](https://github.com/InnerOpen/marvin/commit/088609cd3de811a1f71682bdcf102e3f63cc5614))


## v1.0.0-rc.320 (2026-10-13)

### Bug Fixes

- **entries**: The Ask button carries the workspace's assistant name
  ([`c386a42`](https://github.com/InnerOpen/marvin/commit/c386a425ad7d658d824db2667cbda98476f8f739))


## v1.0.0-rc.319 (2026-10-13)

### Features

- **dashboard**: AI usage against the workspace's limits
  ([`1cbd888`](https://github.com/InnerOpen/marvin/commit/1cbd888a4246ce216f1400080735381af3be58cd))


## v1.0.0-rc.318 (2026-10-13)

### Bug Fixes

- **entries**: Ask Marvin asks for a revision, so the improvements land as a suggestion
  ([`8302af0`](https://github.com/InnerOpen/marvin/commit/8302af0382da604d33e973e1aad5405e0d142a33))


## v1.0.0-rc.317 (2026-10-13)

### Features

- **entries**: Ask Marvin goes to the Ask page when the bubble is off, in the same thread
  ([`2591aca`](https://github.com/InnerOpen/marvin/commit/2591aca7b9de733ac413586fa0c26395a6bff5ba))


## v1.0.0-rc.316 (2026-10-13)

### Features

- **entries**: One Ask Marvin button replaces the AI menu, Generate and Improve
  ([`fb49d1e`](https://github.com/InnerOpen/marvin/commit/fb49d1e1e53394d86361c3ad793946ac97e7edec))


## v1.0.0-rc.315 (2026-10-13)

### Features

- **frontend**: Drop the Review Queue button and the app's Review shortcut
  ([`959537a`](https://github.com/InnerOpen/marvin/commit/959537a0b59b51960bf4e5419978df48c200d196))


## v1.0.0-rc.314 (2026-10-13)

### Bug Fixes

- **entries**: The per-field Improve button stays out of the Marvin chat composer
  ([`16f5eb3`](https://github.com/InnerOpen/marvin/commit/16f5eb3d04a8e7fd1f31df06ee26f385778701cf))


## v1.0.0-rc.313 (2026-10-13)

### Features

- **dashboard**: One dashboard at /, with the live panels; /workspace redirects there
  ([`e82dffe`](https://github.com/InnerOpen/marvin/commit/e82dffea0daaf12cc75d361580d57dc04676c82d))


## v1.0.0-rc.312 (2026-10-13)

### Bug Fixes

- **dashboard**: A caller without a readable role still gets the dashboard
  ([`6c4f7c3`](https://github.com/InnerOpen/marvin/commit/6c4f7c36d7747663c2edf6a552d9cc62566cc761))


## v1.0.0-rc.311 (2026-10-13)

### Features

- **dashboard**: What waits on you, what's coming up, a health strip and a runs sparkline
  ([`d564023`](https://github.com/InnerOpen/marvin/commit/d564023c5009e0fd4ddf700e19727e4d7806db3e))


## v1.0.0-rc.310 (2026-10-13)

### Bug Fixes

- **ci**: Vault test job gets a Postgres service; Helm workflow runs on its own changes
  ([`4744557`](https://github.com/InnerOpen/marvin/commit/47445575e98ec67159536b59688a1fcefaf902d7))


## v1.0.0-rc.309 (2026-10-13)

### Bug Fixes

- **ci**: Make the Postgres-only pipeline green
  ([`e4743d5`](https://github.com/InnerOpen/marvin/commit/e4743d5aba428db3935ce0ec74ad58fecf7f3888))


## v1.0.0-rc.308 (2026-10-13)

### Chores

- **todo**: SQLite stays for now — Jared: trash it soon, not yet
  ([`2cad883`](https://github.com/InnerOpen/marvin/commit/2cad8833efbed74ae13ee4d562e8d53f03bd14aa))

### Features

- **db**: Retire SQLite — Marvin runs on Postgres only
  ([`2fb4473`](https://github.com/InnerOpen/marvin/commit/2fb44737f94f052a756f93bcf0c28d67b745aec2))


## v1.0.0-rc.307 (2026-10-13)

### Bug Fixes

- **groups**: Renaming a workspace through its preferences actually renames it
  ([`607dc21`](https://github.com/InnerOpen/marvin/commit/607dc21351403c6de4f445b36bacc2161c21c5d6))


## v1.0.0-rc.306 (2026-10-13)

### Features

- **frontend**: Assets and Resources fold open to their types, with counts
  ([`32e4c98`](https://github.com/InnerOpen/marvin/commit/32e4c987675d09742b97ebec9b3781b4d6c86004))


## v1.0.0-rc.305 (2026-10-13)

### Features

- **frontend**: A Gmail-shaped sidebar — New, entry folders with counts, collections and settings
  folded
  ([`f917d70`](https://github.com/InnerOpen/marvin/commit/f917d702a1bd9bc600bcb5028ece230bface8c42))


## v1.0.0-rc.304 (2026-10-13)

### Bug Fixes

- **frontend**: The breadcrumb shows the settings tab a page belongs to
  ([`973fdaa`](https://github.com/InnerOpen/marvin/commit/973fdaa3eb1dd5d5950cea4990e0fe75f76831e5))


## v1.0.0-rc.303 (2026-10-13)

### Bug Fixes

- **frontend**: Every admin and workspace page fits a phone
  ([`44ef84f`](https://github.com/InnerOpen/marvin/commit/44ef84fa6c1a9c30b01bbe0fc3e5ba1b58d5f43b))

### Refactoring

- **workflows**: The authoring guide is read like a vault — an index first, then the sections a
  request needs
  ([`b7a4194`](https://github.com/InnerOpen/marvin/commit/b7a419404e4b2399b179900cd109fc962c1b4774))


## v1.0.0-rc.302 (2026-10-13)

### Features

- **workflows**: Member events as triggers (${member.*}); Community welcome pack runs
  ([`382c275`](https://github.com/InnerOpen/marvin/commit/382c27509da229b759c09f837ca7ed4f02cd1ae9))


## v1.0.0-rc.301 (2026-10-13)

### Features

- **workflows**: Thank-you notes and Post-event recap recipes (built on Repeat for each)
  ([`65986ca`](https://github.com/InnerOpen/marvin/commit/65986ca5a2dc6cbe42379f950e555b148c5b1d4a))


## v1.0.0-rc.300 (2026-10-13)

### Bug Fixes

- **workflows**: A waiting run finds its step by id and goes on with the edited workflow; a
  cancelled wait is announced
  ([`d1db920`](https://github.com/InnerOpen/marvin/commit/d1db920999307759098b0369f84d1355c674b2c2))


## v1.0.0-rc.299 (2026-10-13)

### Features

- **workflows**: Approvals with choices, length conditions, cancelling a waiting run
  ([`f12b80c`](https://github.com/InnerOpen/marvin/commit/f12b80c17574d091da965b962ddec780836a089a))


## v1.0.0-rc.298 (2026-10-13)

### Features

- **workflows**: A guided form for Repeat for each; Entry steps can target By id
  ([`4409abf`](https://github.com/InnerOpen/marvin/commit/4409abf54004b1d46d7ceb0be267c10d5ee2807d))


## v1.0.0-rc.297 (2026-10-13)

### Features

- **workflows**: Repeat for each — a few steps once per item of a list
  ([`0e7c993`](https://github.com/InnerOpen/marvin/commit/0e7c993b51976e74a03531d3b00dccea53580dc1))


## v1.0.0-rc.296 (2026-10-13)

### Features

- **workflows**: Time capsule and Intake triage recipes run today
  ([`00f286b`](https://github.com/InnerOpen/marvin/commit/00f286b379c2ec892aedf95b40035a225554e13a))


## v1.0.0-rc.295 (2026-10-13)

### Bug Fixes

- **deps**: Patch the vulnerable dependencies (pip-audit and npm audit clean)
  ([`307c8fd`](https://github.com/InnerOpen/marvin/commit/307c8fd26aa602e205c3841cb6a475538203c0db))


## v1.0.0-rc.294 (2026-10-13)

### Bug Fixes

- **admin**: Asset storage fits a phone
  ([`27db730`](https://github.com/InnerOpen/marvin/commit/27db730828d9c38e89fd268220b92019d11dedd3))


## v1.0.0-rc.293 (2026-10-13)

### Features

- **workflows**: Thread builder, teaser ladder, carousel storyteller, launch kit — as draft recipes
  ([`79bac75`](https://github.com/InnerOpen/marvin/commit/79bac75c9b6f907ab57976f1ff49f583164000ac))


## v1.0.0-rc.292 (2026-10-13)

### Features

- **workflows**: Social recipes — share links, on this day, audience milestone, shout-out
  ([`0674828`](https://github.com/InnerOpen/marvin/commit/0674828efe26d7433085a009734fa314c2e09a1c))


## v1.0.0-rc.291 (2026-10-13)

### Bug Fixes

- **workflows**: Phone-width recipe sheet; recipe date pickers offer every entry's dates
  ([`fc2de5a`](https://github.com/InnerOpen/marvin/commit/fc2de5ac107e026c529bb309dd226066ff01ce93))


## v1.0.0-rc.290 (2026-10-13)

### Features

- **workflows**: Wait — a run kept and resumed later; Event countdown
  ([`37d59e9`](https://github.com/InnerOpen/marvin/commit/37d59e9ec75cc1b4a31b55e5b9f63a1e1026fa5d))


## v1.0.0-rc.289 (2026-10-13)

### Features

- **workflows**: Watermarks — text and/or a logo over a copy of a picture, in a corner or tiled
  across it
  ([`91012b2`](https://github.com/InnerOpen/marvin/commit/91012b2de44b25bf625b2dc62ee8b7020abac7d1))


## v1.0.0-rc.288 (2026-10-13)

### Bug Fixes

- **media**: The PDF reader writes no core dump; the crash test gives a crashing reader time to die
  ([`9988791`](https://github.com/InnerOpen/marvin/commit/9988791ffe167d7f2e17c33805fb682a34b692c7))

- **ui**: Start from a recipe fills a phone's screen instead of landing off-centre
  ([`63d3283`](https://github.com/InnerOpen/marvin/commit/63d328378f0bfb3f2f2f64f0d5d96f3a6703abde))


## v1.0.0-rc.287 (2026-10-13)

### Bug Fixes

- **media**: Read PDFs in a separate, time-limited process — a bad file fails one step, not the
  server
  ([`4048d2a`](https://github.com/InnerOpen/marvin/commit/4048d2a352e98a5c60b58985cc0ac6f20c5c3fb7))


## v1.0.0-rc.286 (2026-10-13)

### Features

- **workflows**: Edit a picture with an integration — background removal, product scenes, seasonal
  variants
  ([`841483a`](https://github.com/InnerOpen/marvin/commit/841483a0cd5f21d822cf292eb720a66085504c72))


## v1.0.0-rc.285 (2026-10-12)

### Features

- **workflows**: ZIP archives and printed PDFs — Archive packager, Workshop field guide
  ([`3b9bdfc`](https://github.com/InnerOpen/marvin/commit/3b9bdfc78dd3d4950c09cdc265a2f76f38f4a79e))


## v1.0.0-rc.284 (2026-10-12)

### Features

- **workflows**: Media slice 3 — a document's text, PDF pages as pictures, faces and personal
  details blurred
  ([`58e99a1`](https://github.com/InnerOpen/marvin/commit/58e99a1c27de961be48a314746c3cec671ae7c9c))


## v1.0.0-rc.283 (2026-10-12)

### Features

- **workflows**: Run inputs — a manual workflow asks for what it needs when it runs; cron in the
  editor's schedule
  ([`5c42d5c`](https://github.com/InnerOpen/marvin/commit/5c42d5cc9a3490872a5fd7e376ad8fd6e3160067))


## v1.0.0-rc.282 (2026-10-12)

### Features

- **workflows**: Three more recipes — a changed resource's entries, a re-uploaded file, entries a
  field change breaks
  ([`0bc6b56`](https://github.com/InnerOpen/marvin/commit/0bc6b56d0e0e9ef6133fc9403d78353189a2190d))


## v1.0.0-rc.281 (2026-10-12)

### Bug Fixes

- **security**: The guarded HTTP client connects to the address it checked (DNS rebinding)
  ([`62d93fb`](https://github.com/InnerOpen/marvin/commit/62d93fbb75e87dc2cb53de04bde4d08f02cb204a))


## v1.0.0-rc.280 (2026-10-12)

### Bug Fixes

- **ui**: An asset's "Made from" and metadata links look like links
  ([`66ef747`](https://github.com/InnerOpen/marvin/commit/66ef747483e49f5105edee9010243834819f5701))


## v1.0.0-rc.279 (2026-10-12)

### Bug Fixes

- **ui**: Space the Workflows header buttons; an asset's derived_from / rendered_from link to those
  pictures
  ([`644b893`](https://github.com/InnerOpen/marvin/commit/644b893441de84e3e90faa74220fe1ab2a56443d))


## v1.0.0-rc.278 (2026-10-12)

### Bug Fixes

- **workflows**: Dry runs preview steps fed by an AI answer; unchanged saves save nothing; a step id
  and result key in the editor
  ([`cea1ce5`](https://github.com/InnerOpen/marvin/commit/cea1ce57f6e53b1501575075cb8812f59fec3180))


## v1.0.0-rc.277 (2026-10-12)

### Features

- **workflows**: Linked items in queries, and a step that checks a web address
  ([`8246d37`](https://github.com/InnerOpen/marvin/commit/8246d37930e3089560d813e9608d9f42189b0e90))


## v1.0.0-rc.276 (2026-10-12)

### Features

- **admin**: Times show in your own time zone; AI Executions lists the tools an agent run used
  ([`b9121a2`](https://github.com/InnerOpen/marvin/commit/b9121a283af807448223bb7b1cd0458c92749c33))

- **workflows**: Gather items — a collect step turns many into one; relative dates in every query
  ([`891a1fc`](https://github.com/InnerOpen/marvin/commit/891a1fc57f429d2ab8ead2ce9f14f75472a9ce10))


## v1.0.0-rc.275 (2026-10-12)

### Bug Fixes

- **workflows**: The editor flags a Set metadata / Set fields step with nothing to set; unchecked
  target filters are left out
  ([`9f23de2`](https://github.com/InnerOpen/marvin/commit/9f23de2b22226f62677c22936eb1981508c5670b))


## v1.0.0-rc.274 (2026-10-12)

### Bug Fixes

- **workflows**: A media step takes the URL an asset is served at — ${entry.image} works as a
  picture
  ([`d62208e`](https://github.com/InnerOpen/marvin/commit/d62208e7f388aa56305001e864faee360669b2ba))


## v1.0.0-rc.273 (2026-10-12)

### Features

- **workflows**: Render a template — cards, quotes, posters, trading cards, memes, comics, front
  pages as images
  ([`be1f0d3`](https://github.com/InnerOpen/marvin/commit/be1f0d3929b306b8aa1d3b4e9b0db847e0b528b9))


## v1.0.0-rc.272 (2026-10-12)

### Features

- **assets**: Workflows run on originals, a grid view, smart rules by origin, tags on made images,
  versions follow their original to the Trash
  ([`1f5311d`](https://github.com/InnerOpen/marvin/commit/1f5311de945a140242f60a5812cef519a57b769a))


## v1.0.0-rc.271 (2026-10-12)

### Features

- **assets**: The library folds versions under their original and filters on the server
  ([`9932dde`](https://github.com/InnerOpen/marvin/commit/9932ddea9dad89b237fe1674b1a23b24184495dd))


## v1.0.0-rc.270 (2026-10-12)

### Performance Improvements

- **workflows**: Crops of one picture share one subject detection
  ([`b88f2a8`](https://github.com/InnerOpen/marvin/commit/b88f2a8d9f42ac6fcb16199acd6af1bbd609eb7a))


## v1.0.0-rc.269 (2026-10-12)

### Features

- **workflows**: Process an image — a step that makes images from images; generated images kept as
  assets
  ([`8e9f851`](https://github.com/InnerOpen/marvin/commit/8e9f851968f90605d6745dcb6ce4d4868b0d8bba))


## v1.0.0-rc.268 (2026-10-12)

### Bug Fixes

- **workflows**: One run of a workflow on an entry at a time — no more double Square listings
  ([`2c9dd5b`](https://github.com/InnerOpen/marvin/commit/2c9dd5bbb3e023b35d8ed7c386be35083333fbfe))


## v1.0.0-rc.267 (2026-10-12)

### Bug Fixes

- **workflows**: List an entry type once when the workspace has its own copy of a built-in
  ([`2983f24`](https://github.com/InnerOpen/marvin/commit/2983f24ace7eb9a819a9e446ec0908a16bfc280a))


## v1.0.0-rc.266 (2026-10-12)

### Bug Fixes

- **workflows**: The Run button starts a run in the background instead of waiting for it
  ([`4c65485`](https://github.com/InnerOpen/marvin/commit/4c65485a94b570384c49bf4df7e22b175b89b66f))


## v1.0.0-rc.265 (2026-10-12)

### Features

- **workflows**: One-tap Approve / Deny on a waiting workflow's notification
  ([`befe2ef`](https://github.com/InnerOpen/marvin/commit/befe2ef00a2b800c9898cd822b5055c8994587ad))


## v1.0.0-rc.264 (2026-10-12)

### Features

- **workflows**: Wait for approval — a step that parks the run until a person approves or denies
  ([`13f5aff`](https://github.com/InnerOpen/marvin/commit/13f5aff24a2f5bc6b29b811f929dc6f807233149))


## v1.0.0-rc.263 (2026-10-12)

### Bug Fixes

- **workflows**: Create an entry shows its type, title and status before the fields
  ([`911273e`](https://github.com/InnerOpen/marvin/commit/911273eb23ca0d826cffbbc3ad313120ce52b624))


## v1.0.0-rc.262 (2026-10-12)

### Features

- **workflows**: Create an entry — a workflow step that makes a draft, once per event; four recipes
  run
  ([`add56c0`](https://github.com/InnerOpen/marvin/commit/add56c068f61cd95be87db59cbf842eb77ef4d63))


## v1.0.0-rc.261 (2026-10-11)

### Build System

- Buttondown 0.7.0, Apprise 0.3.0, Square 0.4.0, Instagram 0.4.0 — each ships its guide (and a
  recipe)
  ([`9675bd7`](https://github.com/InnerOpen/marvin/commit/9675bd7bf798d07918f7d8cf7db4e3b4d640cba5))

### Features

- **workflows**: Custom AI steps — your own instructions and answer fields, checked; five recipes
  run
  ([`a3f1058`](https://github.com/InnerOpen/marvin/commit/a3f1058d05eeb8925a74fcdf4b32f60bd3538dca))


## v1.0.0-rc.260 (2026-10-11)

### Features

- **workflows**: Conditional steps — a step's `when` makes if/else
  ([`0962daf`](https://github.com/InnerOpen/marvin/commit/0962dafaa7abf01136a58f0896f7bfcc98a9a814))


## v1.0.0-rc.259 (2026-10-11)

### Build System

- N8n 0.2.0 — its guide and the Hand published entries to n8n recipe
  ([`189322f`](https://github.com/InnerOpen/marvin/commit/189322f9e6e7c1e317015f83760ddf132e0bc4dc))

### Features

- **workflows**: An AI step on an asset sees the image and writes back — the Alt text assistant and
  Attribution companion recipes run
  ([`f62a137`](https://github.com/InnerOpen/marvin/commit/f62a137ec82f2f8a1b8f2888ee85a7b8ff8965a5))


## v1.0.0-rc.258 (2026-10-11)

### Build System

- Pin the SDK and every baked-in plugin to a release tag, not main (AI plugins slice 7)
  ([`694b240`](https://github.com/InnerOpen/marvin/commit/694b240f045adea25b561ac9a8c34c56be898694))

### Features

- **integrations**: An integration teaches Marvin about itself — its recipes in the Workflow
  Library, its guide for the agents and search_docs
  ([`aef3868`](https://github.com/InnerOpen/marvin/commit/aef3868adfea983f83bc867f8815cc709d4689d9))


## v1.0.0-rc.257 (2026-10-11)

### Features

- **ai**: Core ships no AI provider — Anthropic, Google and Ollama are plugins (slice 5, folds in 2)
  ([`ba180bc`](https://github.com/InnerOpen/marvin/commit/ba180bca4c366ade1ceaf60fc59f3f12674a2d83))


## v1.0.0-rc.256 (2026-10-11)

### Features

- **ai**: Daily AI price feed from a configurable URL (LiteLLM format) — slice 4
  ([`071785e`](https://github.com/InnerOpen/marvin/commit/071785e8b02b1891a8f268a1c5a2e4b15f63f2ee))


## v1.0.0-rc.255 (2026-10-10)

### Features

- **ai**: Admin → AI Pricing — your own price per model, the price list, and Backfill (slice 3)
  ([`d2e66c7`](https://github.com/InnerOpen/marvin/commit/d2e66c73401d258b54cc9f1a4edf4fd31c7e61d9))


## v1.0.0-rc.254 (2026-10-10)

### Features

- **ai**: Runs with no price are counted and shown, not $0 — AI provider plugins slice 1
  ([`abd140b`](https://github.com/InnerOpen/marvin/commit/abd140b36b7a6e8da08b9f3714f45ea641077068))


## v1.0.0-rc.253 (2026-10-10)

### Bug Fixes

- **agents**: Builder looks up the workspace's real entry type and field keys before giving steps
  ([`4306e94`](https://github.com/InnerOpen/marvin/commit/4306e94b93ed599f5fa00c26c6e6b407dfa6fc96))

### Documentation

- **todo**: AI provider plugins — status as built, plan v2 with Jared's decisions
  ([`69b6a9e`](https://github.com/InnerOpen/marvin/commit/69b6a9e8501769019a0c46f37f523dd3e524b27b))


## v1.0.0-rc.252 (2026-10-10)

### Bug Fixes

- **dev**: The refresh Job drops the backup CronJob's pod affinity and data volume
  ([`e60b428`](https://github.com/InnerOpen/marvin/commit/e60b428618300ba25c259a04c7d0d82b0f9a0a07))

### Features

- **agents**: Builder — step-by-step set-up help in the editor's own words, drafts on request
  ([`e62a4c7`](https://github.com/InnerOpen/marvin/commit/e62a4c76a752c2aef5b5c0df1cae8cb39b6a2523))

- **prod**: Start backups from Admin → Scheduled Tasks on production (backup.scheduledTasks.enabled)
  ([`8eaf5b8`](https://github.com/InnerOpen/marvin/commit/8eaf5b8d799ff15a48020a938f98b526e5cae089))


## v1.0.0-rc.251 (2026-10-10)

### Features

- **dev**: `task dev:refresh` — refresh marvin-dev from production's newest backup in one command
  ([`7f1031f`](https://github.com/InnerOpen/marvin/commit/7f1031fd7358bf22b47d199569060460cc33af52))

- **events**: Turn on / Turn off on an event's integration actions and workflows, installed ones too
  ([`1dd1a8c`](https://github.com/InnerOpen/marvin/commit/1dd1a8c1bfc49b83bbb113b4ab23e18cb59f9e14))


## v1.0.0-rc.250 (2026-10-10)

### Features

- **dev**: Start backups from Admin → Scheduled Tasks on marvin-dev (backup.scheduledTasks.enabled)
  ([`519c104`](https://github.com/InnerOpen/marvin/commit/519c104dd865430bf22f9d61ba37e8a87bdd5fee))


## v1.0.0-rc.249 (2026-10-10)

### Bug Fixes

- **backup**: Declare AssetSources with the type statement — clears the engine's 5 mypy errors
  ([`79cc95e`](https://github.com/InnerOpen/marvin/commit/79cc95efe89f313e60c2acd76b3b34ea4a07b521))


## v1.0.0-rc.248 (2026-10-10)

### Chores

- **chart**: Delete values-staging.yaml — no staging exists; marvin-dev is pre-production
  ([`c643796`](https://github.com/InnerOpen/marvin/commit/c64379639fb73b2247bab946dd4bf40bb23a4843))

### Features

- **chart**: Dev yields to production on worker01 — PriorityClass, quota, half-CPU limits
  ([`df457c7`](https://github.com/InnerOpen/marvin/commit/df457c79e5e76651c83e9912e2d9f9800ed6e5ca))


## v1.0.0-rc.247 (2026-10-10)

### Features

- **backups**: Per-workspace backup bundles, made daily and copied off-site under bundles/
  ([`6c7ca48`](https://github.com/InnerOpen/marvin/commit/6c7ca48d231105081816c87d33b453d535263725))


## v1.0.0-rc.246 (2026-10-10)

### Bug Fixes

- **chart**: Default to production mode — dev mode OOMKilled the Kind install (Helm Validation red
  since 10-06)
  ([`647d385`](https://github.com/InnerOpen/marvin/commit/647d385d35dc422b1d6201fd18dc881d9eeb279d))

### Features

- **agents**: Set_automation_enabled — switch an automation on or off after the admin approves
  ([`0d4de83`](https://github.com/InnerOpen/marvin/commit/0d4de836c98ea7ffe9874dd0a0bb24743406b9ba))

- **trash**: Assets and Resources list what's in the Trash, like Entries
  ([`a75d4a0`](https://github.com/InnerOpen/marvin/commit/a75d4a03fa8e23ccedd9f84183daf4e5e5cc105c))


## v1.0.0-rc.245 (2026-10-10)

### Features

- **backups**: Start a backup target from Admin → Scheduled Tasks (Run Now or a Marvin-owned
  schedule)
  ([`a2247e9`](https://github.com/InnerOpen/marvin/commit/a2247e952dafcaba50879c9deeba2041c0eb1d18))

### Refactoring

- **maintenance**: Cleanup buttons become system scheduled tasks; heartbeat logs at DEBUG
  ([`c38f9fd`](https://github.com/InnerOpen/marvin/commit/c38f9fd1ff0c2e74cf8b82c8e61e00ef6a2ab6c8))

- **storage**: Slice 7 — remove the old off-site job and core's S3 provider
  ([`1326f42`](https://github.com/InnerOpen/marvin/commit/1326f4281694433417d32f032bbd71a9e9524061))

### Testing

- A workflow's read shape includes its source recipe
  ([`d77ae50`](https://github.com/InnerOpen/marvin/commit/d77ae506a2bf399dffe756181428eb56b064fbfd))


## v1.0.0-rc.244 (2026-10-10)

### Features

- **workflows**: A step can name a capability; the notification recipes work with Slack
  ([`d4c0fae`](https://github.com/InnerOpen/marvin/commit/d4c0faea0b65fe6f472f8948cd3a3a15bee4bbe8))

- **workflows**: A workflow remembers the recipe it was made from; the Library shows where each is
  in use
  ([`1dd24ff`](https://github.com/InnerOpen/marvin/commit/1dd24ff6cf9e3f69c701b343e5a8d0986e58a2c2))


## v1.0.0-rc.243 (2026-10-10)

### Bug Fixes

- **auth**: A session the API rejects goes to the login page too
  ([`547cba3`](https://github.com/InnerOpen/marvin/commit/547cba34413d680039d737b081748411055f48ce))

- **auth**: Find API and site-client tokens by lookup, not by checking every hash
  ([`496e8cf`](https://github.com/InnerOpen/marvin/commit/496e8cf2c957b00767cf6224a501d0b8a8c2b54e))

- **bubble**: The pose prompt says plainly which way to run; the fix for a sheet that didn't
  ([`c73051b`](https://github.com/InnerOpen/marvin/commit/c73051bf6d74724c41efd5867d0c11f95ea47c85))

### Chores

- **dev**: Character kit — Elvira, Fireball Mini, Mossy and Purple Bot
  ([`6648510`](https://github.com/InnerOpen/marvin/commit/66485101fcdace3c16deb458edc647c0fd5a0100))

### Features

- **bubble**: A hand-off's answer keeps the delegate's character; a drop into an edge stops the walk
  ([`3a9d44d`](https://github.com/InnerOpen/marvin/commit/3a9d44d9ae8c4b9b20bbef7a2f611b4701a14bbb))


## v1.0.0-rc.242 (2026-10-10)

### Bug Fixes

- **bubble**: /use shows an agent's character even if it was given one after the page loaded
  ([`4889238`](https://github.com/InnerOpen/marvin/commit/4889238e1e3982744ac6f3f65ce09b718f4c0a5c))


## v1.0.0-rc.241 (2026-10-10)

### Features

- **auth**: Throttle repeated failed sign-ins per account and per IP
  ([`64b2b78`](https://github.com/InnerOpen/marvin/commit/64b2b78867d0dabfbad63de7cd5214454afd39a7))

- **deploy**: Bake the site-wide plugins into the image
  ([`2be28e1`](https://github.com/InnerOpen/marvin/commit/2be28e1ed3220920d7e9b50e245547b1aae76083))


## v1.0.0-rc.240 (2026-10-09)

### Bug Fixes

- **bubble**: A character sheet's shaded background is background too
  ([`2ce91c4`](https://github.com/InnerOpen/marvin/commit/2ce91c4804ccd3139a28fc0ec5169df494623a46))


## v1.0.0-rc.239 (2026-10-09)

### Bug Fixes

- **auth**: An expired login goes to the login page, not "Unauthorized"
  ([`6c521e4`](https://github.com/InnerOpen/marvin/commit/6c521e4b7c684e92fced45e0ad269b842111ef53))

### Continuous Integration

- Log in to Docker Hub before pulling from it
  ([`f2708c2`](https://github.com/InnerOpen/marvin/commit/f2708c2c40a09a6e8e8b4659ffcd74c24caa48e3))


## v1.0.0-rc.238 (2026-10-09)

### Features

- **bubble**: Upload one character sheet, get the whole character
  ([`1a8de0b`](https://github.com/InnerOpen/marvin/commit/1a8de0b9410e8816cb7cb8f29b21cacf8d82ae89))


## v1.0.0-rc.237 (2026-10-09)

### Features

- **dev**: Character kit names each pack's zip after the character
  ([`b0697b4`](https://github.com/InnerOpen/marvin/commit/b0697b4d89f2364f67203d2845e86c7f9755f2ad))


## v1.0.0-rc.236 (2026-10-09)

### Features

- **dev**: Character kit picks each character's background and attaches a layout guide
  ([`7523c6e`](https://github.com/InnerOpen/marvin/commit/7523c6e16a9c1596306c31df27991366bc21c222))


## v1.0.0-rc.235 (2026-10-09)

### Documentation

- **dev**: Keep ChatGPT's Create Pet skill as a character-kit reference
  ([`953ce17`](https://github.com/InnerOpen/marvin/commit/953ce1793b8122d053e213cfe947457ae1131b26))

### Features

- **dev**: Character kit converts ChatGPT pet sprite sheets into packs
  ([`21fc1a4`](https://github.com/InnerOpen/marvin/commit/21fc1a495446e0c901fc0cdafd824dd1f56acbba))


## v1.0.0-rc.234 (2026-10-09)

### Bug Fixes

- **dev**: Character kit keys the background by its real colour, keeping reds and purples
  ([`19f8059`](https://github.com/InnerOpen/marvin/commit/19f805999a83681a0bcc56fe32d014ba1558ea1a))


## v1.0.0-rc.233 (2026-10-09)

### Bug Fixes

- **dev**: Character kit cuts a sheet of big, close poses into all 16
  ([`ad49c7b`](https://github.com/InnerOpen/marvin/commit/ad49c7be8cf5512415c8e4786b03868f72f1bc92))


## v1.0.0-rc.232 (2026-10-09)

### Features

- **dev**: Character kit designs a new character from its description
  ([`f41949c`](https://github.com/InnerOpen/marvin/commit/f41949c56fe334e864310cbaa55396a3ce7a997d))


## v1.0.0-rc.231 (2026-10-09)

### Features

- **dev**: Character kit warns when a pose is cut off, and keeps tilts and jumps in frame
  ([`24083ff`](https://github.com/InnerOpen/marvin/commit/24083ff4ae3b152882a5bd8a6315a2e91a2825c4))


## v1.0.0-rc.230 (2026-10-09)

### Bug Fixes

- **dev**: Character kit side peeks fit any body shape
  ([`9236789`](https://github.com/InnerOpen/marvin/commit/923678957588fc097dcde5d19c54686380f89713))


## v1.0.0-rc.229 (2026-10-09)

### Features

- **dev**: Character kit — a bubble character's whole pack from one pose sheet
  ([`40cb860`](https://github.com/InnerOpen/marvin/commit/40cb8608bd5fc240fc30c1121b13d7ea642aa456))


## v1.0.0-rc.228 (2026-10-09)

### Bug Fixes

- **bubble**: The tab comes back only once a peek has slid all the way in
  ([`d1fcbf4`](https://github.com/InnerOpen/marvin/commit/d1fcbf421edd8863b70fcc4e4b8ea8897a621b55))


## v1.0.0-rc.227 (2026-10-09)

### Bug Fixes

- **bubble**: A peek lines up the drawn ledge with the screen edge
  ([`2584c10`](https://github.com/InnerOpen/marvin/commit/2584c10846c924c0b438b0642a3b9b3218a814a6))

### Features

- **bubble**: Retire the plain peek; the edge peeks are Peek left / right / top / bottom
  ([`be3f0d6`](https://github.com/InnerOpen/marvin/commit/be3f0d6a5eed832687a6266a81b07fdc97e28878))


## v1.0.0-rc.226 (2026-10-09)

### Features

- **bubble**: A peek per edge, and the whole character comes out
  ([`09a8882`](https://github.com/InnerOpen/marvin/commit/09a8882760997a29d9a243b5809ef704eab22bcb))


## v1.0.0-rc.225 (2026-10-09)

### Bug Fixes

- **backup**: An asset deleted during a run is skipped, not a failure
  ([`3adb093`](https://github.com/InnerOpen/marvin/commit/3adb093b9a47f31a3d78c555d61c48c3818513be))

### Documentation

- Workflow Library in the app (phase 2)
  ([`2edc2f2`](https://github.com/InnerOpen/marvin/commit/2edc2f24235316cb61face03520e015211259362))

### Features

- **automation**: Library page
  ([`9b2f685`](https://github.com/InnerOpen/marvin/commit/9b2f685e22a78134f30da3ba23ef63ebc90284d5))

- **automations**: Workflow library endpoints
  ([`5ea7b26`](https://github.com/InnerOpen/marvin/commit/5ea7b263601ec3b8a5510a29177c7e178e296f17))

- **bubble**: BUBBLE_PEEK_SECONDS sets how often a tucked bubble peeks
  ([`f62549d`](https://github.com/InnerOpen/marvin/commit/f62549d17fe60d105c1184829b313f14217055b6))

- **workflows**: Start from a recipe
  ([`aa79cda`](https://github.com/InnerOpen/marvin/commit/aa79cda78c6d2ee891d114d3a9cdd01d30979192))


## v1.0.0-rc.224 (2026-10-09)

### Bug Fixes

- **email**: Platform mail falls back to the platform workspace's SMTP profile
  ([`48a44a5`](https://github.com/InnerOpen/marvin/commit/48a44a52114a097d1b845adb81164cd1bcbca55c))


## v1.0.0-rc.223 (2026-10-09)

### Features

- **bubble**: Pressing a tucked bubble's tab pulls it out under your finger
  ([`a347202`](https://github.com/InnerOpen/marvin/commit/a347202ef679382c98cc77d8d36b28e53f943322))


## v1.0.0-rc.222 (2026-10-09)

### Bug Fixes

- **bubble**: A tucked bubble shows a tab you can see, and doesn't slide across on reload
  ([`42cb589`](https://github.com/InnerOpen/marvin/commit/42cb589d40ea9103f62364d02e767531ffd5998b))


## v1.0.0-rc.221 (2026-10-09)

### Features

- **bubble**: A tucked bubble peeks out now and then
  ([`caccef7`](https://github.com/InnerOpen/marvin/commit/caccef7060122523ba94f7f9166bb720a9db26fe))


## v1.0.0-rc.220 (2026-10-09)

### Features

- **bubble**: Tuck the bubble into a screen edge, and keep it out of the way while scrolling
  ([`5a6b4f0`](https://github.com/InnerOpen/marvin/commit/5a6b4f0cf949779eb80acf38110f8cea346cc5e2))


## v1.0.0-rc.219 (2026-10-09)

### Bug Fixes

- **assets**: The image cropper works with a finger and fits a phone
  ([`ce86ee1`](https://github.com/InnerOpen/marvin/commit/ce86ee1028654676a318daee09e9582181cc010a))


## v1.0.0-rc.218 (2026-10-09)

### Bug Fixes

- **publish**: An entry's assets and resources come in placement order
  ([`0e97378`](https://github.com/InnerOpen/marvin/commit/0e97378465199e6d69373085746846bd54c3f14b))


## v1.0.0-rc.217 (2026-10-08)

### Bug Fixes

- **webhooks**: No Generate key for senders that issue their own, and replace an existing secret on
  ask
  ([`a3605ec`](https://github.com/InnerOpen/marvin/commit/a3605ecbf01c8fe41c730821956bf5aaf4e251d8))


## v1.0.0-rc.216 (2026-10-08)

### Features

- **assets**: Ask files live apart from the Assets library
  ([`53efc4b`](https://github.com/InnerOpen/marvin/commit/53efc4beeb812e825908caa2994dc7857b6e7880))

- **pwa**: The app icon counts waiting approvals, and a notification opens in its workspace
  ([`2128b1b`](https://github.com/InnerOpen/marvin/commit/2128b1b3c773b9de673a2e35823ad645046b3a59))

- **pwa**: Uploads that fail offline wait and send when the connection is back
  ([`8d0639d`](https://github.com/InnerOpen/marvin/commit/8d0639de2402cb31813b64dfed8c47e345ce7d86))

### Refactoring

- **ai**: OpenAI and Azure OpenAI come only from the marvin-ai-openai plugin
  ([`d15c0d8`](https://github.com/InnerOpen/marvin/commit/d15c0d84f39be70aee54d4d12fff128ae311eb84))


## v1.0.0-rc.215 (2026-10-08)

### Bug Fixes

- **bubble**: Sending while listening clears the input for good
  ([`bb28b64`](https://github.com/InnerOpen/marvin/commit/bb28b642155f9cde69e7cfbea8f931fdb271f589))


## v1.0.0-rc.214 (2026-10-08)

### Bug Fixes

- **ai**: Look at attached files before answering about them, and know they are already assets
  ([`feb13c5`](https://github.com/InnerOpen/marvin/commit/feb13c51cf1863670e90337601810cd2013f84f8))

- **bubble**: Speak keeps listening until you stop it
  ([`210b55c`](https://github.com/InnerOpen/marvin/commit/210b55c4dd745903fee28331500ed09879a2edbf))


## v1.0.0-rc.213 (2026-10-08)

### Features

- **bubble**: Attach files and dictate in the bubble
  ([`d3c3210`](https://github.com/InnerOpen/marvin/commit/d3c3210e74eb7a8b146f47cac64b679555b7ca5b))


## v1.0.0-rc.212 (2026-10-08)

### Features

- **ai**: Files attached to an agent question, and read_attachment
  ([`ec12810`](https://github.com/InnerOpen/marvin/commit/ec12810ffc65cdd5498650d2fe0cd775e9b2963b))


## v1.0.0-rc.211 (2026-10-08)

### Bug Fixes

- **deploy**: A release commit doesn't supersede the push that cut it
  ([`973928d`](https://github.com/InnerOpen/marvin/commit/973928d87f440f4bbb458a22fb9a8097996dd158))

- **secrets**: Store a secret in the caller's transaction
  ([`bd59f88`](https://github.com/InnerOpen/marvin/commit/bd59f88010c8893eda51a19683fda3116ac5eaa2))


## v1.0.0-rc.210 (2026-10-08)

### Features

- **ai**: Production uses the marvin-ai-openai plugin for OpenAI and Azure
  ([`175dbfb`](https://github.com/InnerOpen/marvin/commit/175dbfbbbf97adfbf9da8109fb707f912e37b3cc))


## v1.0.0-rc.209 (2026-10-08)

### Bug Fixes

- **frontend**: Email template Save buttons were invisible
  ([`3ccd959`](https://github.com/InnerOpen/marvin/commit/3ccd959777e4d63990bb9dde60b90f1d3ef685a6))

- **frontend**: Email templates and SMTP fit a phone
  ([`b5cf152`](https://github.com/InnerOpen/marvin/commit/b5cf1529280b42d1b02e2dc0ed95438271147793))

- **frontend**: Phone-wide fixes for title rows, page modals and iOS field zoom
  ([`0d00957`](https://github.com/InnerOpen/marvin/commit/0d00957e203de9ecac2118c9dcdbb6823d0d91f0))

- **frontend**: Submission protection fits a phone
  ([`de46b27`](https://github.com/InnerOpen/marvin/commit/de46b2712272e772f9233cc5ce6623a3bcb1f92e))

- **frontend**: The rest of Settings and Automation fit a phone
  ([`293d1db`](https://github.com/InnerOpen/marvin/commit/293d1db0242b09a1eadcaea653ddd69bd61945a9))

### Documentation

- Getting platform alerts outside Marvin
  ([`58a0ae0`](https://github.com/InnerOpen/marvin/commit/58a0ae0bc7b41efbf94440c28942fc4a00b1f97b))


## v1.0.0-rc.208 (2026-10-07)

### Bug Fixes

- **register**: Logged-in visitors go to the workspace (real cookie name)
  ([`d7e67ee`](https://github.com/InnerOpen/marvin/commit/d7e67eef454dfc89474ba88629ec665252da4163))

### Documentation

- Postgres runbook (dev env, CNPG backups/PITR, copy tool, cutover)
  ([`4e0a7c7`](https://github.com/InnerOpen/marvin/commit/4e0a7c7704ebc9f12b3680de32a498f2952c1b14))

### Testing

- The alias migration check reads one row each, no ORDER BY on JSON
  ([`64cb622`](https://github.com/InnerOpen/marvin/commit/64cb6228504e826dfb401c015e676df0a92e95f0))


## v1.0.0-rc.207 (2026-10-06)

### Bug Fixes

- **entries**: Publishing an entry into a smart collection could 500
  ([`9b81965`](https://github.com/InnerOpen/marvin/commit/9b81965a04b9d49b48c7700253bde515b196a4b4))


## v1.0.0-rc.206 (2026-10-06)

### Documentation

- Platform events aren't offered on the workspace side
  ([`5c72319`](https://github.com/InnerOpen/marvin/commit/5c72319c8ded3ec10eae663506d00d463b262620))

- The Events page's Sent by / What happens / Recent (manual + what's new)
  ([`ccc4973`](https://github.com/InnerOpen/marvin/commit/ccc497374ce894bf59f12d17288f67cead144828))

- **tasks**: Events hub slice 4 review
  ([`0edbb8f`](https://github.com/InnerOpen/marvin/commit/0edbb8fa03655b8c18780793d9087e458ec67b9a))

- **tasks**: Events hub slice 4 review — platform events hidden
  ([`2a4846c`](https://github.com/InnerOpen/marvin/commit/2a4846cf26d72e7b4f0a32f729eba9bec7d0089c))

### Features

- **events**: Event page shows what sends it, what happens and when
  ([`76bf30c`](https://github.com/InnerOpen/marvin/commit/76bf30ce28f712cf05f41614f3de0d86032f4a88))

- **events**: The workspace side leaves platform events out
  ([`26672d8`](https://github.com/InnerOpen/marvin/commit/26672d8b134939568c58bdaeb10557ebb86901cd))


## v1.0.0-rc.205 (2026-10-06)

### Documentation

- **tasks**: Events hub slice 3 review
  ([`cee7272`](https://github.com/InnerOpen/marvin/commit/cee7272987f5c65ff2a1932a7854f89cb1e1d984))

### Features

- **events**: One lookup for what sends an event and what reacts to it
  ([`e226a10`](https://github.com/InnerOpen/marvin/commit/e226a10a1667ee327d4c37659b5da0a043d66e67))


## v1.0.0-rc.204 (2026-10-06)

### Documentation

- **tasks**: Events hub slice 2 review; two more sent_by senders
  ([`aa86762`](https://github.com/InnerOpen/marvin/commit/aa86762f51d02f7c04c05fa74309c06f7cc7eb2b))

### Features

- **events**: Catalogue every sent event; one internal-events set
  ([`28ba107`](https://github.com/InnerOpen/marvin/commit/28ba107967386f018a5d8dcc0c6aff0a8f03b8b8))

- **events**: One catalog — triggerable, emittable, sent_by, leads_to
  ([`9adf871`](https://github.com/InnerOpen/marvin/commit/9adf871d49ef9df173dbda0dce6ef35f9eb70cef))

### Testing

- **events**: Drop the retired side-list snapshots
  ([`a7b6e80`](https://github.com/InnerOpen/marvin/commit/a7b6e809e1411b57c5dcdf9e62fa58aaf95e5a69))


## v1.0.0-rc.203 (2026-10-06)

### Bug Fixes

- **db**: Workflow-type webhooks failed to save on Postgres
  ([`29b5c04`](https://github.com/InnerOpen/marvin/commit/29b5c040ae8d2f15760680616c14697b6be788bb))

### Documentation

- Breadcrumb trail on admin and settings pages (manual + what's new)
  ([`3cc9bb8`](https://github.com/InnerOpen/marvin/commit/3cc9bb8159ee0c3ad0aa3029d06bac1898ed8b4f))


## v1.0.0-rc.202 (2026-10-06)

### Bug Fixes

- **frontend**: Admin Events cards hide closed payload rows on a phone
  ([`106e4ff`](https://github.com/InnerOpen/marvin/commit/106e4ffa4d56404ded683dde1167c9e42658a9da))

### Documentation

- Platform events and the admin Events page (manual + what's new)
  ([`b4254c1`](https://github.com/InnerOpen/marvin/commit/b4254c15e634fddb3e827a365f167822e79dee4b))

### Features

- **events**: Platform events leave the workspace Event Log for an admin API
  ([`0db17f4`](https://github.com/InnerOpen/marvin/commit/0db17f482ac7b116840dc43c8602ef488ac3ec0f))

- **frontend**: Admin Events page for platform events
  ([`ca641d9`](https://github.com/InnerOpen/marvin/commit/ca641d9ec7b663faf5ca5af69163f488b41d5d9b))


## v1.0.0-rc.201 (2026-10-06)

### Bug Fixes

- **events**: An audit settings change doesn't queue a site rebuild
  ([`caae4a1`](https://github.com/InnerOpen/marvin/commit/caae4a1084a38a45e349951befe09ec762587119))

### Documentation

- Event Log audit coverage (manual + what's new)
  ([`0e2c0da`](https://github.com/InnerOpen/marvin/commit/0e2c0da1c094f1b311d315dfcc8e427f68fe418c))

### Features

- **events**: Per-workspace audit toggles for the Event Log
  ([`91ede63`](https://github.com/InnerOpen/marvin/commit/91ede63567b6b00768bf20cbbd676b3fad86da66))

- **frontend**: Event Log audit coverage reads and edits the API
  ([`7e10b7d`](https://github.com/InnerOpen/marvin/commit/7e10b7d73a2037c0507432129404667ef45dc703))


## v1.0.0-rc.200 (2026-10-06)

### Bug Fixes

- **tags**: Attaching a tag to an asset or resource returned 500
  ([`7cd788d`](https://github.com/InnerOpen/marvin/commit/7cd788d5d6b9d8e30b4ab1e1f0137cad3d53bb29))


## v1.0.0-rc.199 (2026-10-05)

### Continuous Integration

- Cache pip downloads in the cli, sdk and release workflows
  ([`8d59a18`](https://github.com/InnerOpen/marvin/commit/8d59a1844a2b5b15921e8cc687095f704a76c78a))

- Optional self-hosted runner for push builds (CI_RUNNER)
  ([`5a1bf65`](https://github.com/InnerOpen/marvin/commit/5a1bf657354ef8d657fd930bac7b9360e3e799ad))

- Publish test results with the composite (non-Docker) action
  ([`cb75109`](https://github.com/InnerOpen/marvin/commit/cb751097d6930e587112adc66e80d21d5dc45723))

- Run the PostgreSQL job on GitHub-hosted runners only
  ([`38d6550`](https://github.com/InnerOpen/marvin/commit/38d65504963ca007683ac059e7345a1207bdf583))

### Documentation

- Media embeds (manual, what's new, publishing API); tasks: tick the core plan
  ([`2dee73d`](https://github.com/InnerOpen/marvin/commit/2dee73de9e83bc0c7794d024d8837cfd00be8e09))

- **manual**: Alerts & health page; tasks: tick the plan
  ([`26cd40c`](https://github.com/InnerOpen/marvin/commit/26cd40c8f16396892a24841724edeaf7a8abe510))

### Features

- **publish**: ?expand=full returns full entries from the list endpoints
  ([`2a9d833`](https://github.com/InnerOpen/marvin/commit/2a9d83334de32917fa4a6b80ea8f666d150673c4))


## v1.0.0-rc.198 (2026-10-05)

### Bug Fixes

- **deps**: Declare requests; install the integration SDK in the SDK gate
  ([`ca2b238`](https://github.com/InnerOpen/marvin/commit/ca2b238e7a4f904c699bb5a31b4d012a2fa1b1b6))

### Documentation

- **manual**: Catch up with rc.197: n8n, integration errors, roles
  ([`b6f5349`](https://github.com/InnerOpen/marvin/commit/b6f53499cafb6ab7ddeec83e58fd1ca4b74952a6))

- **manual**: What's new through rc.197
  ([`18d826e`](https://github.com/InnerOpen/marvin/commit/18d826ee99c85edc20a985e463844aaee9502a3c))


## v1.0.0-rc.197 (2026-10-04)

### Bug Fixes

- Logos and admin-gate tests without the integration SDK
  ([`cb178f7`](https://github.com/InnerOpen/marvin/commit/cb178f7b1a80d012ceba4be18d5b268abfec614a))

### Chores

- **deploy**: Install the n8n integration on iwobble
  ([`172aad4`](https://github.com/InnerOpen/marvin/commit/172aad44ec0e6156f16602a03cdd7755204b8dd8))

### Documentation

- Behaviour changes and retry-chain rules for integration errors
  ([`2807314`](https://github.com/InnerOpen/marvin/commit/28073148480dd80029fc0eb9494a05d34b4a99fe))


## v1.0.0-rc.196 (2026-10-04)

### Features

- **admin**: The entry page says why an entry is waiting for review
  ([`41137fc`](https://github.com/InnerOpen/marvin/commit/41137fc9c950aad5eecf1ac7dd1a724c46e22f59))


## v1.0.0-rc.195 (2026-10-04)

### Features

- **admin**: Voice field on the New entry type page
  ([`1e23da7`](https://github.com/InnerOpen/marvin/commit/1e23da76c4e644bdd3aa54ac819cf5d3fd115b0a))

- **ai**: Preview the prompt of an agent before it is saved
  ([`f0241f4`](https://github.com/InnerOpen/marvin/commit/f0241f4181645dffd63c795fa854137792af4e01))


## v1.0.0-rc.194 (2026-10-04)

### Bug Fixes

- **admin**: Disable View on site until the entry is published
  ([`6ff8b4a`](https://github.com/InnerOpen/marvin/commit/6ff8b4a89a262f019ed93ebebc66e6cb5b1a05c2))

- **ai**: Say Character and Voice where the labels still paired voice/tone
  ([`54bc598`](https://github.com/InnerOpen/marvin/commit/54bc5987a8fc74a63b418def810a0eeda42e7251))

### Documentation

- **manual**: Prompt previews and the Character / Voice labels
  ([`c7f091d`](https://github.com/InnerOpen/marvin/commit/c7f091d15626a6e9e4f952c9462f4b1f1995752e))

### Features

- **admin**: Prompt previews on tone rows, the Character and agents
  ([`800612b`](https://github.com/InnerOpen/marvin/commit/800612b1c1a758016342b8187c2b32bad7866874))

- **ai**: Preview an agent's system prompt and the Character with the default tone
  ([`d862782`](https://github.com/InnerOpen/marvin/commit/d862782ed12b8e57ad1f899e235d82285bfbd7ec))


## v1.0.0-rc.193 (2026-10-04)

### Features

- **dashboard**: Count Needs review and show why on the Review Queue's cards
  ([`3ebd320`](https://github.com/InnerOpen/marvin/commit/3ebd320c59ba55350560872c40b17eea288d017f))

- **workflows**: On_failure steps, a request_review entry op and coded integration errors
  ([`79fa3d0`](https://github.com/InnerOpen/marvin/commit/79fa3d07b7ff248e7af4c38c1228bd623a28ca72))


## v1.0.0-rc.192 (2026-10-04)

### Bug Fixes

- **admin**: Keep the Ask page's hidden attachment chip hidden
  ([`11ed7c9`](https://github.com/InnerOpen/marvin/commit/11ed7c95008a32fdbcfc7542f0148a805da7f774))

### Features

- **admin**: Collapse the entry editor's raw JSON fields by default
  ([`92c3ad3`](https://github.com/InnerOpen/marvin/commit/92c3ad3c4ffe69a0def5d634d9be6f694037cdf1))

- **ai**: Label the persona as Character and let the tone win on delivery
  ([`1b1a78a`](https://github.com/InnerOpen/marvin/commit/1b1a78ac73354ab10fa9b3edad6d306d74e47875))


## v1.0.0-rc.191 (2026-10-04)

### Bug Fixes

- **publishing**: Don't queue site rebuilds for changes no site can see
  ([`e592989`](https://github.com/InnerOpen/marvin/commit/e5929899c992bf7de1785d530b02e43bb09f00c5))


## v1.0.0-rc.190 (2026-10-04)

### Bug Fixes

- **ai**: End, refuse or re-check a carried-up ask where resuming could go wrong
  ([`a6dd2a3`](https://github.com/InnerOpen/marvin/commit/a6dd2a37161e67062bab4d838a68fbf07a8019a6))

### Documentation

- A specialist's ask carried up to Marvin; tasks: C2 checklist and review
  ([`329ac29`](https://github.com/InnerOpen/marvin/commit/329ac293d9df7be088bfea02dd40ea97520b8bc0))

### Features

- **admin**: Approve a specialist's ask from the Ask page, the bubble or a toast
  ([`2595766`](https://github.com/InnerOpen/marvin/commit/25957666e0a164a2f51fbaa6c97ba6bcb178a668))

- **ai**: Bubble tool list follows Marvin's matrix; drafts use the run's tone
  ([`04fc46f`](https://github.com/InnerOpen/marvin/commit/04fc46f44e908e486c55bfa1187afeb97282a1f2))

- **ai**: Carry a specialist's ask up to Marvin
  ([`15d9e55`](https://github.com/InnerOpen/marvin/commit/15d9e556c273d49bc18e42b22201ee1aaa29e12a))

### Testing

- **admin**: Resume source checks follow the bubble's approval card
  ([`829ab14`](https://github.com/InnerOpen/marvin/commit/829ab14a33f35619a14d1e0cd409835192f38a05))


## v1.0.0-rc.189 (2026-10-04)

### Refactoring

- Remove the built-in Apprise notifier — use the Apprise integration
  ([`9ab9f40`](https://github.com/InnerOpen/marvin/commit/9ab9f40bbe6996764d8cc82cbcc1b436e069eb2e))

### Breaking Changes

- The /api/group/notifications and /api/event/options endpoints, the APPRISE_ENABLED / APPRISE_URL
  settings and the about endpoints' Apprise fields are gone. Send notifications by connecting the
  Apprise integration's notify action to events instead.


## v1.0.0-rc.188 (2026-10-04)

### Documentation

- Custom tones in the manual; tasks: tones checklist done
  ([`d3746ad`](https://github.com/InnerOpen/marvin/commit/d3746ad02c7b4fb9b46ff90c198949b142baca85))

- **manual**: Admin pages by their grouped sidebar names
  ([`fe10353`](https://github.com/InnerOpen/marvin/commit/fe10353c93be4dfa6a1211e0442d451232a3ae31))

- **manual**: Agents and Ask through rc.185
  ([`b245e59`](https://github.com/InnerOpen/marvin/commit/b245e59fd8a85b3f50ea0aed09388b2dd96fac48))

- **manual**: API clients, token dialogs and admin-only secrets
  ([`630417c`](https://github.com/InnerOpen/marvin/commit/630417c83b480a3fd676c84c87a477a6af95db56))

- **manual**: Operations and the admin shell through rc.186
  ([`c835b71`](https://github.com/InnerOpen/marvin/commit/c835b713581848d5f3b8932a547891343326ac1b))

- **manual**: Plugins page, HTTP patch and the Buttondown provider
  ([`64ea2d7`](https://github.com/InnerOpen/marvin/commit/64ea2d7a322c4438dc1ffdd8febe75862f1b78bf))

- **manual**: Scheduled publishing, private collections and client permissions
  ([`8291b8e`](https://github.com/InnerOpen/marvin/commit/8291b8ee6327683de1c8bef02c10100d4bf51f1b))

- **manual**: What's new and workflows provenance through rc.186
  ([`3dd9964`](https://github.com/InnerOpen/marvin/commit/3dd99642a47265d4c39ca208847449a6b8d3eaea))

### Features

- **admin**: Tones editor, tone pickers and the bubble's /tone
  ([`2d7ebc9`](https://github.com/InnerOpen/marvin/commit/2d7ebc9625ff60eb31f380b2131d9efe9b592607))

- **ai**: Custom tones per workspace
  ([`9168bc9`](https://github.com/InnerOpen/marvin/commit/9168bc94351aa735193a4fa746030d9e8f419d65))


## v1.0.0-rc.187 (2026-10-04)

### Bug Fixes

- **ai**: Bind the bubble's Marvin through Marvin's permission matrix
  ([`f040df4`](https://github.com/InnerOpen/marvin/commit/f040df4906ca9787e0078086ad42c0fe0918111b))


## v1.0.0-rc.186 (2026-10-04)

### Features

- **collections**: "Visible to sites" toggle for a collection's is_public flag
  ([`af9e609`](https://github.com/InnerOpen/marvin/commit/af9e609ad4c5cf956555042c3fdb4ae9d3334b65))


## v1.0.0-rc.185 (2026-10-04)

### Features

- **ai**: Separate invocation-source toggles for the bubble and the Ask page
  ([`30e2aa9`](https://github.com/InnerOpen/marvin/commit/30e2aa9a2a9a36ce93ca15ea710db096657b2a4f))


## v1.0.0-rc.184 (2026-10-04)

### Bug Fixes

- **frontend**: The Ask bubble hides when "Ask {assistant}" is switched off
  ([`24b778e`](https://github.com/InnerOpen/marvin/commit/24b778e36b44af3fa534babaa77ed2a1e8b67525))


## v1.0.0-rc.183 (2026-10-04)

### Bug Fixes

- **frontend**: Remove the unused API-client create route that put the token in a URL
  ([`4910f83`](https://github.com/InnerOpen/marvin/commit/4910f83216e1629a5ddd4d26474cfa9e5652c9d5))

- **frontend**: Show new personal API tokens once in a dialog, never in the URL
  ([`7a3998a`](https://github.com/InnerOpen/marvin/commit/7a3998ae175c820739c09015fc4a46869d5f44a3))


## v1.0.0-rc.182 (2026-10-04)

### Bug Fixes

- **api**: Make API client routes workspace-admin only
  ([`4a60bb5`](https://github.com/InnerOpen/marvin/commit/4a60bb5e6ca47bdf7167b44529b4f9508dad2ad8))

- **api**: Only workspace admins may create, change or delete secrets
  ([`fddde25`](https://github.com/InnerOpen/marvin/commit/fddde25f5d46987d542979dccdb8c295747b1bdd))

### Features

- **integrations**: PATCH on the provider HTTP helper
  ([`51bf42a`](https://github.com/InnerOpen/marvin/commit/51bf42ab2e806ecb333809c2300908a2654658b7))


## v1.0.0-rc.181 (2026-10-04)

### Features

- **api**: Refuse to delete an enabled API client
  ([`c09fc5e`](https://github.com/InnerOpen/marvin/commit/c09fc5e4513003f528e3fd8a828d241837d8df60))

- **frontend**: Edit and delete API clients, offer form-submit permissions
  ([`ff6417d`](https://github.com/InnerOpen/marvin/commit/ff6417d732cae1d2f8e2fa417586f254750f57a8))


## v1.0.0-rc.180 (2026-10-04)

### Features

- **ai**: Bubble lines written from the workspace persona
  ([`0d9b662`](https://github.com/InnerOpen/marvin/commit/0d9b662c97e6448ec70e390dbc7f76cdc2837481))

- **frontend**: The bubble speaks the workspace's own lines; AI settings edit them
  ([`7741350`](https://github.com/InnerOpen/marvin/commit/7741350876620f7b7805406b9f8af474261b59e9))


## v1.0.0-rc.179 (2026-10-04)

### Features

- **workflows**: Entry step if_none: skip, and ${entry.url}
  ([`2b462fc`](https://github.com/InnerOpen/marvin/commit/2b462fcce36ea8661197ea4516c7bfeb0c8bd4d4))


## v1.0.0-rc.178 (2026-10-04)

### Chores

- **chart**: Install the Buttondown integration on iwobble
  ([`c86844a`](https://github.com/InnerOpen/marvin/commit/c86844a4058212b28cd784a2f98f2dd4faf181ea))

### Features

- **events**: Every event names its subject; a workflow run names its trigger and steps
  ([`d04dc84`](https://github.com/InnerOpen/marvin/commit/d04dc842901b5deff5867c133ff183c565051b1b))

- **frontend**: The event log links each event's subject and a workflow run's trigger
  ([`a45159e`](https://github.com/InnerOpen/marvin/commit/a45159e542c2a1ae4a9e974e776ae91e312227bd))

### Testing

- **events**: The fake session answers the ${site.url} preferences query
  ([`d45253b`](https://github.com/InnerOpen/marvin/commit/d45253b02348417a03a91d25aaaa65f9d8fc82df))


## v1.0.0-rc.177 (2026-10-04)

### Features

- **workflows**: ${site.url} in the workflow context
  ([`eba285b`](https://github.com/InnerOpen/marvin/commit/eba285b471a0b86ff9c3f9c55d62a94712fb8932))


## v1.0.0-rc.176 (2026-10-04)

### Features

- **frontend**: Refused saves show why and keep your edits; a waiting scheduled publish is shown
  ([`69a0884`](https://github.com/InnerOpen/marvin/commit/69a088418ff027176cb70279bff7f9515b8107da))

- **scheduler**: A held-back scheduled publish says why, once, and can wait for approval
  ([`28e62c8`](https://github.com/InnerOpen/marvin/commit/28e62c898b5e3ef994ef9e714679e5474a9076bf))


## v1.0.0-rc.175 (2026-10-04)

### Bug Fixes

- **scheduler**: Expiry consumes the expiration date, and a passed one blocks publishing
  ([`b2952b3`](https://github.com/InnerOpen/marvin/commit/b2952b3669869f50245e68d9dc6d0f988a0b9651))

### Features

- **frontend**: The entry editor flags an expiration date that has passed
  ([`890afc3`](https://github.com/InnerOpen/marvin/commit/890afc379da64bee8ff27da747133ccaf2da2783))


## v1.0.0-rc.174 (2026-10-04)

### Bug Fixes

- **frontend**: Activity toasts stay on screen on a phone
  ([`3f1e457`](https://github.com/InnerOpen/marvin/commit/3f1e4578ff05f1cad266cb3fa3a61db211c9c297))

- **frontend**: The Marvin bubble rests bottom-left and stays put on screen
  ([`697d301`](https://github.com/InnerOpen/marvin/commit/697d301c35d4146192ba7e252090ef0b3321499a))

### Features

- **frontend**: The admin fits a phone — sidebar drawer, stacked layouts, no sideways scroll
  ([`7fdae61`](https://github.com/InnerOpen/marvin/commit/7fdae619918abcdf46fd2ac0bb103de7f79d84d0))


## v1.0.0-rc.173 (2026-10-04)

### Features

- **frontend**: Workflow dry run picks its sample event and shows the condition checklist
  ([`eb0a510`](https://github.com/InnerOpen/marvin/commit/eb0a510a8fb4ea6156730ebfc7cec5d1e3c67519))

- **workflows**: Dry-run an event-triggered workflow against a sample event
  ([`68ca709`](https://github.com/InnerOpen/marvin/commit/68ca7095db4bc686fa1827bc552782bc13db1d90))


## v1.0.0-rc.172 (2026-10-04)

### Features

- **entries**: A page URL pattern per entry type gives each entry its site URL
  ([`f11a641`](https://github.com/InnerOpen/marvin/commit/f11a6412674ba29036bfd8cb38ad738655840eb4))

- **entries**: Placeholder links like [title](#) block publishing
  ([`153d9da`](https://github.com/InnerOpen/marvin/commit/153d9daba1cc9486831d4158ebce423c0456a874))


## v1.0.0-rc.171 (2026-10-03)

### Bug Fixes

- **scheduler**: Scheduled publish and expiry fire the same entry events as a manual change
  ([`d593ea9`](https://github.com/InnerOpen/marvin/commit/d593ea980b25c0dd3826390a552c71f963c6e9e5))


## v1.0.0-rc.170 (2026-10-03)

### Bug Fixes

- **entries**: Publishing by any route clears the schedule
  ([`02ce26a`](https://github.com/InnerOpen/marvin/commit/02ce26a2ca53e0074967cd5a6b9397f65da2c53b))

### Features

- **scheduler**: Scheduled publish and expiry run out of the box as system tasks
  ([`0e3725d`](https://github.com/InnerOpen/marvin/commit/0e3725d9cde63af6e6452b50580772c3aa6b90ea))


## v1.0.0-rc.169 (2026-10-03)

### Features

- **collections**: A rule builder and Run Query on the smart-collection form
  ([`07601ea`](https://github.com/InnerOpen/marvin/commit/07601ea70c3fc673d9178d5e3543c58c89c3cc45))

- **collections**: Field conditions in smart rules, and a preview of unsaved rules
  ([`62edd8c`](https://github.com/InnerOpen/marvin/commit/62edd8cca2a50ab8e133fe424e82f82b9900f9dc))


## v1.0.0-rc.168 (2026-10-03)

### Bug Fixes

- **entries**: Scheduled Publish and Expiration dates save, in the viewer's time zone
  ([`9e39a1b`](https://github.com/InnerOpen/marvin/commit/9e39a1b05936852e55c1b24047990ab7c90baeef))

- **scheduler**: Scheduled publish runs once and leaves archived entries alone
  ([`7d6aec2`](https://github.com/InnerOpen/marvin/commit/7d6aec2725a14e8f2b579737edcef0e2ecf88968))


## v1.0.0-rc.167 (2026-10-03)

### Features

- **frontend**: Attached images preview at the top of Entry Details
  ([`d9aec37`](https://github.com/InnerOpen/marvin/commit/d9aec3775e9ada0e858bcf74499cfd52c4b60689))


## v1.0.0-rc.166 (2026-10-03)

### Features

- **ai**: Search and read Marvin's own manual from agents (search_docs, read_doc)
  ([`47182a9`](https://github.com/InnerOpen/marvin/commit/47182a98e3bd3d32bcaa40c5e76cc46f17705375))


## v1.0.0-rc.165 (2026-10-03)

### Features

- **activity**: Queued-rebuild and running-workflow toasts that update in place
  ([`4bb6ed6`](https://github.com/InnerOpen/marvin/commit/4bb6ed6d3da2b5dcc698cd56cc4252f235fa7977))


## v1.0.0-rc.164 (2026-10-03)

### Bug Fixes

- **ui**: Dark mode applies before the first paint — no white flash
  ([`a00c97f`](https://github.com/InnerOpen/marvin/commit/a00c97fabaf3cf176a2c804f61de73e7cab4b43d))


## v1.0.0-rc.163 (2026-10-03)

### Chores

- **deploy**: The backend deploys with Recreate on iwobble
  ([`5762700`](https://github.com/InnerOpen/marvin/commit/57627009310c4fcb0eb811320a70b2332a79bb72))

### Features

- **ai**: The Ask page lists every agent's threads, hand-offs nested under their parent
  ([`c216b84`](https://github.com/InnerOpen/marvin/commit/c216b84e69d39043e54922e363e11220c1364db1))


## v1.0.0-rc.162 (2026-10-03)

### Bug Fixes

- **ai**: Big bulk writes ask first, tagging uses the images, restart-killed runs are marked,
  deploys drain
  ([`8dbc749`](https://github.com/InnerOpen/marvin/commit/8dbc749cbbf228fb197c88c71a44ca962d2c59b3))

- **ui**: The update banner shows on admin pages too
  ([`0ad5707`](https://github.com/InnerOpen/marvin/commit/0ad570706cf8c2d3e3e358fad3e697638d2deb08))


## v1.0.0-rc.161 (2026-10-03)

### Features

- **ui**: An agent's Character button opens its bubble character without Edit
  ([`6b82d98`](https://github.com/InnerOpen/marvin/commit/6b82d98fb82320feeae524e8b380d7f499073abc))


## v1.0.0-rc.160 (2026-10-03)

### Features

- **admin**: "What's new" list on the update banner
  ([`b9c022c`](https://github.com/InnerOpen/marvin/commit/b9c022c884c4c48a65e86b0df5abd3161a1f1eaf))

- **admin**: List the image's unreleased commits in "What's new"
  ([`315e0ce`](https://github.com/InnerOpen/marvin/commit/315e0ce99069e70ad013ee9fb48688879cb96cef))

- **ui**: An agent's bubble character sits in its Edit form, under Icon and Name
  ([`7e02d7c`](https://github.com/InnerOpen/marvin/commit/7e02d7c6e9c3091515a2bf5da0d737ac9e878b04))


## v1.0.0-rc.159 (2026-10-03)

### Bug Fixes

- **character**: Clear solid backgrounds from bubble-character images
  ([`4929ec5`](https://github.com/InnerOpen/marvin/commit/4929ec59564c8ba3e68eb777c31f02888f5c4db9))

### Features

- **admin**: Delete a character pack from its card, even one in use
  ([`f29fdbf`](https://github.com/InnerOpen/marvin/commit/f29fdbfe72cef571768581a0085c3ae9a7e591e0))


## v1.0.0-rc.158 (2026-10-03)

### Features

- **admin**: Group the admin nav, turn /admin into an overview, add a plugins page
  ([`dffdd86`](https://github.com/InnerOpen/marvin/commit/dffdd8682c5877d2a0207edef66ad28aa0ba6923))


## v1.0.0-rc.157 (2026-10-03)

### Documentation

- Publish the Marvin manual
  ([`888ba85`](https://github.com/InnerOpen/marvin/commit/888ba85da32a4008ff6df49fa52f30395a3d0fa2))

### Features

- **ui**: Pick a bubble character from cards, not a dropdown
  ([`27b56db`](https://github.com/InnerOpen/marvin/commit/27b56db49d4575d267df1f8eadfd3738410c5247))


## v1.0.0-rc.156 (2026-10-03)

### Bug Fixes

- **bubble**: Keep threads per workspace; recover from a 404'd thread
  ([`6bc32ec`](https://github.com/InnerOpen/marvin/commit/6bc32ecc0702a1a85d754029facdd2c086b57618))

### Features

- **ai**: Character library and per-agent bubble characters
  ([`c31228e`](https://github.com/InnerOpen/marvin/commit/c31228ecafdc03216956db4e7d4192f20ffb103a))


## v1.0.0-rc.155 (2026-10-03)

### Bug Fixes

- **events**: Webhook_triggered's catalog entry describes what it carries
  ([`b2d7ac9`](https://github.com/InnerOpen/marvin/commit/b2d7ac9f871fbce0ad2e07011c0f270bc81084e8))


## v1.0.0-rc.154 (2026-10-03)

### Features

- **publishing**: Site rebuild toast lists what changed
  ([`317c509`](https://github.com/InnerOpen/marvin/commit/317c50970b487d690fe81e5a1c2c7caedc9109d1))


## v1.0.0-rc.153 (2026-10-03)

### Features

- **ai**: Animated bubble character — one animation per bubble state
  ([`e5c3efc`](https://github.com/InnerOpen/marvin/commit/e5c3efcb8178364e1b85da39bdcab00170de8fba))


## v1.0.0-rc.152 (2026-10-03)

### Bug Fixes

- **automation**: Site build/deploy events are workflow triggers
  ([`a62d97f`](https://github.com/InnerOpen/marvin/commit/a62d97ff79d0656d6b1850bfb690ae04fa9aa1ed))


## v1.0.0-rc.151 (2026-10-03)

### Bug Fixes

- **events**: Site build/deploy events can trigger workflows and notifications
  ([`31b5266`](https://github.com/InnerOpen/marvin/commit/31b52661cc0ca3acb08a8bf5fc4d54036d14522b))


## v1.0.0-rc.150 (2026-10-03)

### Features

- **ai**: Bubble agent runs live in server threads and survive navigation
  ([`ef103f7`](https://github.com/InnerOpen/marvin/commit/ef103f72c6f140ecacd17455958e89b141096b5e))


## v1.0.0-rc.149 (2026-10-03)

### Bug Fixes

- **dashboard**: Count inbox and drafts apart in Needs Attention
  ([`1fc74f1`](https://github.com/InnerOpen/marvin/commit/1fc74f18e8ba9b1623b633150afe274153319351))

### Refactoring

- **ai**: Official OpenAI via the Responses API; no per-model rules
  ([`03a62bb`](https://github.com/InnerOpen/marvin/commit/03a62bb5fa253438342c440d46bb48d2011eddbc))


## v1.0.0-rc.148 (2026-10-03)

### Bug Fixes

- **ai**: Send tool calls through the Responses API when a model asks
  ([`f5a7a5e`](https://github.com/InnerOpen/marvin/commit/f5a7a5ed6aba64c4a11c76aa1c30088f099b256e))


## v1.0.0-rc.147 (2026-10-03)

### Bug Fixes

- **ai**: Learn which length/sampling parameters a model accepts
  ([`7d217ce`](https://github.com/InnerOpen/marvin/commit/7d217cec79f33c83ff933c954de070e7039221a3))


## v1.0.0-rc.146 (2026-10-03)

### Chores

- **deploy**: Install the Cloudflare Pages integration on iwobble
  ([`d721731`](https://github.com/InnerOpen/marvin/commit/d7217316ab07ffdb4c599e5a568b121c9ad805f7))

### Features

- **ai**: AI usage against limits, honest external sources, agent names in history
  ([`7871997`](https://github.com/InnerOpen/marvin/commit/787199766b297eaf293009df2e5b65092f43a284))


## v1.0.0-rc.145 (2026-10-03)

### Features

- **integrations**: {{SECRET}} references in integration action arguments
  ([`a9daeda`](https://github.com/InnerOpen/marvin/commit/a9daedaa80fa14d92abd15b38ce662dd2bd17391))


## v1.0.0-rc.144 (2026-10-03)

### Features

- Site build/deploy status from a host's webhook, as Marvin events and toasts
  ([`3ef20e4`](https://github.com/InnerOpen/marvin/commit/3ef20e4fb86f32d80d20beae235087057cb22522))


## v1.0.0-rc.143 (2026-10-03)

### Features

- **publishing**: Published content changes rebuild the site on their own
  ([`5c70383`](https://github.com/InnerOpen/marvin/commit/5c70383acb0fea55ffd9a926c047eedca92d4d23))


## v1.0.0-rc.142 (2026-10-03)

### Bug Fixes

- **ai**: The search index holds published entries only, and skips unchanged saves
  ([`7136ac8`](https://github.com/InnerOpen/marvin/commit/7136ac8cdb910ce7ff3467e0562678871bc66730))


## v1.0.0-rc.141 (2026-10-03)

### Features

- **ai**: Workspace reindex runs in the background, batched and incremental
  ([`33d3b7f`](https://github.com/InnerOpen/marvin/commit/33d3b7f5438cd98a606e2a67cb17c86f66262f1c))


## v1.0.0-rc.140 (2026-10-03)

### Bug Fixes

- **ai**: The main agent carries the workspace's assistant name
  ([`8489865`](https://github.com/InnerOpen/marvin/commit/84898654f79b8b701d9471a0a99d52ffd2792a5d))


## v1.0.0-rc.139 (2026-10-03)

### Bug Fixes

- Bugs the manual review found — fail-closed where ops, apply_many connection, recorded chat runs,
  stale UI copy
  ([`f08d0c2`](https://github.com/InnerOpen/marvin/commit/f08d0c2495a75c9c8fe5ea13ec4a6b4f8f39a9d3))


## v1.0.0-rc.138 (2026-10-02)

### Features

- **entries**: One entry query for agents, workflows and bulk actions
  ([`1c5dcbe`](https://github.com/InnerOpen/marvin/commit/1c5dcbeb504a10a27b9807d057c4772ce99bbc17))


## v1.0.0-rc.137 (2026-10-02)

### Bug Fixes

- **ai**: Keep core tool text workspace-agnostic
  ([`85a03a7`](https://github.com/InnerOpen/marvin/commit/85a03a7267b51134f60d58c6d045a9c49a71ad0b))


## v1.0.0-rc.136 (2026-10-02)

### Bug Fixes

- **ai**: Find_entries can filter and read an entry type's own fields
  ([`2ef0b34`](https://github.com/InnerOpen/marvin/commit/2ef0b348d46cc7ccbfe4f5b1896bea7a1dc0691f))


## v1.0.0-rc.135 (2026-10-02)

### Features

- **ai**: The bubble wears the workspace's assistant name and icon
  ([`1a9dcc6`](https://github.com/InnerOpen/marvin/commit/1a9dcc61001ca883eab1118bdc4a3b5b083d2bb5))


## v1.0.0-rc.134 (2026-10-02)

### Bug Fixes

- **ai**: Approval mode covers every AI write-back; Ask Marvin is the agent source
  ([`6a8dd36`](https://github.com/InnerOpen/marvin/commit/6a8dd360aae03dbba4a414a07193c60e66272b63))


## v1.0.0-rc.133 (2026-10-02)

### Bug Fixes

- **ai**: A blank persona means Marvin's default voice, as the settings page says
  ([`5b2b45d`](https://github.com/InnerOpen/marvin/commit/5b2b45d7264541efa0d9a9bd717cc98c0626a1cd))


## v1.0.0-rc.132 (2026-10-02)

### Bug Fixes

- **automation**: Set_data reads the entry type defensively
  ([`28a6d27`](https://github.com/InnerOpen/marvin/commit/28a6d27f5bb9e6ea7642479949639e46f40eae3d))


## v1.0.0-rc.131 (2026-10-02)

### Bug Fixes

- **automation**: Typed-in values meet checkbox and number fields
  ([`c3ac416`](https://github.com/InnerOpen/marvin/commit/c3ac41665c3735c4e47ef51d7d08e01eea1c3fcf))


## v1.0.0-rc.130 (2026-10-02)

### Bug Fixes

- **automation**: Entry queries de-duplicate by id, so they work on Postgres
  ([`01c4226`](https://github.com/InnerOpen/marvin/commit/01c4226e311fb507429f90665462644814d33d26))


## v1.0.0-rc.129 (2026-10-02)

### Bug Fixes

- **automation**: Query runs see each entry's fields, and can filter by them
  ([`0e254e4`](https://github.com/InnerOpen/marvin/commit/0e254e4c8bac33998b040bf9c571033e3d6a20bb))


## v1.0.0-rc.128 (2026-10-02)

### Features

- **admin**: Activity toasts hang off the bell like a speech bubble
  ([`8177f37`](https://github.com/InnerOpen/marvin/commit/8177f3751eb5358e4df0c055d0beee3d0ed65422))


## v1.0.0-rc.127 (2026-10-02)

### Features

- **admin**: Centre the activity toasts under the top bar
  ([`5f853a2`](https://github.com/InnerOpen/marvin/commit/5f853a298cb6d23fb1333231a9a3a4de13926ca2))


## v1.0.0-rc.126 (2026-10-02)

### Bug Fixes

- **admin**: Show activity toasts in the window corner, not above the top bar
  ([`ca8b18e`](https://github.com/InnerOpen/marvin/commit/ca8b18e64a3f9d4a45057033fa83a927ca6e6db2))


## v1.0.0-rc.125 (2026-10-02)

### Bug Fixes

- **admin**: Style the activity toasts
  ([`de47dfc`](https://github.com/InnerOpen/marvin/commit/de47dfcd2e0069c764ba182fd9036fcc09e73616))


## v1.0.0-rc.124 (2026-10-02)

### Chores

- **deploy**: Iwobble allows 16 MiB integration downloads (Square item pictures)
  ([`151325f`](https://github.com/InnerOpen/marvin/commit/151325fca2879dcb1ed891ae7a4eb995bef9b33b))

### Features

- **admin**: Live activity toasts
  ([`378a10d`](https://github.com/InnerOpen/marvin/commit/378a10d6642e4c47fe5633c0ca2b6c2928f3c487))


## v1.0.0-rc.123 (2026-10-02)

### Features

- **integrations**: INTEGRATION_HTTP_MAX_BYTES caps provider downloads
  ([`1fd3bd8`](https://github.com/InnerOpen/marvin/commit/1fd3bd812618d716d65548bc97c67569d685f64f))


## v1.0.0-rc.122 (2026-10-02)

### Features

- **publishing**: Site rebuild debounce windows are env settings
  ([`e636672`](https://github.com/InnerOpen/marvin/commit/e636672b8a1497a2c684fee6d2f4478d7834a42e))


## v1.0.0-rc.121 (2026-10-02)

### Features

- **publishing**: Coalesce site rebuild requests per workspace
  ([`322d0bf`](https://github.com/InnerOpen/marvin/commit/322d0bfbad52a8d8edfc39ae152f230e9bea21ed))


## v1.0.0-rc.120 (2026-10-02)

### Bug Fixes

- **marvin-bubble**: Open on the latest turn of a restored conversation
  ([`21a6114`](https://github.com/InnerOpen/marvin/commit/21a6114f84f6669f5841156095e1175f464b0249))


## v1.0.0-rc.119 (2026-10-02)

### Features

- **automation**: Workflows see the entry's featured image URL; integration HTTP sends a named
  User-Agent
  ([`c4691e6`](https://github.com/InnerOpen/marvin/commit/c4691e617cbc6f599b44d64e4056af8d147229e4))


## v1.0.0-rc.118 (2026-10-02)

### Features

- **blueprints**: Update an applied workflow to its integration's current version
  ([`d874a58`](https://github.com/InnerOpen/marvin/commit/d874a58d65dcad3942b33681e42a41523701b1ec))


## v1.0.0-rc.117 (2026-10-02)

### Bug Fixes

- **blueprints**: An integration parameter defaults to the workspace's own connection
  ([`145dfbe`](https://github.com/InnerOpen/marvin/commit/145dfbe0d3cbb308702bca3044cec3faf873ba7b))


## v1.0.0-rc.116 (2026-10-02)

### Features

- **blueprints**: Pick parameters from dropdowns — entry types, collections, integrations
  ([`c6e8547`](https://github.com/InnerOpen/marvin/commit/c6e8547219a2f1ade10218636512073b6aa3d381))


## v1.0.0-rc.115 (2026-10-02)

### Features

- **integrations**: Edit a connected integration; keep Add buttons on the right
  ([`ace1355`](https://github.com/InnerOpen/marvin/commit/ace1355e5547d166fefd222c28ffeb167eeb8668))


## v1.0.0-rc.114 (2026-10-02)

### Bug Fixes

- **integrations**: Apply parameterised content from the card, show action results, {{SECRET}}
  credentials
  ([`4a8cba5`](https://github.com/InnerOpen/marvin/commit/4a8cba51c476c85e2e74eea5589e14c84e653df7))


## v1.0.0-rc.113 (2026-10-02)

### Features

- **hooks**: One general webhook-signature engine — core presets, integration presets, custom
  ([`ddac9b1`](https://github.com/InnerOpen/marvin/commit/ddac9b1d23bc95e46ebb1d8660cee9640ffb4056))


## v1.0.0-rc.112 (2026-10-02)

### Bug Fixes

- **auth**: Workspace admins got a 500 on workflows, webhooks and AI settings
  ([`0c58086`](https://github.com/InnerOpen/marvin/commit/0c58086be3f44a9eedbcdbadf6bb4bfaa3d71a1c))

### Testing

- **integrations**: Skip the HTTP helper tests when the optional SDK is absent
  ([`82c7e04`](https://github.com/InnerOpen/marvin/commit/82c7e048ee514a4f5003089cdd81055daf86ef5b))


## v1.0.0-rc.111 (2026-10-02)

### Chores

- **deploy**: Install the Square integration on iwobble; plans for Trash, dev+Postgres and Square
  ([`f8ee69e`](https://github.com/InnerOpen/marvin/commit/f8ee69ebb93b96c96db266e8c6c79125c7c72485))

### Code Style

- **blueprints**: Ruff format apply.py
  ([`f687421`](https://github.com/InnerOpen/marvin/commit/f687421b4764cb2ae2c1d4ef6c9f86a63e47ccc5))

- **tests**: Ruff format the member-role, set_data and signature tests
  ([`c724d9c`](https://github.com/InnerOpen/marvin/commit/c724d9c46c9e9ad6e3f2023521ee7c3b37df13ed))

### Features

- **automation**: Integration workflow step — run a provider action, keep its result
  ([`06dc3a9`](https://github.com/InnerOpen/marvin/commit/06dc3a91d41668f270eab7c4164c139df0cb784d))

- **automation**: List indexes in template paths; entry metadata in the workflow context
  ([`46d688b`](https://github.com/InnerOpen/marvin/commit/46d688be5d6f8f04369260b2715f0efa34ed3137))

- **automation**: Set_data entry step — write an entry's schema fields from a workflow
  ([`78744ba`](https://github.com/InnerOpen/marvin/commit/78744bac9060027579925c606c4ff976689f7b3b))

- **blueprints**: Entry_fields, incoming_webhook and workflow kinds; applying needs admin
  ([`1cce300`](https://github.com/InnerOpen/marvin/commit/1cce3001817d8ad6b4eab90509c9715456781446))

- **hooks**: Signature schemes for incoming webhooks — Square
  ([`024410d`](https://github.com/InnerOpen/marvin/commit/024410dd6db4d62085d9f41ab726f7a0082ac83a))

- **integrations**: Put and delete on the provider HTTP helper
  ([`aa878a6`](https://github.com/InnerOpen/marvin/commit/aa878a6e15bd54566cb2bd94d4adf16cd55f590e))


## v1.0.0-rc.110 (2026-10-01)

### Bug Fixes

- **ai**: Price the GPT-5 family; an unpriced model costs "unknown", not "Free"
  ([`90cd72a`](https://github.com/InnerOpen/marvin/commit/90cd72a686a25cd894e87967f713f4bcda1f9dae))


## v1.0.0-rc.109 (2026-10-01)

### Bug Fixes

- **ai**: OpenAI reasoning models — no null max_tokens, max_completion_tokens, default temperature
  ([`041c4de`](https://github.com/InnerOpen/marvin/commit/041c4de5239722007cdc8f07fd53f0fd21d65e4a))

- **members**: Invited roles stick, inviting follows the workspace role, user edits save
  ([`a76aab9`](https://github.com/InnerOpen/marvin/commit/a76aab97c4630146335d2a9f2d34dc04c1d48d5e))


## v1.0.0-rc.108 (2026-10-01)

### Features

- **agents**: Workspace inventory + forgiving workflow lookup
  ([`326b831`](https://github.com/InnerOpen/marvin/commit/326b8319ff4d8a72350df47514e043b5cd71d867))


## v1.0.0-rc.107 (2026-10-01)

### Features

- **agents**: Ask-first approval — park a run on its thread, resume with the user's decisions (slice
  C)
  ([`7d63527`](https://github.com/InnerOpen/marvin/commit/7d63527ba480f893ff18dd846d82cdf13ca8da33))


## v1.0.0-rc.106 (2026-10-01)

### Code Style

- **ask**: Links inside answers look like links
  ([`28fe069`](https://github.com/InnerOpen/marvin/commit/28fe0691882a2497473b30104e3fd0bd73950446))

### Features

- **ai**: Executions spawned inside an agent run carry parent_execution_id
  ([`08b244f`](https://github.com/InnerOpen/marvin/commit/08b244f148d94f0f138c85f05df8658bcd21aa53))


## v1.0.0-rc.105 (2026-10-01)

### Bug Fixes

- **sidebar**: Inbox badge on the Entries row, correct counts path
  ([`6e43f26`](https://github.com/InnerOpen/marvin/commit/6e43f26eeada6cef6c49ef24077fb1585e4ccc54))


## v1.0.0-rc.104 (2026-10-01)

### Bug Fixes

- **authoring**: Deterministic review links — absolute when FRONTEND_URL is configured, plus a
  copy-ready reviewLink
  ([`a837ba2`](https://github.com/InnerOpen/marvin/commit/a837ba2b600e56b94983ee164e5dc9ac2dc98b53))


## v1.0.0-rc.103 (2026-10-01)

### Features

- **sidebar**: Inbox row with an unread-style count badge
  ([`b359b7a`](https://github.com/InnerOpen/marvin/commit/b359b7a51a8ec35da01a2c39bd3aa591bffc59c4))


## v1.0.0-rc.102 (2026-10-01)

### Bug Fixes

- **agents**: Keep workspace links relative; ask the specialist for text before an action only
  Marvin can do
  ([`0bdb790`](https://github.com/InnerOpen/marvin/commit/0bdb79005359b6a1802b2980524b76c1c185cbee))


## v1.0.0-rc.101 (2026-10-01)

### Bug Fixes

- **agents**: "auto" from the caller no longer overrides a named agent's own register
  ([`2155bb6`](https://github.com/InnerOpen/marvin/commit/2155bb6e6056c3d53dab1fb833f81b77c571e018))

### Chores

- **tasks**: Slice D verified live
  ([`ddf4e32`](https://github.com/InnerOpen/marvin/commit/ddf4e32e97d972d9e899070c4b4d76058a515aab))


## v1.0.0-rc.100 (2026-10-01)

### Bug Fixes

- **agents**: Make the router hand off on an explicit voice/agent request; lenient find_entries type
  slug
  ([`fc4c1ae`](https://github.com/InnerOpen/marvin/commit/fc4c1ae479229b11600c077af12aa532b6b9b881))


## v1.0.0-rc.99 (2026-10-01)

### Chores

- **tasks**: Slice D rolled out; live verification left for Jared
  ([`1db427c`](https://github.com/InnerOpen/marvin/commit/1db427c317526554e41b5b1c45fa87e229e0a05f))

### Features

- **agents**: Let the system Ask agent refer with suggest_agent
  ([`b178b8c`](https://github.com/InnerOpen/marvin/commit/b178b8c42fbf4b11fe6e1d679e50c0001429b87d))


## v1.0.0-rc.98 (2026-10-01)

### Features

- **agents**: Marvin as router — hand-offs and referrals (v2 slice D)
  ([`2320057`](https://github.com/InnerOpen/marvin/commit/2320057f76b99f87d65be15e9e2be51471e62608))

### Testing

- **agents**: "ask" is a valid tool policy now that POLICY_ASK exists
  ([`27d3f8b`](https://github.com/InnerOpen/marvin/commit/27d3f8b5cc92ebaadae5b5fe74026a0fbd85fac8))


## v1.0.0-rc.97 (2026-09-25)

### Features

- **scheduled-tasks**: Ship the execution-log prune as a system task
  ([`ce6b4c5`](https://github.com/InnerOpen/marvin/commit/ce6b4c5f406696ec639799dff5b6f1318fc5764b))


## v1.0.0-rc.96 (2026-09-25)

### Features

- **scheduled-tasks**: Stop routine no-op runs from burying the execution log
  ([`c34e516`](https://github.com/InnerOpen/marvin/commit/c34e516f8668c45deba1fe699dbfd34cd6e28389))


## v1.0.0-rc.95 (2026-09-25)

### Bug Fixes

- **blueprints**: Catalog test counted whatever providers were installed
  ([`eebd164`](https://github.com/InnerOpen/marvin/commit/eebd164683e6e27dc68f31b5d82dc7d6ebccf1c2))


## v1.0.0-rc.94 (2026-09-25)

### Features

- **integrations**: Show what each integration can actually do
  ([`3e1603b`](https://github.com/InnerOpen/marvin/commit/3e1603b4ab43f0f1fa8ffbd39785869bf90e3aac))


## v1.0.0-rc.93 (2026-09-25)

### Features

- **integrations**: Separate what an integration needs from what it suggests
  ([`bfad431`](https://github.com/InnerOpen/marvin/commit/bfad4311312dcb9a66556c0d4391566d167a2598))


## v1.0.0-rc.92 (2026-09-25)

### Features

- **integrations**: Event-subscription blueprints, and an optional provider icon
  ([`847631d`](https://github.com/InnerOpen/marvin/commit/847631de490f01f0b29545b0c735fae7a01af47a))


## v1.0.0-rc.91 (2026-09-25)

### Bug Fixes

- **integrations**: Deterministic rule order, and document the content declaration
  ([`2c581d2`](https://github.com/InnerOpen/marvin/commit/2c581d2cb6694baca0e036e4b486c561e3cfcb70))


## v1.0.0-rc.90 (2026-09-25)

### Features

- **integrations**: Show what an integration needs to work, and apply it there
  ([`4f8d30e`](https://github.com/InnerOpen/marvin/commit/4f8d30e3f6b965fce710fbe9ef93fde9d63438b2))

### Refactoring

- **blueprints**: No gallery — the catalog belongs where it is useful
  ([`3ec7d61`](https://github.com/InnerOpen/marvin/commit/3ec7d61cc42e838ab2f76b19aba0cc0a3d64c0be))


## v1.0.0-rc.89 (2026-09-25)

### Bug Fixes

- **blueprints**: Drop the core 'drafts' blueprint — it duplicates a system collection
  ([`8a4e923`](https://github.com/InnerOpen/marvin/commit/8a4e923805ef9a6d9da3f67d48c9ed3f750cd978))


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
