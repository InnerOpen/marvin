# Marvin Scripts

Utility scripts for seeding, migration, and maintenance.

## Seed Scripts

### `seed_mashandburnco.py`

**Idempotent seed script for Mash & Burn Co. content.**

Imports complete website content from the [mashandburnco repository](https://github.com/iWobble/mashandburnco) into Marvin as structured Entry data.

**Usage:**
```bash
uv run scripts/seed_mashandburnco.py
```

**What it does:**
- ✅ Creates `mash-and-burn-co` workspace
- ✅ Sets up 5 entry types (Page, Project, etc.)
- ✅ Creates 10 collections (Projects, Jackets, etc.)
- ✅ Imports 7 workshop projects with full metadata
- ✅ Imports 5 static pages
- ✅ Creates ~40 resources (materials, hardware)
- ✅ Creates ~7 asset metadata placeholders
- ✅ **Automatically creates API client token for Publishing API**

**Idempotent:**
- Run multiple times without duplicates
- Updates existing records
- Safe for development and testing

**Output:**
```
============================================================
✅ Seed complete!
============================================================

📝 API Client Token (save this!):
   marvin_sk_...

🧪 Test the Publishing API:
   curl -H "Authorization: Bearer marvin_sk_..." \
     http://localhost:8080/api/publish/mash-and-burn-co/entries
```

**Documentation:** See [docs/MASH-AND-BURN-SEED.md](../docs/MASH-AND-BURN-SEED.md)

> The Instagram integration used to be seeded by `seed_instagram_auto_reply.py`. It now declares its
> own content (entry types, collections, scheduled tasks) through the SDK, and the workspace applies
> it from the blueprint catalog after review — see `services/blueprints/`.

---

## Test Scripts

### `test_invitations.sh`

**End-to-end test for invitation system with workspace roles.**

Tests the complete invitation flow from token creation through user registration and role verification.

**Usage:**
```bash
./scripts/test_invitations.sh

# Or with custom settings
MARVIN_URL=http://localhost:8080 \
ADMIN_USER=admin \
ADMIN_PASS=MyPassword \
./scripts/test_invitations.sh
```

**What it tests:**
1. ✅ Creates invitation tokens for all 5 workspace roles
2. ✅ Validates API responses include `workspaceRole` field
3. ✅ Lists tokens and verifies roles
4. ✅ Registers test users with invitation tokens
5. ✅ Verifies workspace role assignment

**Test users created:**
- `viewer_test` (VIEWER) - password: TestPass123!
- `author_test` (AUTHOR) - password: TestPass123!
- `editor_test` (EDITOR) - password: TestPass123!
- `admin_test` (ADMIN) - password: TestPass123!
- `owner_test` (OWNER) - password: TestPass123!

**Environment variables:**
- `MARVIN_URL` - Backend URL (default: `http://localhost:8080`)
- `ADMIN_USER` - Admin username (default: `admin`)
- `ADMIN_PASS` - Admin password (default: `MyPassword`)

**Requirements:**
- `curl` and `jq` installed
- Marvin backend running
- Admin credentials

### `test_invitations_cli.sh`

**CLI-based end-to-end test for invitation system.**

Alternative to `test_invitations.sh` that uses the `marvin` CLI instead of direct curl commands. Better for testing the complete CLI workflow.

**Usage:**
```bash
./scripts/test_invitations_cli.sh

# With custom CLI path
MARVIN_CLI="marvin" ./scripts/test_invitations_cli.sh

# With local development CLI
MARVIN_CLI="node /path/to/marvin-cli/dist/index.js" ./scripts/test_invitations_cli.sh
```

**What it tests:**
1. ✅ Authenticates with marvin CLI
2. ✅ Creates invitation tokens using `marvin platform invites invite --role <ROLE> --json`
3. ✅ Lists invitations using `marvin platform invites list --json`
4. ✅ Validates CLI JSON output includes `workspaceRole` field
5. ✅ Registers test users and verifies roles

**Test users created:**
- `viewer_cli_test` (VIEWER) - password: TestPass123!
- `author_cli_test` (AUTHOR) - password: TestPass123!
- `editor_cli_test` (EDITOR) - password: TestPass123!
- `admin_cli_test` (ADMIN) - password: TestPass123!
- `owner_cli_test` (OWNER) - password: TestPass123!

**Environment variables:**
- `MARVIN_URL` - Backend URL (default: `http://localhost:8080`)
- `MARVIN_CLI` - CLI command or path (default: `marvin`)
- `ADMIN_USER` - Admin username (default: `admin`)
- `ADMIN_PASS` - Admin password (default: `MyPassword`)

**Requirements:**
- marvin CLI installed (`npm install -g @inneropen/marvin-cli@develop`) or local build
- `curl` and `jq` installed
- Marvin backend running

---

## Future Scripts

Additional seed scripts can be added here for:
- Development test data
- Demo content
- Customer-specific imports
- Migration utilities

Each script should be:
- Idempotent (safe to rerun)
- Well-documented
- Self-contained
- Logged clearly
