# Semantic Versioning Setup Summary

## Overview

Semantic versioning has been added to the Marvin CMS server using **Python Semantic Release**, following the same pattern as `marvin-sdk` and `marvin-cli`.

## What Was Added

### 1. Configuration Files

#### `pyproject.toml` (updated)
- Added `[tool.semantic_release]` configuration section
- Added `python-semantic-release>=9.17.0` to dev dependencies
- Configured version source locations:
  - `pyproject.toml:project.version`
  - `src/marvin/__init__.py:__version__`
- Set up branch-specific release strategies:
  - `main` → stable releases (`v1.0.0`)
  - `develop` → prerelease versions (`v1.0.0-next.1`)

#### `.github/workflows/release.yml` (new)
- Automated GitHub Actions workflow
- Triggers on push to `main` or `develop`
- Runs `python-semantic-release` to:
  - Analyze commits
  - Bump version
  - Update CHANGELOG
  - Create git tag
  - Create GitHub Release

#### `CHANGELOG.md` (new)
- Auto-generated changelog
- Organized by release version
- Grouped by commit type (features, fixes, etc.)

#### `RELEASE_PROCESS.md` (new)
- Complete documentation of the release process
- Examples of conventional commits
- Workflow examples
- Troubleshooting guide

## How It Works

### Automatic Versioning

Version bumps are determined by commit messages:

```bash
# Patch bump (0.2.0 → 0.2.1)
git commit -m "fix: resolve bug in workspace permissions"

# Minor bump (0.2.0 → 0.3.0)
git commit -m "feat: add user export feature"

# Major bump (0.2.0 → 1.0.0)
git commit -m "feat!: migrate to new auth system"
# or
git commit -m "feat: new auth system

BREAKING CHANGE: Old tokens are no longer valid"
```

### Branch Strategy

- **`main` branch**: Stable releases
  - Example: `v1.0.0`, `v1.1.0`, `v1.2.0`

- **`develop` branch**: Preview/beta releases
  - Example: `v1.0.0-next.1`, `v1.1.0-next.2`

### Workflow

1. Developer commits using conventional commit format
2. Developer pushes to `main` or `develop`
3. GitHub Actions automatically:
   - Analyzes commits since last release
   - Determines version bump
   - Updates `pyproject.toml` and `__init__.py`
   - Generates/updates `CHANGELOG.md`
   - Creates git tag
   - Creates GitHub Release with notes
   - Commits changes back with `[skip ci]`

## Alignment with SDK and CLI

This setup mirrors `marvin-sdk` and `marvin-cli`:

| Feature | marvin-sdk | marvin-cli | marvin (server) |
|---------|------------|------------|-----------------|
| Tool | semantic-release | semantic-release | python-semantic-release |
| Language | TypeScript | TypeScript | Python |
| Branch Strategy | ✅ main/develop | ✅ main/develop | ✅ main/develop |
| Prerelease | `@next` tag | `@next` tag | `-next.N` suffix |
| Changelog | ✅ Auto | ✅ Auto | ✅ Auto |
| GitHub Actions | ✅ | ✅ | ✅ |
| Conventional Commits | ✅ | ✅ | ✅ |

## Key Differences from SDK/CLI

1. **Language-specific tooling**:
   - SDK/CLI use `semantic-release` (Node.js)
   - Server uses `python-semantic-release` (Python)

2. **Version storage**:
   - SDK/CLI: `package.json`
   - Server: `pyproject.toml` + `__init__.py`

3. **Publishing**:
   - SDK/CLI: npm registry
   - Server: GitHub Releases only (no PyPI)

## Next Steps

### To Start Using

1. **Install dev dependencies**:
   ```bash
   pip install -e ".[dev]"
   ```

2. **Make changes using conventional commits**:
   ```bash
   git commit -m "feat: your new feature"
   git commit -m "fix: your bug fix"
   ```

3. **Push to trigger release**:
   ```bash
   # For preview release
   git push origin develop

   # For stable release
   git push origin main
   ```

### To Test Locally

```bash
# Dry run (see what would happen)
semantic-release version --dry-run

# Actually create version
semantic-release version

# Publish release
semantic-release publish
```

## Configuration Reference

### Version Locations

1. **pyproject.toml**:
   ```toml
   [project]
   version = "0.2.0"
   ```

2. **src/marvin/__init__.py**:
   ```python
   __version__ = "0.2.0"
   ```

Both are kept in sync automatically by python-semantic-release.

### Commit Types and Version Impact

| Type | Version Bump | Example |
|------|--------------|---------|
| `fix:` | Patch | `fix: resolve email template bug` |
| `feat:` | Minor | `feat: add workspace templates` |
| `feat!:` or `BREAKING CHANGE:` | Major | `feat!: remove legacy API` |
| `docs:`, `chore:`, etc. | None | No release triggered |

## Verification

After setup, verify with:

```bash
# Check configuration
semantic-release --version

# Dry run to see next version
semantic-release version --dry-run

# Check current version
grep "^version" pyproject.toml
grep "__version__" src/marvin/__init__.py
```

## References

- [Python Semantic Release Docs](https://python-semantic-release.readthedocs.io/)
- [Conventional Commits Spec](https://www.conventionalcommits.org/)
- [Semantic Versioning](https://semver.org/)
- marvin-sdk: `.releaserc.json` and workflow
- marvin-cli: `.releaserc.json` and workflow
