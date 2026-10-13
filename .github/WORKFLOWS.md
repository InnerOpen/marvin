# GitHub Actions Workflows Documentation

This document describes the complete CI/CD pipeline for Marvin CMS.

## Architecture Overview

Marvin's CI/CD pipeline is designed around its multi-component architecture:

- **Backend**: FastAPI + SQLAlchemy + Alembic + PostgreSQL + Redis
- **SDK**: TypeScript SDK (`@inneropen/marvin-sdk`)
- **CLI**: TypeScript CLI (`@inneropen/marvin-cli`)
- **Infrastructure**: Docker + Helm Charts + Kubernetes
- **Documentation**: MkDocs + API docs + SDK/CLI docs

## Workflow Structure

```
.github/workflows/
├── pr-ci.yml          # Fast PR validation (lint, format, basic tests)
├── test.yml           # Full test suite with databases
├── docker.yml         # Container image builds
├── release.yml        # Semantic versioning & releases
├── codeql.yml         # Security scanning
├── helm.yml           # Helm chart validation
├── sdk.yml            # SDK build & verification
├── cli.yml            # CLI integration tests
├── workspace.yml      # End-to-end workspace tests
└── docs.yml           # Documentation builds
```

## Workflow Descriptions

### 1. pr-ci.yml (Pull Request CI)

**Triggers**: `pull_request`

**Purpose**: Fast feedback loop for PRs

**Jobs**:
- **Lint & Format**
  - Ruff linting
  - Black formatting check
  - TypeScript ESLint (SDK/CLI)
  - Prettier formatting check

- **Type Checking**
  - mypy (Python)
  - TypeScript type checking

- **Quick Validation**
  - SDK build
  - CLI build
  - Helm lint
  - OpenAPI spec generation verification
  - Ensure generated files are committed

**Duration**: ~3-5 minutes

**Fail Fast**: Yes - stops on first error

---

### 2. test.yml (Full Test Suite)

**Triggers**:
- `push` to `main` or `develop`
- Manual dispatch

**Purpose**: Comprehensive testing with real services

**Jobs**:

#### Backend Tests (PostgreSQL)
- PostgreSQL 15 service
- Redis 7 service
- Alembic migration testing:
  - Upgrade all migrations
  - Downgrade all migrations
  - Re-upgrade (verify reversibility)
- Pytest with coverage
- Upload coverage reports

#### SDK Tests
- Build TypeScript SDK
- Unit tests
- Integration tests against mock API

#### CLI Tests
- Build TypeScript CLI
- Unit tests
- Mock command execution

**Duration**: ~8-12 minutes

---

### 3. docker.yml (Container Builds)

**Triggers**:
- `push` to `main`
- Manual dispatch

**Purpose**: Build and publish Docker images

**Jobs**:
- Build multi-stage Dockerfile
- Security scanning (Trivy)
- Push to GitHub Container Registry (ghcr.io)
- Tag strategies:
  - `latest` (main branch)
  - `develop` (develop branch)
  - `sha-<commit>` (all builds)
  - `v<version>` (releases)

**Outputs**: `ghcr.io/InnerOpen/marvin:latest`

---

### 4. release.yml (Semantic Release)

**Triggers**:
- `push` to `main` or `develop`

**Purpose**: Automated versioning and releases

**Jobs**:
- Analyze commits (conventional commits)
- Bump version in:
  - `pyproject.toml`
  - `src/marvin/__init__.py`
  - Helm chart `Chart.yaml`
- Generate CHANGELOG.md
- Create git tag
- Create GitHub Release
- Build and publish artifacts:
  - Docker image (to GitHub Container Registry)
  - Helm chart package (to GitHub Releases)
  - (SDK and CLI publish from their own repositories)

**Version Strategy**:
- `main` → stable (v1.0.0)
- `develop` → prerelease (v1.0.0-next.1)

---

### 5. codeql.yml (Security Scanning)

**Triggers**:
- `push` to `main`
- `pull_request`
- Schedule: Weekly (Monday 3:00 AM UTC)

**Purpose**: Security vulnerability detection

**Languages**:
- Python
- TypeScript

**Queries**: `security-extended`

**Duration**: ~10-15 minutes

---

### 6. helm.yml (Helm Chart Validation)

**Triggers**:
- `pull_request` (if Helm files changed)
- `push` to `main`

**Purpose**: Validate Kubernetes deployment

**Jobs**:

#### Lint
- `helm lint`
- `helm template` dry-run
- YAML validation

#### Integration Test
- Create Kind cluster
- Install Helm chart
- Verify:
  - All pods running
  - Readiness probes pass
  - Health endpoints respond
  - Service endpoints accessible
- Run smoke tests
- Cleanup

**Duration**: ~6-8 minutes

---

### 7. sdk.yml (SDK Quality Gate)

**Triggers**:
- `pull_request`
- `push` to `main`

**Purpose**: Protect SDK quality

**Jobs**:
- Build SDK from OpenAPI spec
- Run unit tests
- Run integration tests
- Verify generated SDK matches committed files
- Fail if OpenAPI changed but SDK not regenerated
- Bundle size check
- Type coverage check

**Validation**:
```bash
# Generate SDK from OpenAPI
npm run generate

# Verify no changes
git diff --exit-code src/
```

---

### 8. cli.yml (CLI Integration Tests)

**Triggers**:
- `pull_request`
- `push` to `main`

**Purpose**: End-to-end CLI validation

**Jobs**:
- Build CLI
- Start Marvin backend (Docker)
- Run CLI command suite:
  ```bash
  marvin workspace create test-workspace
  marvin collection create test-collection
  marvin entry create test-entry
  marvin asset upload test.jpg
  marvin publish entry <id>
  marvin entry get <id>
  marvin entry delete <id>
  ```
- Validate JSON output
- Verify exit codes
- Test error handling

**Duration**: ~5-7 minutes

---

### 9. workspace.yml (E2E Platform Test)

**Triggers**:
- `push` to `main`
- Manual dispatch
- Nightly schedule

**Purpose**: Full platform validation

**Jobs**:

#### Setup Infrastructure
- PostgreSQL
- Redis
- Marvin backend

#### Import Seed Workspace
- Import complete workspace
- Verify all data imported:
  - Workspace metadata
  - Collections
  - Entry types
  - Entries
  - Assets
  - Resources
  - Relationships

#### Validation Suite
- **Publish API**: Query published content
- **Platform API**: CRUD operations
- **SDK**: Retrieve data via SDK
- **CLI**: Interact via CLI commands
- **Export**: Verify workspace export

**Duration**: ~10-15 minutes

---

### 10. docs.yml (Documentation)

**Triggers**:
- `push` to `main`
- Manual dispatch

**Purpose**: Build and publish documentation

**Jobs**:
- Build MkDocs site
- Generate API documentation (OpenAPI → HTML)
- Generate SDK documentation (TypeDoc)
- Generate CLI documentation (typedoc + README)
- Upload artifacts
- Deploy to GitHub Pages (if enabled)

**Outputs**: https://InnerOpen.github.io/marvin/

---

## Required Secrets

Configure these in GitHub repository settings:

### Auto-Provided (No Setup Required)
```
GITHUB_TOKEN               # Automatically provided by GitHub Actions
                          # Used for: Docker/Helm publishing, GitHub Releases
```

### Optional
```
GHCR_TOKEN                 # Alternative to GITHUB_TOKEN for container registry (rarely needed)
PYPI_TOKEN                 # PyPI token (future use if publishing to PyPI)
```

### SDK and CLI Publishing
**Note**: SDK and CLI are published from their own repositories:
- `InnerOpen/marvin-sdk` has its own `NPM_TOKEN`
- `InnerOpen/marvin-cli` has its own `NPM_TOKEN`
- The Marvin server repo does NOT need `NPM_TOKEN`

### Testing
```
MARVIN_TEST_DATABASE_URL   # Test database connection string (optional)
MARVIN_TEST_REDIS_URL      # Test Redis connection string (optional)
```

### Deployment
```
KUBE_CONFIG                # Kubernetes config for deployment (future)
HELM_REGISTRY_TOKEN        # Helm registry token (if using private registry)
```

---

## Artifacts

Each workflow produces relevant artifacts:

### pr-ci.yml
- Linting reports
- Type checking results

### test.yml
- Test reports (JUnit XML)
- Coverage reports (coverage.xml, htmlcov/)
- Database migration logs

### docker.yml
- Docker image manifest
- Security scan results (Trivy report)

### release.yml
- CHANGELOG.md
- SDK package tarball
- CLI package tarball
- Helm chart package (.tgz)

### helm.yml
- Rendered Kubernetes manifests
- Kind cluster logs

### sdk.yml
- SDK bundle
- Type definitions

### cli.yml
- CLI binaries (future: cross-platform)
- Test output logs

### workspace.yml
- Workspace export file
- Test data snapshots
- API response samples

### docs.yml
- Documentation site (HTML)
- OpenAPI spec (JSON/YAML)

---

## Caching Strategy

All workflows use aggressive caching to improve speed:

### Python Dependencies
```yaml
- uses: actions/cache@v4
  with:
    path: |
      ~/.cache/pip
      ~/.cache/uv
      .venv
    key: ${{ runner.os }}-python-${{ hashFiles('**/pyproject.toml', '**/uv.lock') }}
```

### Node Dependencies
```yaml
- uses: actions/cache@v4
  with:
    path: |
      ~/.npm
      ~/Code/marvin-sdk/node_modules
      ~/Code/marvin-cli/node_modules
    key: ${{ runner.os }}-node-${{ hashFiles('**/package-lock.json') }}
```

### Docker Layers
```yaml
- uses: docker/build-push-action@v5
  with:
    cache-from: type=gha
    cache-to: type=gha,mode=max
```

### Helm Dependencies
```yaml
- uses: actions/cache@v4
  with:
    path: ~/.cache/helm
    key: ${{ runner.os }}-helm-${{ hashFiles('**/Chart.yaml') }}
```

---

## Concurrency Control

All workflows include concurrency protection to cancel outdated runs:

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

This ensures:
- Only one run per branch
- Superseded PR builds are cancelled
- Cost optimization

---

## Permissions

Each workflow uses minimal required permissions:

### Read-Only (default)
```yaml
permissions:
  contents: read
```

### Release Workflow
```yaml
permissions:
  contents: write      # Create tags, update files
  issues: write        # Comment on issues
  pull-requests: write # Comment on PRs
  packages: write      # Publish to GHCR
```

### CodeQL Workflow
```yaml
permissions:
  security-events: write
  actions: read
  contents: read
```

---

## Matrix Builds

Where beneficial, workflows use matrix strategies:

### Python Versions (future)
```yaml
strategy:
  matrix:
    python-version: ['3.12', '3.13']
```

### OS Targets (CLI binaries, future)
```yaml
strategy:
  matrix:
    os: [ubuntu-latest, macos-latest, windows-latest]
```

---

## Failure Notifications

Configure GitHub Actions notifications in repository settings:

- Email on workflow failure
- Slack integration (via webhooks)
- GitHub mobile app notifications

---

## Best Practices

### 1. Fail Fast
- Use `fail-fast: true` in matrices
- Run quick checks (lint, format) before expensive tests
- Exit on first error in PR CI

### 2. Reusable Steps
- Extract common setup into composite actions (future)
- Use job outputs for cross-job communication
- Share artifacts between jobs

### 3. Clear Naming
- Descriptive job and step names
- Use emojis for visual scanning (optional)
- Group related steps

### 4. Environment Isolation
- Each job starts fresh
- Use services for databases
- Clean up resources in teardown

### 5. Security
- Never log secrets
- Use `secrets.GITHUB_TOKEN` when possible
- Restrict permissions to minimum required

---

## Future Enhancements

### Short Term
1. **Composite Actions**: Extract reusable setup steps
2. **Deployment Workflows**: Auto-deploy to staging/production
3. **Performance Testing**: Benchmark API response times
4. **Visual Regression**: Screenshot testing for UI components
5. **Dependency Updates**: Automated Dependabot PRs

### Medium Term
1. **Multi-Region Deployment**: Deploy to multiple Kubernetes clusters
2. **Canary Releases**: Gradual rollout with traffic splitting
3. **Rollback Automation**: Auto-revert on health check failures
4. **Load Testing**: Simulate production traffic patterns
5. **Database Migration Testing**: Test migrations on production-like data

### Long Term
1. **Chaos Engineering**: Automated failure injection tests
2. **Cost Optimization**: Track and optimize cloud resource usage
3. **Compliance Scanning**: Automated security/compliance checks
4. **Multi-Cloud**: Deploy to AWS, GCP, Azure
5. **GitOps**: ArgoCD/Flux integration for declarative deployments

---

## Troubleshooting

### Common Issues

**Issue**: Flaky tests
- **Solution**: Use retry mechanisms, increase timeouts, fix race conditions

**Issue**: Docker build timeouts
- **Solution**: Optimize Dockerfile layers, use BuildKit, increase timeout

**Issue**: Out of disk space
- **Solution**: Clean up Docker images, use pruning steps, request larger runners

**Issue**: npm install fails
- **Solution**: Clear cache, use `npm ci` instead of `npm install`, check lockfile

**Issue**: Database connection fails
- **Solution**: Verify service health checks, check port mappings, review logs

---

## Monitoring

Track workflow health via:

1. **GitHub Insights**: Actions tab → Workflow analytics
2. **Success Rate**: Target >95% success rate
3. **Duration Trends**: Monitor for performance regressions
4. **Cost**: Review Actions minutes usage monthly

---

## Support

For workflow issues:
1. Check GitHub Actions logs
2. Review this documentation
3. Open issue with workflow run URL
4. Tag `@devops` team
