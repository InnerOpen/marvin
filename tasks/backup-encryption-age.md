# Task: encrypt off-site backups with age (draft 2026-11-12)

Why: every backup target holds the DB dump, `.secret` and workspace bundles unencrypted. `.secret` decrypts every stored
credential, so a leaked backup token (or a read-only Cloudflare/NAS compromise) exposes all users, tokens, drafts and
provider keys (docs/manual/offsite-backup.md, "Every target holds the installation secret"). Today the only control is a
private bucket plus a one-bucket token. Goal: a stolen target is useless without an offline key.

## Design
- **Public-key encryption (age X25519).** The cluster holds only the *recipient* (public) key. The *identity* (private key)
  never touches the cluster: kept in `pass` + a paper/offline copy. A leaked bucket token AND a compromised backup pod
  still can't decrypt old backups.
- **Encrypt what is sensitive, not assets:** `postgres/*.dump`, `sqlite/*.gz`, `config/*.tar.gz`, `bundles/**/*.zip`
  become `<name>.age`. **Leave `assets/` plain**: the mirror compares size/MD5-ETag/sha256 per file to copy incrementally,
  encryption would re-upload everything each run, and the assets are already served publicly. Open question: drafts and
  private assets are also in `assets/`; decide whether private ones need an encrypted mirror (separate follow-up).
- **Multiple recipients** (`BACKUP_AGE_RECIPIENTS`, comma-separated) so a second key (spare/rotation) can be added; old
  backups stay readable by the key they were written for.
- **Fail closed:** if `BACKUP_AGE_RECIPIENTS` is set but encryption fails, the run fails (status `failed`), never uploads
  plaintext. If unset, behaviour is unchanged (opt-in), but Admin → Backup health shows "unencrypted" per target.
- **Library:** `pyrage` (Rust age bindings, no binary in the image) preferred; stream in chunks so a 100s-MB bundle isn't
  held in memory. Check licence and wheels for the backend image's Python/arch first.

## Work (src/marvin/services/backup_engine/engine.py, layout.py; scripts/backup.py)
1. Settings: `BackupSettings` gains `age_recipients` (parsed + validated at start; bad key = clear error).
2. Upload path: after the existing local integrity check (`pg_restore --list`, SQLite `integrity_check`, which must stay on
   plaintext before encrypting), encrypt to `<key>.age`, record the *plaintext* sha256 in the object metadata so restore can
   verify after decrypting (`_verify_sha`).
3. Layout/retention: `prune`, `latest_key`, `list_backups`, bundle pruning match `.age` suffixes (and plain, so a target
   mid-migration still prunes the old plaintext objects). Don't delete old plaintext until the first encrypted run is
   verified.
4. Restore: `restore --identity <file>` (or `BACKUP_AGE_IDENTITY` for the file path only, never the key value in env);
   decrypt to a temp file in `--into`, verify sha, then proceed as today. Missing identity on an `.age` key = clear message.
   `fetch_bundle` and the admin "Import" path for bundles the same.
5. `test` subcommand: also encrypt a tiny object and (if an identity is given) round-trip it.
6. Reports/Health: add `encrypted: true|false` to the run summary line, `backup_runs` row and Admin → Backup health.
7. Check `scripts/refresh_dev.py` and any code that reads dumps straight from a target; they must decrypt or be pointed at
   a plaintext source.
8. Docs: offsite-backup.md (new setting, key generation `age-keygen`, where to store the identity, restore example, what
   encryption does NOT cover: assets, and a compromised running cluster), chart values (`BACKUP_AGE_RECIPIENTS` via the
   target's `env`, not a Secret: it's public), whats-new.

## Rollout
- Generate keypair; identity into `pass` (`marvin/backup-age/identity`) + printed copy; recipient into chart values.
- Enable on dev's `marvin-backups-dev`-style target first; do a full `restore --identity` drill into a scratch dir and a
  Postgres `pg_restore` of the result before enabling in production.
- Then enable on the `r2` and NAS targets. After one verified encrypted run per target, delete plaintext
  `postgres/ config/ bundles/` objects older than the cutover (retention will age them out; delete sooner by hand since
  they are the exposure). Also rotate the existing `marvin/r2` token and, strictly, stored secrets, because old plaintext
  backups may have been readable for as long as the token existed.

## Tests
- Unit: encrypt/decrypt round trip, multi-recipient, wrong identity, truncated ciphertext, bad recipient string, large
  file streams without loading it all; fail-closed (no plaintext uploaded when encryption raises).
- Engine: encrypted run lists `.age` keys, prune keeps the right ones with mixed plain/`.age` objects, restore with/without
  identity, sha check after decrypt, `--dry-run` reports "would encrypt".

## Out of scope / later
- Encrypted mirror for private assets; Cloudflare R2 SSE-C; per-workspace backup keys (bundles already have Fernet-wrapped
  per-workspace keys: check how that interacts); signing backups.
