# Changelog

All notable changes to the Marvin CMS server will be documented in this file.

This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!-- version list -->

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
