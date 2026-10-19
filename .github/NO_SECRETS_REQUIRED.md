# No Manual Secrets Required! 🎉

## TL;DR

**The Marvin server CI/CD pipeline requires ZERO manual secret configuration.**

GitHub Actions automatically provides everything needed.

## What You DON'T Need to Configure

### ❌ NPM_TOKEN
- **Not needed**: The Marvin server is a Python backend, not an npm package
- **Where it IS needed**: SDK and CLI repos (they handle their own publishing)

### ❌ GHCR_TOKEN
- **Not needed**: `GITHUB_TOKEN` (auto-provided) has sufficient permissions
- **Only if**: You encounter permission issues (extremely rare)

### ❌ PyPI Token
- **Not needed**: We're not publishing to PyPI (yet)
- **Future**: Will add when/if we publish the Marvin server to PyPI

## What GitHub Provides Automatically

### ✅ GITHUB_TOKEN

**Automatically provided** by GitHub Actions for every workflow run.

**Used for**:
- Publishing Docker images to GitHub Container Registry (ghcr.io)
- Creating GitHub Releases
- Packaging Helm charts
- Accessing SDK/CLI repos for testing

**Permissions configured per workflow**:
```yaml
permissions:
  contents: write      # Create releases, tags
  packages: write      # Publish Docker images
  id-token: write      # OIDC tokens
```

## Why This Matters

### Before (Complicated)
1. Generate npm token
2. Add to GitHub secrets
3. Configure in workflow
4. Worry about token expiration
5. Rotate tokens regularly

### After (Simple)
1. Push code
2. That's it! ✨

## Repository Breakdown

### This Repo (InnerOpen/marvin)
- **Language**: Python (FastAPI)
- **Publishes**: Docker images, Helm charts
- **Secrets needed**: None (GITHUB_TOKEN is auto-provided)
- **Setup time**: 0 minutes

### SDK Repo (InnerOpen/marvin-sdk)
- **Language**: TypeScript
- **Publishes**: @inneropen/marvin-sdk to npm
- **Secrets needed**: NPM_TOKEN (configured in SDK repo)
- **Setup time**: 2 minutes (one-time)

### CLI Repo (InnerOpen/marvin-cli)
- **Language**: TypeScript
- **Publishes**: @inneropen/marvin-cli to npm
- **Secrets needed**: NPM_TOKEN (configured in CLI repo)
- **Setup time**: 2 minutes (one-time)

## How to Get Started

### Step 1: Push Code
```bash
git push origin main
```

### Step 2: Watch Magic Happen
Go to Actions tab and watch workflows run.

### Step 3: There is no step 3
Everything just works! 🎉

## What Gets Published

When you push to `main`:

1. **Semantic Release** analyzes your commits
2. **Version bumps** if changes warrant it
3. **Docker image** built and pushed to ghcr.io
4. **Helm chart** packaged and attached to GitHub Release
5. **CHANGELOG** updated automatically
6. **Git tag** created with release notes

All without any manual secret configuration!

## FAQ

### Q: Do I need an npm account?
**A**: Not for the Marvin server repo. Only SDK/CLI repos need npm tokens.

### Q: Do I need a Docker Hub account?
**A**: No. We publish to GitHub Container Registry (ghcr.io), which uses your GitHub account.

### Q: What if I want to publish to PyPI later?
**A**: Add `PYPI_TOKEN` secret when needed. Not required now.

### Q: Why does the documentation mention NPM_TOKEN?
**A**: Only to explain that SDK/CLI repos handle their own publishing. It's not a requirement for this repo.

### Q: Can I test workflows without pushing?
**A**: Yes! Use [act](https://github.com/nektos/act) to run workflows locally:
```bash
brew install act
act pull_request -W .github/workflows/pr-ci.yml
```

### Q: How do I verify GITHUB_TOKEN works?
**A**: It's auto-provided and automatically works. No verification needed. Just push code.

## Troubleshooting

### "Permission denied" when publishing Docker image

**Cause**: Repository is private and GITHUB_TOKEN lacks package permissions

**Fix**: Workflows already configured with correct permissions. Should work automatically.

### "Secret not found"

**Cause**: Typo in workflow file referencing a secret

**Fix**: All workflows reference only `GITHUB_TOKEN` which is auto-provided. Check for typos.

### SDK/CLI not publishing

**Cause**: Those repos have their own workflows

**Solution**: Configure `NPM_TOKEN` in those repos, not this one.

## Summary

| Component | Repository | Publishes To | Secrets Needed |
|-----------|------------|--------------|----------------|
| **Backend** | marvin | GHCR + GitHub Releases | ✅ None |
| **SDK** | marvin-sdk | npm | NPM_TOKEN (in SDK repo) |
| **CLI** | marvin-cli | npm | NPM_TOKEN (in CLI repo) |

**Bottom line**: The Marvin server repository needs **zero manual secret setup**. Just push and let GitHub Actions handle everything!

---

**Still have questions?** Check:
- `.github/QUICKSTART.md` - 5-minute setup guide
- `.github/SECRETS.md` - Detailed secrets documentation
- `.github/WORKFLOWS.md` - Workflow explanations
- `docs/archive/CI_CD_IMPLEMENTATION.md` - Complete implementation guide
