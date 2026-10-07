# Off-site backup

Marvin's own **Backups** (see [Operations → Backups](operations.md#backups)) export one workspace's content at a time. They leave out users, API clients and tokens, the installation secret, event and execution logs, and they live on the same volume as the data. The installation backup covers all of it: the **backup engine** (`python -m marvin.scripts.backup`, in the backend image) copies the database, the installation secret and the uploaded files to a list of independent **targets**, each a CronJob of its own in the Helm chart (`backup.targets[]`). A target is the built-in `local` (a directory on a volume of its own, for example the NAS) or a storage plugin's target, for example `s3` from [`marvin-storage-s3`](https://github.com/InnerOpen/marvin-storage-s3) for an S3-compatible bucket off the cluster (Cloudflare R2, MinIO, AWS S3, Backblaze B2).

Production runs two targets: `r2` hourly to the R2 bucket `marvin-backups` (the off-site copy) and `nas-nightly` to the NAS. Dev runs `r2` hourly to `marvin-backups-dev`. Each target has its own schedule, retention, run and exit code, so a failing NAS never stops the R2 run and the other way round.

The old single-target job (`marvin.scripts.offsite_backup`, CronJob `marvin-offsite-backup`, `backup.enabled`) is retired: the `r2` target replaced it in dev and production, writing the same objects into the same buckets (see [The old off-site job](#the-old-off-site-job)). It stays in the image and chart as the rollback until it is removed.

## What is backed up

| Object | Contents |
|---|---|
| `sqlite/marvin-<UTC YYYYmmddTHHMMSSZ>.db.gz` | the SQLite database, copied with SQLite's online backup API while the backend runs, checked with `PRAGMA integrity_check`, then gzipped. A copy that fails the check is not uploaded. |
| `postgres/marvin-<UTC stamp>.dump` | with `dbEngine: postgres`, instead of `sqlite/`: a `pg_dump --format=custom` of the app's database, read back with `pg_restore --list` before upload. See [Postgres](#postgres). |
| `config/marvin-config-<UTC stamp>.tar.gz` | `.secret`, `scheduler_state.json` and `templates/` (custom email templates) from `DATA_DIR` |
| `assets/<path>` | every uploaded file, read through the storage provider, mirrored incrementally: a file is copied when its key is missing in the target or its size or digest differs (MD5 from the ETag on an `s3` target, `sha256` on a `local` one). Assets are never deleted from a target, so a file deleted in Marvin stays there. |

The database and config objects carry a `sha256` of the object in their metadata (a `<file>.meta.json` sidecar on a `local` target), and the database also a `db-sha256` of the uncompressed file; restore checks both. Logs, `.temp`, `backups/`, the `marvin.db.pre-*` snapshots and the live `marvin.db-wal` / `marvin.db-shm` are not backed up. The copy is consistent: one read transaction covers the whole database, so writes made during the backup are either all in it or all left out.

!!! danger "Every target holds the installation secret"
    `.secret` is the key that decrypts every secret Marvin stores (workspace secrets, provider keys, integration credentials). It has to be backed up, or encrypted values are unreadable after a restore, but it means anyone who can read a target can read those secrets. Keep the bucket private, give the backup a token scoped to that one bucket (on R2: an **Object Read & Write** API token limited to the bucket), keep the token out of Git, and treat a leaked token as leaking the secrets: rotate the token and the stored secrets. The same goes for the NAS export.

## Retention

After a successful upload, older database (`postgres/` or `sqlite/`) and `config/` objects in that target are pruned. The run keeps the newest database backup of each of the last `hourly` hours, the newest backup of each of the last `daily` days and the newest of each of the last `weekly` ISO weeks, and deletes the rest. Hours, days and weeks are counted among those that have a backup, not back from now, so a run of failures never empties a target. A prefix is pruned only when that run's upload to it succeeded. Keys the engine did not name (for example a manually uploaded `postgres/before-cutover.dump`) and everything under `assets/` are never deleted. Two backups in the same hour (a one-off run after the scheduled one) keep only the newer.

The counts are a target's `retention: {hourly, daily, weekly}` (`BACKUP_KEEP_HOURLY` / `_DAILY` / `_WEEKLY`). A key left out keeps the engine's default, 48 / 30 / 0 ("30 days, hourly for the last two"); 0 turns the hourly or weekly rule off; daily must be at least 1, so a run never prunes the backup it just made.

| Target | Hourly | Daily | Weekly |
|---|---|---|---|
| production `r2` | 48 | 30 | 8 |
| production `nas-nightly` | 0 | 30 | 8 |
| dev `r2` | 24 | 7 | 0 |

## Targets in the chart

```yaml
plugins:
  packages:                                   # the s3 target comes from a plugin
    - https://github.com/InnerOpen/marvin-integration-sdk/archive/refs/heads/develop.tar.gz
    - https://github.com/InnerOpen/marvin-storage-s3/archive/refs/heads/main.tar.gz
backup:
  targets:
    - name: r2                                # CronJob marvin-backup-r2
      type: s3
      existingSecret: marvin-r2-backup        # every key becomes an environment variable
      schedule: "0 * * * *"
      timeZone: America/New_York
      retention: {hourly: 48, daily: 30, weekly: 8}
      activeDeadlineSeconds: 2700             # an hourly run must finish well before the next
      startingDeadlineSeconds: 900
    - name: nas-nightly                       # CronJob marvin-backup-nas-nightly
      type: local
      schedule: "30 2 * * *"
      timeZone: America/New_York
      retention: {hourly: 0, daily: 30, weekly: 8}
      volume:
        nfs: {server: 192.168.30.10, path: /tank/backups/marvin}   # static PV + PVC from the chart
        subPath: prod                         # the target root inside the export; dev would use dev/
```

Each entry renders a CronJob `<release>-backup-<name>` running `python -m marvin.scripts.backup run --target <type> --name <name>` from the backend image at the backend's tag (`concurrencyPolicy: Forbid`, `backoffLimit: 2`, the last 3 successful and 3 failed jobs kept). The data volume is ReadWriteOnce and SQLite's WAL index is shared memory, so the pod is scheduled onto the backend pod's node (required pod affinity); with no backend pod the job stays Pending and fails at `activeDeadlineSeconds`. It mounts the data volume read-write, because a reader of a WAL-mode database takes its locks in `marvin.db-shm`, but opens the database read-only and writes nothing else there; it stages the snapshot or dump in an `emptyDir` at `/tmp` (about 1.2 times the database size).

- **Plugins:** with `plugins.packages` set, every target CronJob gets the same `install-plugins` init container as the backend (one `pip install` into an `emptyDir` on `PYTHONPATH`). The packages are downloaded on every run, so a backup run needs GitHub and PyPI egress like a backend start does. The log's first lines say which plugin provides the target (`storage plugin 's3' replaces core's built-in 's3'` while core still has its own copy).
- **`s3` target settings** (plugin `marvin-storage-s3`), from `existingSecret`: `BACKUP_S3_BUCKET` (required), `BACKUP_S3_ENDPOINT` (empty = AWS), `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and optionally `BACKUP_S3_REGION` (default `auto`, right for R2). The Secret `marvin-r2-backup` has exactly the four required keys; create it by hand (below), the chart never renders it.
- **Volume** (`local` only): `volume.existingClaim`, or `volume.nfs: {server, path}`, from which the chart renders a static PersistentVolume `<namespace>-<release>-backup-<name>` (ReadWriteMany, `Retain`, `storageClassName: ""`, mount options `hard,nfsvers=4.2`, `claimRef` to the PVC) and the PVC `<release>-backup-<name>`. It has to be a PV, because OpenShift's `restricted-v2` SCC doesn't allow inline `nfs:` volumes. `volume.subPath` picks a directory inside the volume, which the kubelet creates on the first run. The volume is mounted at `/backup-target` (`BACKUP_LOCAL_ROOT`).
- **Guardrails:** `helm template` fails when a local target has no volume or points at the data volume (`marvin-data`, `<release>-data` or `persistence.existingClaim`). At runtime the engine also refuses a target directory inside `DATA_DIR` or on the same filesystem as it, and a directory that doesn't exist (a missing mount mustn't fill the container's disk).
- Other keys: `prefix` (`BACKUP_PREFIX`, e.g. `staging/` to share a bucket), `env`, `resources` (default `backup.resources`). Deadlines default to 3600 each. The chart's `values.yaml` lists them all.

Creating the R2 Secret (once per namespace; each environment's `BACKUP_S3_BUCKET` is its own bucket):

```bash
oc -n marvin create secret generic marvin-r2-backup \
  --from-literal=AWS_ACCESS_KEY_ID='<access key id>' \
  --from-literal=AWS_SECRET_ACCESS_KEY='<secret access key>' \
  --from-literal=BACKUP_S3_ENDPOINT='https://<account id>.r2.cloudflarestorage.com' \
  --from-literal=BACKUP_S3_BUCKET='marvin-backups'
```

!!! warning "The NAS shares a pool with the live data"
    The export `/tank/backups/marvin` (ZFS dataset `tank/backups` on `pve`, 50 GB quota) is in the same `tank` pool as `managed-nfs-storage`. The NAS copy covers a deleted or corrupted PVC and app bugs, not losing the NAS. R2 remains the off-site copy. The export squashes every client to uid 3100 (`all_squash`), which owns it at mode 0770, so any pod UID can write. Any host in the export's client range (`192.168.50.0/25`, the cluster nodes) can mount it.

## Running and checking a target

```bash
oc -n marvin get cronjob -l app.kubernetes.io/component=backup
oc -n marvin create job --from=cronjob/marvin-backup-r2 marvin-r2-now
oc -n marvin wait --for=condition=complete job/marvin-r2-now --timeout=30m
oc -n marvin logs job/marvin-r2-now -c backup | tail -1
```

The last line of every run is a one-line summary, for example `backup[r2] ok: db 7.4 MB (postgres/marvin-20261007T021941Z.dump), config 3 item(s), assets 0 uploaded (0.0 MB), 516 unchanged, pruned 2, 8.7s`. A failed step is listed after `FAILED`, the other steps still run, and the job exits non-zero, so it shows as failed in `oc get jobs`. Credentials are never logged.

A target's first run copies every asset (516 files, about 90 MB in production); later runs copy only new or changed files. An `s3` target pointed at a bucket the old off-site job wrote finds those assets unchanged and carries on its history.

To list a target's backups and restore into a scratch directory inside the pod, run a Job from the CronJob with a different command (replace `s3` / `r2` with `local` / `nas-nightly` for the NAS):

```bash
oc -n marvin create job --from=cronjob/marvin-backup-r2 marvin-r2-check --dry-run=client -o json \
  | jq '.spec.template.spec.containers[0].command = ["sh", "-c"]
        | .spec.template.spec.containers[0].args = ["python -m marvin.scripts.backup list --target s3 --name r2
            && python -m marvin.scripts.backup restore --target s3 --name r2 --into /tmp/restore --skip-assets
            && ls -la /tmp/restore"]' \
  | oc apply -f -
oc -n marvin logs -f job/marvin-r2-check -c backup; oc -n marvin delete job marvin-r2-check
```

A backup is only proven by restoring it: see [Postgres → Restore test](postgres.md#restore-test-do-this-first-on-dev-then-after-any-change-to-the-backup).

## Restoring

`restore --target <type> --into DIR` downloads the chosen database object (default: the newest for the engine), checks its checksums (and `integrity_check` for SQLite) before it touches `DIR`, then the config archive, then any assets missing or different locally. It never deletes local files. Into a directory that already has `marvin.db` or `.secret` it refuses unless given `--force`, and with `--force` it moves the existing `marvin.db`, `marvin.db-wal`, `marvin.db-shm`, `.secret`, `scheduler_state.json` and `templates/` aside as `<name>.pre-restore-<stamp>` rather than overwriting them. Moving the `-wal` aside matters: left beside a restored database, SQLite would replay it onto that database. With Postgres it downloads and verifies the dump as `DIR/marvin.dump` and never loads it; load it with `pg_restore` (see [Postgres](#postgres)).

Options: `--db-key postgres/marvin-<stamp>.dump` (or `sqlite/…`) and `--config-key config/…` pick an older backup than the newest; `--skip-db`, `--skip-config`, `--skip-assets`.

### Into the cluster

`--force` is safe only while no backend process has the database open: replacing it under a running backend corrupts it. Stop the backend first.

1. Stop the backend and pause every target's schedule:

    ```bash
    oc -n marvin scale deploy/marvin-backend --replicas=0   # combined mode: deploy/marvin
    for cj in marvin-backup-r2 marvin-backup-nas-nightly; do oc -n marvin patch cronjob $cj -p '{"spec":{"suspend":true}}'; done
    oc -n marvin get pods   # wait until the backend pod is gone
    ```

2. Run the restore as a Job made from the target's CronJob, with the arguments swapped and the pod affinity dropped (there is no backend pod to sit beside now):

    ```bash
    oc -n marvin create job --from=cronjob/marvin-backup-r2 marvin-restore --dry-run=client -o json \
      | jq '.spec.template.spec.containers[0].args = ["restore", "--target", "s3", "--name", "r2", "--into", "/app/data", "--force"]
            | del(.spec.template.spec.affinity)' \
      | oc apply -f -
    oc -n marvin logs -f job/marvin-restore -c backup
    ```

    From the NAS: `--from=cronjob/marvin-backup-nas-nightly` and `"--target", "local", "--name", "nas-nightly"`. With Postgres this puts the dump at `/app/data/marvin.dump`; load it as in [Postgres](postgres.md#restore-test-do-this-first-on-dev-then-after-any-change-to-the-backup) before starting the backend.

3. Start the backend and resume the schedules, then check it serves (`/healthz`, a login, a page with images):

    ```bash
    oc -n marvin scale deploy/marvin-backend --replicas=1
    for cj in marvin-backup-r2 marvin-backup-nas-nightly; do oc -n marvin patch cronjob $cj -p '{"spec":{"suspend":false}}'; done
    oc -n marvin delete job marvin-restore
    ```

4. Once satisfied, delete the `*.pre-restore-*` files from the volume. Until then they are the way back.

A `helm upgrade` resets the CronJobs' `suspend` to the chart's value, so resume them explicitly or the next upgrade will.

To bring back only lost uploads, restore the assets alone. This needs no `--force` and the backend can keep running: `["restore", "--target", "s3", "--name", "r2", "--into", "/app/data", "--skip-db", "--skip-config"]`.

**Without the cluster:** the NAS target is plain files. On `pve`, `/tank/backups/marvin/prod/postgres/marvin-<stamp>.dump`, `config/…tar.gz` and `assets/…` are the objects, and each has a `<file>.meta.json` beside it with its size and `sha256`. Check a file with `sha256sum` against its sidecar before using it.

## Postgres

The engine is engine-aware through `DB_ENGINE`, which the CronJob reads from the release's ConfigMap. With `dbEngine: sqlite` it backs up the SQLite file as above. With `dbEngine: postgres` the database part is a `pg_dump --format=custom` of the app's database, taken with the same `POSTGRES_*` connection the backend uses (the chart passes them from the connection Secret; the engine hands them to `pg_dump` as `PG*` environment variables, never on the command line), checked with `pg_restore --list`, and uploaded as `postgres/marvin-<stamp>.dump`. This dump **is** the Postgres backup — there is no WAL archiving or point-in-time recovery, by choice — so the `r2` target runs hourly. See [Postgres → Backups](postgres.md#backups), including the restore test.

`pg_dump` comes from the backend image's `postgresql-client` (Debian's, major 17). A dump only restores cleanly with a `pg_restore` at least as new, into a server of the same major or newer, which is why the clusters run Postgres 17.

## Engine reference

```text
python -m marvin.scripts.backup run     --target TYPE [--name NAME] [--dry-run]
python -m marvin.scripts.backup list    --target TYPE [--name NAME]
python -m marvin.scripts.backup prune   --target TYPE [--name NAME] [--dry-run]
python -m marvin.scripts.backup restore --target TYPE [--name NAME] --into DIR [--db-key KEY] [--config-key KEY]
                                        [--skip-db] [--skip-config] [--skip-assets] [--force]
```

`--target` is the target type (`local`, or a plugin's slug such as `s3`; default `BACKUP_TARGET`), `--name` a label for the logs. Settings: `BACKUP_LOCAL_ROOT` (local), the plugin's own settings (s3: above), `BACKUP_PREFIX` (falls back to `BACKUP_S3_PREFIX`), `BACKUP_KEEP_HOURLY` / `_DAILY` / `_WEEKLY`, `BACKUP_DATA_DIR` (default `/app/data`), `DB_ENGINE`, and `POSTGRES_SERVER` … `POSTGRES_DB` for Postgres. More in the module docstrings (`marvin/scripts/backup.py`, `marvin/services/backup_engine/`).

Exit codes: `0` success, `1` a step failed (the summary or error line says which), `2` missing configuration. `run --dry-run` still snapshots and checks the database locally and lists the target, so it also proves the credentials work.

## The old off-site job

`python -m marvin.scripts.offsite_backup` (CronJob `<release>-offsite-backup`, `backup.enabled`, `backup.schedule`, `backup.existingSecret`, `backup.s3Region`, `backup.prefix`, `backup.retention`) was the S3-only predecessor: same key layout, its own retention (48 hourly for `postgres/`, 14 daily, 8 weekly by default). The `r2` target replaced it on 2026-10-06 (dev) and at the following production promotion, reading and pruning the history it left. `values-dev.yaml` and `values-iwobble.yaml` keep its settings with `enabled: false` until it is deleted (slice 7 of the storage plan, after a week of green `r2` runs).

**Rolling back to it:** set `backup.enabled: true` and remove the `r2` target (or suspend `marvin-backup-r2` with `oc patch cronjob marvin-backup-r2 -p '{"spec":{"suspend":true}}'`) so the two don't write the same bucket at the same minute, then upgrade; or `helm rollback` to the revision before the cutover. Either way the old job carries on the bucket's history, assets included (it reads the new target's objects as its own).
