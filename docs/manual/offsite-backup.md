# Off-site backup

Marvin's own **Backups** (see [Operations → Backups](operations.md#backups)) export one workspace's content at a time. They leave out users, API clients and tokens, the installation secret, event and execution logs, and they live on the same volume as the data. The off-site backup covers the whole installation: a nightly CronJob in the Helm chart copies the database, the installation secret and the uploaded files to an S3-compatible bucket off the cluster (Cloudflare R2, MinIO or AWS S3). The work is done by `python -m marvin.scripts.offsite_backup`, which ships in the backend image.

## What is backed up

| Object | Contents |
|---|---|
| `sqlite/marvin-<UTC YYYYmmddTHHMMSSZ>.db.gz` | the SQLite database, copied with SQLite's online backup API while the backend runs, checked with `PRAGMA integrity_check`, then gzipped. A copy that fails the check is not uploaded. |
| `config/marvin-config-<UTC stamp>.tar.gz` | `.secret`, `scheduler_state.json` and `templates/` (custom email templates) from `DATA_DIR` |
| `assets/<path>` | every file under `DATA_DIR/assets`, mirrored incrementally: a file is uploaded when its key is missing or its size or MD5 (the object's ETag) differs. Remote assets are never deleted, so a file deleted in Marvin stays in the bucket. |

The database and config objects carry a `sha256` of the object in their metadata, and the database also a `db-sha256` of the uncompressed file; restore checks both. Logs, `.temp`, `backups/`, the `marvin.db.pre-*` snapshots and the live `marvin.db-wal` / `marvin.db-shm` are not backed up. The copy is consistent: one read transaction covers the whole database, so writes made during the backup are either all in it or all left out.

!!! danger "The bucket holds the installation secret"
    `.secret` is the key that decrypts every secret Marvin stores (workspace secrets, provider keys, integration credentials). It has to be backed up, or encrypted values are unreadable after a restore, but it means anyone who can read the bucket can read those secrets. Keep the bucket private, give the backup a token scoped to that one bucket (on R2: an **Object Read & Write** API token limited to the bucket), keep the token out of Git, and treat a leaked token as leaking the secrets: rotate the token and the stored secrets.

## Retention

After a successful upload, older `sqlite/` and `config/` objects are pruned: the run keeps the newest backup of each of the last 14 days that have one, plus the newest of each of the last 8 ISO weeks, and deletes the rest. Days and weeks are counted among those that have a backup, not back from today, so a run of failed nights never empties the bucket. A prefix is pruned only when that night's upload to it succeeded. Keys the script did not name (for example a manually uploaded `sqlite/before-cutover.db.gz`) and everything under `assets/` are never deleted.

Two backups on the same day (a one-off run after the nightly one) keep only the newer.

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

The backup is engine-aware through `DB_ENGINE`, which the CronJob reads from the release's ConfigMap. With `dbEngine: sqlite` it backs up the SQLite file as above. With `dbEngine: postgres` the database step reports a failure (the run exits non-zero) rather than silently skipping: a `pg_dump` step is not built yet, and Postgres on CloudNativePG gets its own barman backups (base backup plus WAL) to the same bucket. The config archive and the assets are still backed up either way. The seam is `backup_database` in `src/marvin/scripts/offsite_backup.py`.

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
| `BACKUP_DATA_DIR` | `/app/data` | the data directory to back up |
| `BACKUP_DB_ENGINE` | `DB_ENGINE`, else `sqlite` | |

Exit codes: `0` success, `1` a step failed (the summary or error line says which), `2` missing configuration. `--dry-run` still snapshots and checks the database locally and lists the bucket, so it also proves the credentials work.
