# Off-site backup

Marvin's own **Backups** (see [Operations → Backups](operations.md#backups)) export one workspace's content at a time. They leave out users, API clients and tokens, the installation secret, event and execution logs, and they live on the same volume as the data. The off-site backup covers the whole installation: a nightly CronJob in the Helm chart copies the database, the installation secret and the uploaded files to an S3-compatible bucket off the cluster (Cloudflare R2, MinIO or AWS S3). The work is done by `python -m marvin.scripts.offsite_backup`, which ships in the backend image.

## What is backed up

| Object | Contents |
|---|---|
| `sqlite/marvin-<UTC YYYYmmddTHHMMSSZ>.db.gz` | the SQLite database, copied with SQLite's online backup API while the backend runs, checked with `PRAGMA integrity_check`, then gzipped. A copy that fails the check is not uploaded. |
| `postgres/marvin-<UTC stamp>.dump` | with `dbEngine: postgres`, instead of `sqlite/`: a `pg_dump --format=custom` of the app's database, read back with `pg_restore --list` before upload. See [Postgres](#postgres). |
| `config/marvin-config-<UTC stamp>.tar.gz` | `.secret`, `scheduler_state.json` and `templates/` (custom email templates) from `DATA_DIR` |
| `assets/<path>` | every file under `DATA_DIR/assets`, mirrored incrementally: a file is uploaded when its key is missing or its size or MD5 (the object's ETag) differs. Remote assets are never deleted, so a file deleted in Marvin stays in the bucket. |

The database and config objects carry a `sha256` of the object in their metadata, and the database also a `db-sha256` of the uncompressed file; restore checks both. Logs, `.temp`, `backups/`, the `marvin.db.pre-*` snapshots and the live `marvin.db-wal` / `marvin.db-shm` are not backed up. The copy is consistent: one read transaction covers the whole database, so writes made during the backup are either all in it or all left out.

!!! danger "The bucket holds the installation secret"
    `.secret` is the key that decrypts every secret Marvin stores (workspace secrets, provider keys, integration credentials). It has to be backed up, or encrypted values are unreadable after a restore, but it means anyone who can read the bucket can read those secrets. Keep the bucket private, give the backup a token scoped to that one bucket (on R2: an **Object Read & Write** API token limited to the bucket), keep the token out of Git, and treat a leaked token as leaking the secrets: rotate the token and the stored secrets.

## Retention

After a successful upload, older `sqlite/` (or `postgres/`, which also keeps the newest of each of the last 48 hours) and `config/` objects are pruned: the run keeps the newest backup of each of the last 14 days that have one, plus the newest of each of the last 8 ISO weeks, and deletes the rest. Days and weeks are counted among those that have a backup, not back from today, so a run of failed nights never empties the bucket. A prefix is pruned only when that night's upload to it succeeded. Keys the script did not name (for example a manually uploaded `sqlite/before-cutover.db.gz`) and everything under `assets/` are never deleted.

Two backups on the same day (a one-off run after the nightly one) keep only the newer.

The counts are `backup.retention.hourly` / `.daily` / `.weekly` in the chart (`BACKUP_KEEP_HOURLY` / `_DAILY` / `_WEEKLY`); a key left out keeps the default above; 0 turns the hourly or weekly rule off (daily must be at least 1, so a run never prunes the backup it just made). Dev keeps 24 hourly + 7 daily and nothing weekly (`values-dev.yaml`); production uses the defaults.

## Enabling it

1. Create the bucket and a token that can read, write and delete objects in it.
2. Create a Secret in the release's namespace with exactly these keys. The chart never renders it.

    ```bash
    oc -n marvin create secret generic marvin-r2-backup \
      --from-literal=AWS_ACCESS_KEY_ID='<access key id>' \
      --from-literal=AWS_SECRET_ACCESS_KEY='<secret access key>' \
      --from-literal=BACKUP_S3_ENDPOINT='https://<account id>.r2.cloudflarestorage.com' \
      --from-literal=BACKUP_S3_BUCKET='marvin-backups'
    ```

3. Turn it on in the values file and upgrade the release:

    ```yaml
    backup:
      enabled: true
      existingSecret: marvin-r2-backup
      timeZone: America/New_York   # optional; empty reads the schedule in the controller's zone (UTC)
    ```

| Value | Default | Notes |
|---|---|---|
| `backup.enabled` | `false` | needs `persistence.enabled` |
| `backup.schedule` | `15 3 * * *` | cron syntax |
| `backup.timeZone` | empty | an IANA zone; needs Kubernetes 1.27+ |
| `backup.existingSecret` | empty | required when enabled; the keys above |
| `backup.s3Region` | `auto` | right for R2; the bucket's region for AWS |
| `backup.activeDeadlineSeconds` | `3600` | a run (including time spent Pending) is failed after this |
| `backup.startingDeadlineSeconds` | `3600` | a run that could not start this long after its slot is skipped |
| `backup.resources` | 50m / 128Mi requested, 500m / 512Mi limit | |

The CronJob is `<release>-offsite-backup` and runs the backend image at the backend's tag (`concurrencyPolicy: Forbid`, `backoffLimit: 2`, the last 3 successful and 3 failed jobs kept). The data volume is ReadWriteOnce and SQLite's WAL index is shared memory, so the pod is scheduled onto the backend pod's node (required pod affinity). If no backend pod is running, the job stays Pending and fails at `activeDeadlineSeconds`. It mounts the volume read-write, because a reader of a WAL-mode database takes its locks in `marvin.db-shm`, but opens the database read-only and writes nothing else there; it stages the snapshot in an `emptyDir` at `/tmp` (about 1.2 times the database size).

## Running a one-off backup

```bash
oc -n marvin create job --from=cronjob/marvin-offsite-backup marvin-offsite-backup-manual-$(date +%Y%m%d%H%M)
oc -n marvin logs -f job/marvin-offsite-backup-manual-<stamp>
```

The last line of every run is a one-line summary, for example `offsite-backup ok: db 48.2 MB -> 9.1 MB gz (sqlite/marvin-20261007T071500Z.db.gz), config 3 item(s), assets 2 uploaded (1.4 MB), 311 unchanged, pruned 1, 6.2s`. A failed step is listed after `FAILED`, the other steps still run, and the job exits non-zero, so it shows as failed in `oc get jobs`. Credentials are never logged.

To see what a run would do without uploading or deleting anything, run the script with `--dry-run` from a machine that has the credentials in its environment (see the reference below).

## Checking backups

```bash
oc -n marvin get cronjob,jobs -l app.kubernetes.io/component=backup
oc -n marvin logs job/<latest job> | tail -1
```

From a checkout with the credentials exported, `python -m marvin.scripts.offsite_backup list` prints every database and config object with its size. A backup is only proven by restoring it; restore one into a scratch directory now and then.

## Restoring

`restore` downloads the chosen database object (default: the newest), checks both checksums and `integrity_check` before it touches the target, then the config archive, then any assets missing or different locally. It never deletes local files. Into a directory that already has `marvin.db` or `.secret` it refuses unless given `--force`, and with `--force` it moves the existing `marvin.db`, `marvin.db-wal`, `marvin.db-shm`, `.secret`, `scheduler_state.json` and `templates/` aside as `<name>.pre-restore-<stamp>` rather than overwriting them. Moving the `-wal` aside matters: left beside a restored database, SQLite would replay it onto that database.

### Into a scratch directory

To inspect a backup or rehearse a restore, from a checkout:

```bash
export BACKUP_S3_ENDPOINT=... BACKUP_S3_BUCKET=marvin-backups AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=...
PYTHONPATH=src uv run python -m marvin.scripts.offsite_backup list
PYTHONPATH=src uv run python -m marvin.scripts.offsite_backup restore --target ./restored \
  [--db-key sqlite/marvin-20261006T071500Z.db.gz] [--config-key config/marvin-config-20261006T071500Z.tar.gz] [--skip-assets]
```

`./restored` is then a data directory: point `DATA_DIR` at it to run Marvin against the copy.

### Into the cluster

`--force` is safe only while no backend process has the database open: replacing it under a running backend corrupts it. Stop the backend first.

1. Stop the backend and pause the schedule:

    ```bash
    oc -n marvin scale deploy/marvin-backend --replicas=0   # combined mode: deploy/marvin
    oc -n marvin patch cronjob marvin-offsite-backup -p '{"spec":{"suspend":true}}'
    oc -n marvin get pods   # wait until the backend pod is gone
    ```

2. Run the restore as a Job made from the CronJob, with the arguments swapped and the pod affinity dropped (there is no backend pod to sit beside now):

    ```bash
    oc -n marvin create job --from=cronjob/marvin-offsite-backup marvin-restore --dry-run=client -o json \
      | jq '.spec.template.spec.containers[0].args = ["restore", "--target", "/app/data", "--force"]
            | del(.spec.template.spec.affinity)' \
      | oc apply -f -
    oc -n marvin logs -f job/marvin-restore
    ```

    Add `"--db-key", "sqlite/marvin-<stamp>.db.gz"` (and `"--config-key", ...`) to restore an older backup than the newest.

3. Start the backend and resume the schedule, then check it serves (`/healthz`, a login, a page with images):

    ```bash
    oc -n marvin scale deploy/marvin-backend --replicas=1
    oc -n marvin patch cronjob marvin-offsite-backup -p '{"spec":{"suspend":false}}'
    oc -n marvin delete job marvin-restore
    ```

4. Once satisfied, delete the `*.pre-restore-*` files from the volume. Until then they are the way back.

A `helm upgrade` resets the CronJob's `suspend` to the chart's value, so resume it explicitly or the next upgrade will.

To bring back only lost uploads, restore the assets alone. This needs no `--force` and the backend can keep running: `["restore", "--target", "/app/data", "--skip-db", "--skip-config"]`.

## Postgres

The backup is engine-aware through `DB_ENGINE`, which the CronJob reads from the release's ConfigMap. With `dbEngine: sqlite` it backs up the SQLite file as above. With `dbEngine: postgres` the database part is a `pg_dump --format=custom` of the app's database, taken with the same `POSTGRES_*` connection the backend uses (the chart passes them from the connection Secret; the script hands them to `pg_dump` as `PG*` environment variables, never on the command line), checked with `pg_restore --list`, and uploaded as `postgres/marvin-<stamp>.dump`. This dump **is** the Postgres backup — there is no WAL archiving or point-in-time recovery, by choice — so a Postgres release runs the job hourly (`backup.schedule: "0 * * * *"`), and `postgres/` keeps the newest of each of the last 48 hours on top of the 14 daily + 8 weekly rule. See [Postgres → Backups](postgres.md#backups), including the restore test.

`restore` with `DB_ENGINE=postgres` (or a `--db-key postgres/...`) downloads and verifies the dump as `<target>/marvin.dump`; it never loads it. Load it deliberately with `pg_restore`.

`pg_dump` comes from the backend image's `postgresql-client` (Debian's, major 17). A dump only restores cleanly with a `pg_restore` at least as new, into a server of the same major or newer, which is why the clusters run Postgres 17.

## Environments

Each environment has its own bucket: production `marvin-backups`, dev `marvin-backups-dev` (`BACKUP_S3_BUCKET` in each namespace's `marvin-r2-backup` Secret). One R2 token covers both, by choice — the buckets separate the objects and their retention, not the permissions. `backup.prefix` (`BACKUP_S3_PREFIX`) can also put every key of a release under a prefix in a shared bucket (listing, retention and restore then work relative to it); nothing uses it today.

## Backup targets

The off-site job above is being replaced by the **backup engine** (`python -m marvin.scripts.backup`, also in the backend image), which writes the same objects (`postgres/` or `sqlite/`, `config/`, `assets/`) to a list of independent **targets**. Each target has its own schedule, retention, run and exit code, so a failing NAS never stops the R2 run and the other way round. Until the cutover both run side by side: `backup.enabled` keeps the `marvin-offsite-backup` CronJob described above, and `backup.targets[]` adds one CronJob `<release>-backup-<name>` per target.

A target's `type` is the built-in `local` (a directory on a volume of its own, for example the NAS) or a storage plugin's target slug (for example `s3` from `marvin-storage-s3`, installed through `plugins.packages`, which the target CronJobs get too). Production has one target today:

```yaml
backup:
  targets:
    - name: nas-nightly                       # CronJob marvin-backup-nas-nightly
      type: local
      schedule: "30 2 * * *"
      timeZone: America/New_York
      retention: {hourly: 0, daily: 30, weekly: 8}
      volume:
        nfs: {server: 192.168.30.10, path: /tank/backups/marvin}   # static PV + PVC from the chart
        subPath: prod                         # the target root inside the export; dev would use dev/
```

- **Retention** (`retention.hourly` / `.daily` / `.weekly` → `BACKUP_KEEP_*`) follows the rule under [Retention](#retention), with the engine's defaults: 48 hourly, 30 daily, 0 weekly. `hourly` counts database backups (`postgres/`, `sqlite/`). The NAS keeps the newest backup of each of the last 30 days that have one plus the newest of each of the last 8 weeks. A one-off run on the same day replaces that day's nightly backup.
- **Volume** (`local` only): `volume.existingClaim`, or `volume.nfs: {server, path}`, from which the chart renders a static PersistentVolume `<namespace>-<release>-backup-<name>` (ReadWriteMany, `Retain`, `storageClassName: ""`, mount options `hard,nfsvers=4.2`, `claimRef` to the PVC) and the PVC `<release>-backup-<name>`. It has to be a PV, because OpenShift's `restricted-v2` SCC doesn't allow inline `nfs:` volumes. `volume.subPath` picks a directory inside the volume, which the kubelet creates on the first run. The volume is mounted at `/backup-target` (`BACKUP_LOCAL_ROOT`).
- **Guardrails:** `helm template` fails when a local target has no volume or points at the data volume (`marvin-data`, `<release>-data` or `persistence.existingClaim`). At runtime the engine also refuses a target directory inside `DATA_DIR` or on the same filesystem as it, and a directory that doesn't exist (a missing mount mustn't fill the container's disk).
- **Plugin targets** take their settings from `existingSecret` (every key becomes an environment variable) and `env`. They take no `volume`.
- Other keys: `prefix` (`BACKUP_PREFIX`), `activeDeadlineSeconds` and `startingDeadlineSeconds` (default 3600 each), `resources` (default `backup.resources`). The chart's `values.yaml` lists them all.

!!! warning "The NAS shares a pool with the live data"
    The export `/tank/backups/marvin` (ZFS dataset `tank/backups` on `pve`, 50 GB quota) is in the same `tank` pool as `managed-nfs-storage`. The NAS copy covers a deleted or corrupted PVC and app bugs, not losing the NAS. R2 remains the off-site copy. Like the bucket, the NAS export holds `.secret`. The export squashes every client to uid 3100 (`all_squash`), which owns it at mode 0770, so any pod UID can write. Any host in the export's client range (`192.168.50.0/25`, the cluster nodes) can mount it.

### Running and checking a target

```bash
oc -n marvin get cronjob marvin-backup-nas-nightly
oc -n marvin create job --from=cronjob/marvin-backup-nas-nightly marvin-nas-now
oc -n marvin wait --for=condition=complete job/marvin-nas-now --timeout=30m
oc -n marvin logs job/marvin-nas-now | tail -1   # "backup[nas-nightly] ok: db … config 3 item(s), assets N uploaded …"
```

The first run copies every asset (516 files, about 90 MB in production). Later runs copy only new or changed files. To list the target's backups, or restore into a scratch directory inside the pod, run a Job from the CronJob with a different command:

```bash
oc -n marvin create job --from=cronjob/marvin-backup-nas-nightly marvin-nas-check --dry-run=client -o json \
  | jq '.spec.template.spec.containers[0].command = ["sh", "-c"]
        | .spec.template.spec.containers[0].args = ["python -m marvin.scripts.backup list --target local
            && python -m marvin.scripts.backup restore --target local --into /tmp/restore --skip-assets
            && ls -la /tmp/restore"]' \
  | oc apply -f -
oc -n marvin logs -f job/marvin-nas-check; oc -n marvin delete job marvin-nas-check
```

### Restoring from the NAS

The engine's `restore` works like the off-site script's, with `--target local --into DIR` (see [Restoring](#restoring)). With Postgres it downloads and verifies the dump as `DIR/marvin.dump` and never loads it. Load it with `pg_restore` as in [Postgres → Restore test](postgres.md#restore-test-do-this-first-on-dev-then-after-any-change-to-the-backup).

- **Into the cluster:** follow [Into the cluster](#into-the-cluster), with the Job made from `marvin-backup-nas-nightly` and the arguments `["restore", "--target", "local", "--into", "/app/data", "--force"]`. Suspend `marvin-backup-nas-nightly` as well as the off-site CronJob while you do it.
- **Without the cluster:** the target is plain files. On `pve`, `/tank/backups/marvin/prod/postgres/marvin-<stamp>.dump`, `config/…tar.gz` and `assets/…` are the objects, and each has a `<file>.meta.json` beside it with its size and `sha256`. Check a file with `sha256sum` against its sidecar before using it.

The engine's settings and options are in its module docstrings (`marvin/scripts/backup.py`, `marvin/services/backup_engine/`): `BACKUP_TARGET` / `--target`, `BACKUP_LOCAL_ROOT`, `BACKUP_PREFIX` (falls back to `BACKUP_S3_PREFIX`), `BACKUP_KEEP_*`, and the same `BACKUP_DATA_DIR`, `DB_ENGINE` and `POSTGRES_*` as below. Restore takes `--into DIR` instead of the old `--target DIR`.

## Script reference

```text
python -m marvin.scripts.offsite_backup [backup] [--dry-run]
python -m marvin.scripts.offsite_backup list
python -m marvin.scripts.offsite_backup restore --target DIR [--db-key KEY] [--config-key KEY]
                                                [--skip-db] [--skip-config] [--skip-assets] [--force]
```

| Variable | Default | Notes |
|---|---|---|
| `BACKUP_S3_ENDPOINT` | required | e.g. `https://<account id>.r2.cloudflarestorage.com` |
| `BACKUP_S3_BUCKET` | required | |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | required | read by boto3 only; never logged |
| `BACKUP_S3_REGION` | `auto` | |
| `BACKUP_S3_PREFIX` | empty | e.g. `dev/`: every key under it |
| `BACKUP_DATA_DIR` | `/app/data` | the data directory to back up |
| `BACKUP_DB_ENGINE` | `DB_ENGINE`, else `sqlite` | |
| `BACKUP_KEEP_HOURLY` / `BACKUP_KEEP_DAILY` / `BACKUP_KEEP_WEEKLY` | `48` / `14` / `8` | retention counts (hourly applies to `postgres/` only); `0` turns hourly or weekly off; daily is at least `1` |
| `POSTGRES_SERVER`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | | Postgres only; passed to `pg_dump` as `PGHOST` … `PGDATABASE` |

Exit codes: `0` success, `1` a step failed (the summary or error line says which), `2` missing configuration. `--dry-run` still snapshots and checks the database locally and lists the bucket, so it also proves the credentials work.
