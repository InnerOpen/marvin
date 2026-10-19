# GitHub Actions Quick Start Guide

Get the Marvin CI/CD pipeline running in 5 minutes.

## Prerequisites

- [x] GitHub repository with Marvin code
- [x] Workflows committed to `.github/workflows/`
- [x] `GITHUB_TOKEN` (auto-provided by GitHub Actions)

## 1. Verify Secrets (30 seconds)

The Marvin server repository only needs `GITHUB_TOKEN`, which is **automatically provided** by GitHub Actions.

### No Manual Setup Required! 🎉

The auto-provided `GITHUB_TOKEN` is used for:
- ✅ Publishing Docker images to GitHub Container Registry (ghcr.io)
- ✅ Creating GitHub Releases
- ✅ Packaging Helm charts
- ✅ Accessing other repos for testing (SDK/CLI)

### Note: SDK and CLI Publishing

SDK and CLI are published from their **own repositories**:
- `InnerOpen/marvin-sdk` has its own `NPM_TOKEN` secret
- `InnerOpen/marvin-cli` has its own `NPM_TOKEN` secret
- The Marvin server repo does **not** publish to npm

## 2. Enable Branch Protection (1 minute)

Protect `main` and `develop` branches:

1. Go to Settings → Branches
2. Click "Add branch protection rule"
3. Branch name pattern: `main`
4. Check:
   - ✅ Require a pull request before merging
   - ✅ Require status checks to pass before merging
   - ✅ Require branches to be up to date before merging
5. Select required status checks:
   - `Python Lint & Format`
   - `SDK Build & Lint`
   - `CLI Build & Lint`
   - `Helm Lint`
6. Click "Create"
7. Repeat for `develop` branch

## 3. Test the Pipeline (1 minute)

### Create a Test PR

```bash
# Create a test branch
git checkout -b test-ci-pipeline

# Make a small change
echo "# CI/CD Pipeline Test" >> TEST_CI.md
git add TEST_CI.md
git commit -m "test: verify CI pipeline works"

# Push and create PR
git push origin test-ci-pipeline
```

Go to GitHub and create a Pull Request.

### Watch Workflows Run

1. Go to your repo → Actions tab
2. You should see `pr-ci.yml` running
3. Wait ~3-5 minutes for completion
4. All checks should pass ✅

### Expected Results

- ✅ Python Lint & Format
- ✅ Python Quick Tests
- ✅ OpenAPI Validation
- ✅ SDK Build & Lint
- ✅ CLI Build & Lint
- ✅ Helm Lint
- ✅ PR CI Summary

## 4. Trigger a Release (Optional)

Merge your PR to trigger release automation:

```bash
# Merge PR on GitHub or:
git checkout main
git merge test-ci-pipeline
git push origin main
```

This triggers:
- ✅ Full test suite (`test.yml`)
- ✅ Docker image build (`docker.yml`)
- ✅ Semantic release (`release.yml`)
- ✅ Security scanning (`codeql.yml`)
- ✅ Documentation build (`docs.yml`)

## 5. Verify Release

Check the release was created:

1. Go to your repo → Releases
2. You should see a new release (e.g., `v0.2.1`)
3. CHANGELOG.md should be updated
4. Docker image published to GHCR
5. Helm chart packaged

## Troubleshooting

### Workflow fails with "Secret not found"

**Issue**: Missing required secret

**Fix**:
- The Marvin server repo only needs `GITHUB_TOKEN` (auto-provided)
- If you see this error, check the workflow file for typos in secret names
- SDK/CLI secrets should be configured in their respective repos, not here

### PR checks don't appear

**Issue**: Branch protection not configured

**Fix**:
1. Go to Settings → Branches
2. Add branch protection rule (see step 2 above)

### Docker build fails

**Issue**: Permission denied to push to GHCR

**Fix**:
1. Verify `GITHUB_TOKEN` has `packages: write` permission
2. Check workflow has `permissions: packages: write`
3. Verify repository visibility (public repos work without extra config)

### SDK/CLI build fails

**Issue**: Cannot checkout SDK/CLI repos

**Fix**:
1. Verify repos exist: `InnerOpen/marvin-sdk`, `InnerOpen/marvin-cli`
2. Verify `GITHUB_TOKEN` has access to these repos
3. If private repos, may need personal access token

### Tests fail with database connection error

**Issue**: PostgreSQL service not ready

**Fix**:
- This is usually a timing issue
- Workflow includes health checks and retries
- Re-run the workflow

## What's Next?

### Enable GitHub Pages

For documentation hosting:

1. Go to Settings → Pages
2. Source: GitHub Actions
3. Save

Documentation will be available at:
`https://YOUR_ORG.github.io/marvin/`

### Configure Notifications

Get notified when workflows fail:

1. Go to your GitHub profile → Settings → Notifications
2. Under "Actions", check:
   - ✅ Send notifications for failed workflows

### Set Up Slack Integration (Optional)

Get workflow notifications in Slack:

1. Create a Slack webhook URL
2. Add as repository secret: `SLACK_WEBHOOK_URL`
3. Add notification step to workflows:

```yaml
- name: Notify Slack
  if: failure()
  uses: slackapi/slack-github-action@v1
  with:
    webhook: ${{ secrets.SLACK_WEBHOOK_URL }}
    payload: |
      {
        "text": "Workflow failed: ${{ github.workflow }}"
      }
```

## Monitoring Dashboard

Track workflow health:

1. Go to your repo → Insights → Actions
2. View:
   - Workflow run history
   - Success/failure rates
   - Duration trends
   - Usage statistics

Target metrics:
- Success rate: >95%
- PR CI duration: <5 minutes
- Full test suite: <12 minutes

## Common Workflows

### Run tests manually

```bash
# Go to Actions tab → test.yml → Run workflow
```

### Create a release manually

```bash
# Use conventional commit on main
git checkout main
git commit -m "feat: add new feature" --allow-empty
git push origin main

# release.yml will automatically create a release
```

### Test a workflow locally

```bash
# Install act
brew install act

# Run pr-ci workflow
act pull_request -W .github/workflows/pr-ci.yml

# Run test workflow
act push -W .github/workflows/test.yml --secret-file .env.secrets
```

## Getting Help

1. **Documentation**:
   - Read `.github/WORKFLOWS.md` for detailed explanations
   - Read `.github/SECRETS.md` for secret configuration
   - Read `docs/archive/CI_CD_IMPLEMENTATION.md` for architecture overview

2. **Workflow Logs**:
   - Go to Actions tab
   - Click on failed workflow
   - Expand failed step to see error details

3. **GitHub Community**:
   - [GitHub Actions Community Forum](https://github.community/c/actions)
   - [GitHub Actions Documentation](https://docs.github.com/en/actions)

4. **Support**:
   - Open an issue with `ci/cd` label
   - Include workflow run URL
   - Attach relevant logs

## Success Checklist

Your CI/CD pipeline is ready when:

- [x] All workflows created in `.github/workflows/`
- [ ] Branch protection enabled on `main` and `develop`
- [ ] Test PR created and all checks pass
- [ ] Release workflow tested and working
- [ ] Docker images publishing to GHCR
- [ ] SDK/CLI publishing to npm (optional)
- [ ] Documentation building successfully
- [ ] Team notified of new pipeline

## Resources

- [Conventional Commits](https://www.conventionalcommits.org/)
- [Semantic Versioning](https://semver.org/)
- [GitHub Actions Best Practices](https://docs.github.com/en/actions/learn-github-actions/security-hardening-for-github-actions)
- [Docker Multi-stage Builds](https://docs.docker.com/build/building/multi-stage/)
- [Helm Chart Best Practices](https://helm.sh/docs/chart_best_practices/)

---

**Need help?** Check the documentation or open an issue.

**Ready to go?** Create your first PR and watch the magic happen! ✨
