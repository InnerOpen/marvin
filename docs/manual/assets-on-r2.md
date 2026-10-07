# Assets on R2

Uploaded files (assets and character-library files) can live on Cloudflare R2, served from a public custom domain (`assets.iwobble.com`), instead of the `marvin-data` volume. This page is the runbook: what changes, the Cloudflare setup, the switch, and the rollback.

## How it works

- **Where new uploads go is an admin's choice.** **Admin → Storage** picks the provider for *new* uploads among the installed ones: local disk (built in, always there) or `s3` (the [`marvin-storage-s3`](https://github.com/InnerOpen/marvin-storage-s3) plugin, once its settings are present). `STORAGE_PROVIDER` is only the default until an admin chooses, so it stays `local` in the chart. You can switch back at any time; the change is recorded as `storage_provider_changed` on the admin Events page (platform scope, always audited).
- **Existing files never move on a switch.** Each asset row (and each character-library file) records the provider it lives in, and is served from there. Local and R2 files are served side by side, so a switch never breaks a URL.
- **Moving files is a separate, freeze-free step:** `python -m marvin.scripts.storage_migrate --to s3`. It copies each file, checks the copy's sha256, and only then repoints the row, in a short transaction that only applies if nothing else changed the row meanwhile. It is idempotent and resumable (interrupt it and run it again), and repeats passes until nothing is left, so files uploaded to the old provider while it runs are caught. It never deletes the local copy; `--prune-local` does that later, after downloading each R2 copy and comparing it with the local bytes. `--to local` is the rollback.
- **Old URLs keep working.** `/assets/<key>` on the API host (and the frontend's `/assets` proxy) redirects (302) to the file's new location when its row lives elsewhere, so `/assets/…` URLs pasted into entries or settings, or baked into sites built earlier, still resolve after `--prune-local`. Rebuild the sites anyway, so they link to `assets.iwobble.com` directly. Character URLs are worked out when they're read, from each file's provider.
- **If the plugin or its Secret disappears later,** new uploads fall back to `STORAGE_PROVIDER` (local) instead of the app refusing to start, with a `CRITICAL` line in the backend log at startup and a red warning on Admin → Storage. That fallback is safe because every new row records where it was actually stored. Files already on R2 can't be served until the plugin is back. `STORAGE_PROVIDER` itself is still checked strictly at startup: an unknown value stops the backend, as before.
- **Backups:** a backup target mirrors assets from local disk and from every provider listed in `BACKUP_ASSET_PROVIDERS`, so set `BACKUP_ASSET_PROVIDERS=s3` on both targets (below). R2 to R2 (`marvin-assets` → `marvin-backups`) is kept on purpose: R2's durability doesn't cover an asset deleted in Marvin, a bug or a leaked assets token, and the backup bucket keeps every asset it ever saw. The NAS target is the copy that doesn't depend on Cloudflare. Keys and digests are the same on both sides, so the first run after the move uploads nothing new (`assets 0 uploaded, 516 unchanged`).

## Cloudflare checklist (Jared)

For each environment: production `marvin-assets` + `assets.iwobble.com`, dev `marvin-assets-dev` + `assets-dev.iwobble.com`.

1. **Buckets.** R2 → **Create bucket** → name `marvin-assets`, location *Automatic*, storage class *Standard*. Repeat for `marvin-assets-dev`. Leave the bucket's **Public Development URL** (`r2.dev`) **disabled**.
2. **API tokens.** R2 → **Manage API tokens** → **Create API token**: permission **Object Read & Write**, **Specify bucket(s)** → only `marvin-assets` (production). Create a second token for `marvin-assets-dev` (dev). Note each token's *Access Key ID* and *Secret Access Key* (shown once) and the account's S3 endpoint `https://<account-id>.r2.cloudflarestorage.com`.
    - *Why new tokens instead of extending the backup token:* the assets token lives in the backend pods (the most exposed part); if it could also write `marvin-backups`, a leak could delete the backups too. Extending the existing token (R2 → Manage API tokens → the backup token → add the two buckets) works technically, but it mixes the two blast radii.
3. **Custom domain.** R2 → `marvin-assets` → **Settings** → **Custom Domains** → **Connect Domain** → `assets.iwobble.com` → confirm the DNS record Cloudflare proposes (a proxied CNAME in the `iwobble.com` zone) → wait for status **Active**. Repeat with `marvin-assets-dev` → `assets-dev.iwobble.com`. Check: `curl -sI https://assets.iwobble.com/` answers (a 404 for the bare root is fine).
4. **Caching.** Nothing to set up: the custom domain is cached by Cloudflare. The plugin's `STORAGE_S3_CACHE_CONTROL` (below) gives every object `Cache-Control: public, max-age=86400`.
5. **CORS: not needed.** Images, video and links don't use CORS, MarvinAstro only embeds URLs, the admin's canvas drawing never reads pixels back, and mashandburnco already avoids CSS `mask` on CMS URLs. Add a rule (GET/HEAD from the sites' origins) only if a page ever `fetch()`es an asset.
6. **Usage alert** (already on the cost checklist): R2 alert at about 5 GB.

## Switching (dev first, then production)

The code must be deployed first (this release), with `marvin-storage-s3` in `plugins.packages` (it already is). Commands are for production (`-n marvin`); dev is the same with `-n marvin-dev`, `marvin-assets-dev` and `assets-dev.iwobble.com`.

**1. Secret** (once per namespace; the plugin's own variable names):

```bash
oc -n marvin create secret generic marvin-r2-assets \
  --from-literal=STORAGE_S3_ACCESS_KEY='<access key id>' \
  --from-literal=STORAGE_S3_SECRET_KEY='<secret access key>' \
  --from-literal=STORAGE_S3_ENDPOINT='https://<account id>.r2.cloudflarestorage.com' \
  --from-literal=STORAGE_S3_BUCKET='marvin-assets'
```

**2. Values** (`values-iwobble.yaml`; dev: `values-dev.yaml` with `assets-dev.iwobble.com`). `STORAGE_PROVIDER` stays `local`. Keep `STORAGE_LOCAL_PUBLIC_BASE_URL`: rows on local disk still use it.

```yaml
extraEnv:
  # … the existing entries stay …
  - name: STORAGE_REMOTE_PUBLIC_URL
    value: https://assets.iwobble.com
  - name: STORAGE_S3_CACHE_CONTROL
    value: "public, max-age=86400"
  - {name: STORAGE_S3_BUCKET, valueFrom: {secretKeyRef: {name: marvin-r2-assets, key: STORAGE_S3_BUCKET}}}
  - {name: STORAGE_S3_ENDPOINT, valueFrom: {secretKeyRef: {name: marvin-r2-assets, key: STORAGE_S3_ENDPOINT}}}
  - {name: STORAGE_S3_ACCESS_KEY, valueFrom: {secretKeyRef: {name: marvin-r2-assets, key: STORAGE_S3_ACCESS_KEY}}}
  - {name: STORAGE_S3_SECRET_KEY, valueFrom: {secretKeyRef: {name: marvin-r2-assets, key: STORAGE_S3_SECRET_KEY}}}

backup:
  targets:
    - name: r2
      # … as now …
      env: &assetsFromR2
        - {name: BACKUP_ASSET_PROVIDERS, value: s3}
        - {name: STORAGE_S3_BUCKET, valueFrom: {secretKeyRef: {name: marvin-r2-assets, key: STORAGE_S3_BUCKET}}}
        - {name: STORAGE_S3_ENDPOINT, valueFrom: {secretKeyRef: {name: marvin-r2-assets, key: STORAGE_S3_ENDPOINT}}}
        - {name: STORAGE_S3_ACCESS_KEY, valueFrom: {secretKeyRef: {name: marvin-r2-assets, key: STORAGE_S3_ACCESS_KEY}}}
        - {name: STORAGE_S3_SECRET_KEY, valueFrom: {secretKeyRef: {name: marvin-r2-assets, key: STORAGE_S3_SECRET_KEY}}}
    - name: nas-nightly          # production only
      # … as now …
      env: *assetsFromR2
```

Upgrade (production through `promote-iwobble.sh`). The backend restarts; uploads still go to local. Check: **Admin → Storage** lists *S3-compatible* `s3` as available (no "unavailable" note), and the backend log has `Storage: new uploads go to 'local' (STORAGE_PROVIDER)`.

**3. Before switching:** run a backup (`oc -n marvin create job --from=cronjob/marvin-backup-r2 marvin-r2-pre-s3`, wait, check the summary line). Optional: look for asset URLs typed into content (they keep working through the redirect; this only tells you what the redirect is carrying):

```bash
oc -n marvin exec -i deploy/marvin-backend -c backend -- python - <<'EOF'
from marvin.db.db_setup import session_context
import sqlalchemy as sa
with session_context() as s:
    for table, col in [("entries", "data_json"), ("entries", "metadata_json"), ("group_preferences", "site_logo"),
                       ("group_preferences", "site_favicon"), ("group_preferences", "site_metadata_json")]:
        try:
            n = s.execute(sa.text(f"select count(*) from {table} where cast({col} as text) like '%/assets/%'")).scalar()
            print(table, col, n)
        except Exception as e:
            s.rollback(); print(table, col, "n/a")
EOF
```

**4. Switch new uploads:** **Admin → Storage** → *S3-compatible (R2, AWS S3, MinIO, B2)* → **Save**. Upload a test image in any workspace: its *File Info* says *Stored on `s3`* and *View Full Size* opens `https://assets.iwobble.com/…`.

**5. Move the existing files** (in the backend pod: it has the plugin, the database and `marvin-data`):

```bash
oc -n marvin exec deploy/marvin-backend -c backend -- python -m marvin.scripts.storage_migrate --to s3 --dry-run
oc -n marvin exec deploy/marvin-backend -c backend -- python -m marvin.scripts.storage_migrate --to s3 --verify
```

Expect the last line to be like `to s3: copied 516 (… MB), 0 already there, 516 asset rows moved, N library files moved, 0 changed meanwhile, 0 failed, 1 pass` and exit status 0. If a file failed, the line says so and the run exits 1: fix the cause and run the same command again (it picks up where it stopped). A second run must report `copied 0 … 0 passes`. `--workspace <slug>` moves one workspace's assets first if you'd rather go in steps; library files move in a full run.

**6. Check:** Admin → Storage shows 0 assets on local disk; spot-check a few assets (the URL is on `assets.iwobble.com`, the image loads); an old URL `https://api.iwobble.com/assets/<key>` still answers 200 (the local copy is still there).

**7. Rebuild the sites** (GraceMartinFranklin, mashandburnco: their Cloudflare Pages deploy, or Marvin's *Rebuild site*), then check that their images load from `assets.iwobble.com`.

**8. Watch:** the next `marvin-backup-r2` and `marvin-backup-nas-nightly` runs end `ok` with `assets 0 uploaded, … unchanged`; the backend log has no `storage:` errors.

**9. Later** (a set period after the move, e.g. 30 days, and only after a restore test that includes assets):

```bash
oc -n marvin exec deploy/marvin-backend -c backend -- python -m marvin.scripts.storage_migrate --prune-local --dry-run
oc -n marvin exec deploy/marvin-backend -c backend -- python -m marvin.scripts.storage_migrate --prune-local
```

It deletes only local copies whose R2 copy it downloaded and found identical; anything else is listed and kept. Old `/assets/` URLs then redirect to R2.

## Rollback

1. **Admin → Storage → Local disk → Save.** New uploads go to `marvin-data` again at once.
2. If files should come back too: `storage_migrate --to local --verify` (same `oc exec` as above). Until `--prune-local` has run, every file's local copy is still there, so this only repoints rows (`… already there`); after a prune it downloads them from R2.
3. Rebuild the sites, so they link to the API host again. Keep the custom domain up until they have.
4. Leave the plugin settings in place (they're harmless), or remove the `extraEnv` / `env` entries and the Secret once no row is on `s3` (Admin → Storage shows 0).

## Copying production to dev afterwards

Once production's assets live in `marvin-assets`, a copy of production's database into dev brings rows that say `s3` with keys in production's bucket, which dev's settings (`marvin-assets-dev`) don't hold, so those images break in dev. When refreshing dev from production, also copy the objects into dev's bucket (for example `rclone sync r2:marvin-assets r2:marvin-assets-dev` with a token that can read the one and write the other), or run dev's refresh before production's move.

## Reference

- `python -m marvin.scripts.storage_migrate --to PROVIDER [--dry-run] [--workspace SLUG] [--batch N] [--verify]`, or `--prune-local [--dry-run] [--workspace SLUG]`. `--batch` sets how often progress is logged. Exit status 0 when everything moved, 1 when any file failed (the rest still moved), 2 for a provider that can't take files or an unknown workspace.
- Plugin settings: `STORAGE_S3_BUCKET` (required), `STORAGE_S3_ENDPOINT`, `STORAGE_S3_REGION` (default `auto`), `STORAGE_S3_ACCESS_KEY`, `STORAGE_S3_SECRET_KEY`, `STORAGE_S3_PREFIX`, `STORAGE_REMOTE_PUBLIC_URL` (the custom domain; without it, asset URLs are presigned and expire, which breaks built sites), `STORAGE_S3_PRESIGN_SECONDS`, `STORAGE_S3_CACHE_CONTROL`. See the plugin's README.
- Backups: `BACKUP_ASSET_PROVIDERS` (comma-separated) on a target adds providers to the asset mirror; local disk and `STORAGE_PROVIDER` are always read. A provider that can't be opened fails only the asset step (the database and config backups still run). See [Off-site backup](offsite-backup.md).
