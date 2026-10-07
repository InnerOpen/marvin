# Postgres

Marvin runs on SQLite or Postgres (`config.dbEngine`). On the iwobble cluster Postgres is a [CloudNativePG](https://cloudnative-pg.io) (CNPG) cluster per environment, rendered by the Helm chart. This page covers the `marvin-dev` environment, backups and restores, the SQLite → Postgres copy tool and the production cutover.

What lives where once an environment is on Postgres:

| What | Where |
|---|---|
| The database | CNPG cluster `<name>` (one instance), its own PVC; app connection in Secret `<name>-app`, Service `<name>-rw` |
| Uploaded assets, `.secret` (decrypts stored secrets), `templates/` | the release's data PVC, as before |
| Backups | the off-site CronJob, **hourly**: `postgres/marvin-<stamp>.dump` (`pg_dump`), `config/`, `assets/` in the environment's bucket — production `marvin-backups`, dev `marvin-backups-dev` |

## Chart values

```yaml
config:
  dbEngine: postgres          # the backend and the backup job get POSTGRES_* from the Secret below
postgres:
  existingSecret: ""          # default "<cluster.name>-app" when cluster.enabled
  cluster:
    enabled: true             # render templates/postgres-cluster.yaml
    name: marvin-dev-pg
    imageName: ghcr.io/cloudnative-pg/postgresql:17
    storage: {size: 10Gi, storageClass: managed-nfs-storage}
backup:
  enabled: true
  existingSecret: marvin-r2-backup   # BACKUP_S3_BUCKET in it picks the bucket
  schedule: "0 * * * *"              # hourly
```

The cluster can be enabled while `dbEngine` is still `sqlite` — that is how production gets its database ready before the cutover. The Cluster carries `helm.sh/resource-policy: keep`: `helm uninstall` leaves the database and its PVC alone; delete them by hand when you mean it. With `dbEngine: postgres` the backend may roll (`RollingUpdate`) instead of `Recreate`; keep one replica while assets are on the RWO data volume.

Postgres 17 is used everywhere on purpose: the clusters, the CI test job and the backend image's `pg_dump` (Debian's `postgresql-client`). A `pg_dump` 17 archive does not restore cleanly into Postgres 16. Move all three together.

## The `marvin-dev` environment

Release `marvin` in namespace `marvin-dev`, values `marvin-chart/values-dev.yaml`: split mode, `:develop` images with `pullPolicy: Always`, CNPG cluster `marvin-dev-pg`, a 2 Gi assets PVC, routes `marvin-marvin-dev.apps.ocp4.iwobble.com` (UI) and `marvin-api-marvin-dev.apps.ocp4.iwobble.com` (API) with `X-Robots-Tag: noindex, nofollow`, production's integration plugins, the **scheduler off** (`SCHEDULER_ENABLED=false`), and the hourly backup to `marvin-backups-dev`. Only the CNPG operator is needed on the cluster (installed).

!!! note "One R2 token, two buckets"
    By Jared's choice the same R2 token (`pass marvin/r2/*`) can read and write both `marvin-backups` (production) and `marvin-backups-dev` (dev). The buckets keep the environments' objects and retention apart; the token does not — dev's credentials could delete production backups.

Bring it up (the project exists; the image must contain this branch, i.e. it is merged into `develop`):

```bash
# 1. R2 credentials straight from pass (nothing printed, nothing on argv); dev's own bucket
oc -n marvin-dev create secret generic marvin-r2-backup \
  --from-file=AWS_ACCESS_KEY_ID=<(pass show marvin/r2/access-key-id | head -n1 | tr -d '\n') \
  --from-file=AWS_SECRET_ACCESS_KEY=<(pass show marvin/r2/secret-access-key | head -n1 | tr -d '\n') \
  --from-file=BACKUP_S3_ENDPOINT=<(pass show marvin/r2/endpoint | head -n1 | tr -d '\n') \
  --from-literal=BACKUP_S3_BUCKET=marvin-backups-dev

# 2. The CNPG Cluster and the app
helm upgrade --install marvin marvin-chart -n marvin-dev -f marvin-chart/values-dev.yaml
oc -n marvin-dev get cluster marvin-dev-pg -w          # until "Cluster in healthy state"
oc -n marvin-dev rollout status deploy/marvin-backend  # restarts until marvin-dev-pg-app exists
```

On first start against the empty database the backend migrates and seeds the default group and admin. Then load production (below, `--pause-outbound`), take the first backup and test the restore ([Backups](#backups)). Dev follows `develop`: `oc -n marvin-dev rollout restart deploy/marvin-backend deploy/marvin-frontend` picks up the newest build.

!!! warning "Production data in dev"
    A copy of production brings real users, tokens, webhook URLs, workflows and scheduled tasks. Stored secrets stay unreadable (dev has its own `.secret`), but plain-text outgoing webhooks — a Cloudflare Pages deploy hook, for one — would fire. Dev therefore runs with the scheduler off **and** the copy is loaded with `--pause-outbound`, which switches off, in dev's database only, webhooks, integrations and their subscriptions, workflows, email subscriptions, SMTP profiles, MCP servers, scheduled tasks and auto site rebuilds. AI providers stay on (they only run when someone asks for an AI action). To test a feature, re-enable just what it needs: `--unpause webhook_urls` (the rows the pause switched off, nothing else), or in the UI.

## Storage

`managed-nfs-storage` (nfs-subdir-external-provisioner, NFS 4.2 `hard` mounts from the NAS) is the only storage class on ocp4, so the clusters use it. The export keeps the pod's UID (no squashing — `marvin-data` files are owned by the pod user), which `initdb` needs. CNPG recommends block storage and discourages NFS: Postgres relies on `fsync` and locking semantics an NFS server may not give, and a misbehaving export can corrupt the database. Mitigations here: one instance, `hard` mounts, and an hourly logical dump off the cluster. Better options, in order of effort:

- **iSCSI from the NAS** via democratic-csi (ZFS zvols as block PVs, snapshots for free).
- **LVM Storage (LVMS) operator** on a node with a spare disk: local block PVs, fastest; the database is then pinned to that node.
- OpenShift Data Foundation (Ceph) — heavy for one small database.

Moving a cluster to a new class = restore the newest dump into a new cluster with the new `storageClass`, then point the app at it.

## Backups

The Postgres backup is the backup engine's `r2` target (CronJob `marvin-backup-r2`, through the `s3` target of the `marvin-storage-s3` plugin), run **hourly**: a `pg_dump --format=custom` of the app's database, read back with `pg_restore --list`, uploaded as `postgres/marvin-<UTC stamp>.dump`, plus the config archive and the asset mirror ([Off-site backup](offsite-backup.md)). Retention for the dumps: the newest of each of the last 48 hours, of each of the last 30 days and of each of the last 8 weeks. Dev keeps less: 24 hours and 7 days, no weeks (the `r2` target's `retention` in `values-dev.yaml`). It replaced the old off-site CronJob (`marvin-offsite-backup`) in the same bucket, history included.

Production also writes a nightly copy to the NAS: backup target `nas-nightly` (CronJob `marvin-backup-nas-nightly`, 02:30 New York time, 30 daily + 8 weekly), with the same `pg_dump`, config archive and asset mirror ([Off-site backup → Targets in the chart](offsite-backup.md#targets-in-the-chart)). It shares a ZFS pool with the live data, so R2 stays the off-site copy. Dev has no NAS target.

- **At most an hour of data can be lost** (whatever was written since the last dump).
- **No point-in-time recovery, by choice**: no WAL archiving, no Barman Cloud plugin, no cert-manager. A restore goes back to a dump's moment.

Check and run one now:

```bash
oc -n marvin-dev get cronjob marvin-backup-r2; oc -n marvin-dev get jobs --sort-by=.metadata.creationTimestamp | tail -3
oc -n marvin-dev create job --from=cronjob/marvin-backup-r2 marvin-backup-now
oc -n marvin-dev wait --for=condition=complete job/marvin-backup-now --timeout=10m
oc -n marvin-dev logs job/marvin-backup-now -c backup | tail -1     # "backup[r2] ok: db … (postgres/marvin-….dump)"
```

### Restore test (do this first on dev, then after any change to the backup)

Fetch the newest dump in a Job made from the target's CronJob (it has the plugin and the credentials; nothing on the workstation needs them), load it into a throwaway local Postgres 17, and compare every table's row count with the live database. Take a fresh backup right before (above) so the counts are from the same moment — dev runs no scheduler, so nothing changes in between. For the NAS use `--from=cronjob/marvin-backup-nas-nightly` and `--target local --name nas-nightly`.

```bash
mkdir -p /tmp/r && chmod 700 /tmp/r
# 1. fetch + verify the newest dump from dev's bucket, inside the cluster; the pod waits 10 minutes for the copy
oc -n marvin-dev create job --from=cronjob/marvin-backup-r2 marvin-restore-test --dry-run=client -o json \
  | jq '.spec.template.spec.containers[0].command = ["sh", "-c"]
        | .spec.template.spec.containers[0].args = ["python -m marvin.scripts.backup restore --target s3 --name r2
            --into /tmp/restore --skip-config --skip-assets && echo READY && sleep 600"]' \
  | oc apply -f -
until oc -n marvin-dev logs job/marvin-restore-test -c backup 2>/dev/null | grep -q READY; do sleep 5; done
oc -n marvin-dev cp -c backup "$(oc -n marvin-dev get pod -l job-name=marvin-restore-test -o name | cut -d/ -f2)":/tmp/restore/marvin.dump /tmp/r/marvin.dump
oc -n marvin-dev delete job marvin-restore-test

# 2. load it into a scratch Postgres 17
docker run -d --name marvin-restore-test -e POSTGRES_USER=marvin -e POSTGRES_PASSWORD=marvin -e POSTGRES_DB=marvin \
  -v /tmp/r:/r:ro postgres:17-alpine
sleep 5; docker exec marvin-restore-test pg_restore --exit-on-error --no-owner -U marvin -d marvin /r/marvin.dump

# 3. per-table counts on both sides must be identical
COUNTS="select table_name, (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I', table_name), false, true, '')))[1]::text
        from information_schema.tables where table_schema = 'public' and table_type = 'BASE TABLE' order by 1"
docker exec marvin-restore-test psql -U marvin -d marvin -tAc "$COUNTS" | LC_ALL=C sort > /tmp/r/restored.txt
oc -n marvin-dev exec marvin-dev-pg-1 -c postgres -- psql -U postgres -d marvin -tAc "$COUNTS" | LC_ALL=C sort > /tmp/r/live.txt
diff /tmp/r/live.txt /tmp/r/restored.txt && echo "restore test OK: $(wc -l < /tmp/r/live.txt) tables"

docker rm -f marvin-restore-test; rm -rf /tmp/r     # the dump is production data: don't keep it
```

The `.secret` and assets can be checked the same way inside the Job, against the live volume mounted at `/app/data`: restore without `--skip-config --skip-assets`, then `cmp /tmp/restore/.secret /app/data/.secret` and compare `sha256sum` lists of `/tmp/restore/assets` and `/app/data/assets`.

To **restore for real**, load the dump the same way into an empty database — a new CNPG cluster (`postgres.cluster.name: <new>`) or the app's after a deliberate drop — through `oc port-forward svc/<cluster>-rw 15432:5432` and the `<cluster>-app` credentials, with the backend scaled to 0; then point the release at it and scale back up.

### Adding point-in-time recovery later

Nothing has to move. Install cert-manager and the [Barman Cloud plugin](https://cloudnative-pg.io/plugin-barman-cloud/docs/installation/) into the operator's namespace (`openshift-operators`; the upstream Deployment pins UID 10001, so the plugin's service account needs `nonroot-v2`), create a `barmancloud.cnpg.io/v1` `ObjectStore` (bucket path, R2 endpoint, the `marvin-r2-backup` keys, `retentionPolicy`; set `AWS_REQUEST_CHECKSUM_CALCULATION` / `AWS_RESPONSE_CHECKSUM_VALIDATION=when_required` in its `instanceSidecarConfiguration.env` for R2), add `plugins: [{name: barman-cloud.cloudnative-pg.io, isWALArchiver: true, parameters: {barmanObjectName: <store>}}]` to the Cluster (the template's header comment has the shape) and a `ScheduledBackup` with `method: plugin`. CNPG starts archiving from the running cluster. CNPG's in-tree `barmanObjectStore` is not an option: deprecated, removed in 1.31.

## SQLite → Postgres copy tool

`python -m marvin.scripts.sqlite_to_postgres` ships in the backend image. The target is the app's own Postgres (`DB_ENGINE=postgres` + `POSTGRES_*`).

```text
python -m marvin.scripts.sqlite_to_postgres --source /app/data/marvin.db --dry-run
python -m marvin.scripts.sqlite_to_postgres --source /app/data/marvin.db [--truncate] [--pause-outbound] [--batch-size 1000]
python -m marvin.scripts.sqlite_to_postgres --pause-outbound          # pause an existing target, no copy
python -m marvin.scripts.sqlite_to_postgres --unpause [TABLE ...]     # undo the pause (all, or these tables)
```

What it does:

1. Opens the SQLite file **read-only**, in one read transaction (it never writes the source).
2. Runs `alembic upgrade head` on the target, then requires the source's Alembic revision to equal the target's — copy with the same image version that last ran on the file.
3. Refuses a target that holds data unless `--truncate` (re-runs with `--truncate` are idempotent).
4. Checks every value against the target column type before writing anything — SQLite keeps booleans as 0/1, datetimes, JSON and GUIDs as text, and enforces neither lengths nor types. Anything that does not convert exactly (invalid JSON, a datetime without a time, too long for its column, a NUL byte, NULL in a NOT NULL column, an unknown enum label) is listed and nothing is written. Lossless normalisations are reported as notes (e.g. a `+00:00` offset in a naive timestamp column → stored as naive UTC).
5. In **one transaction**: truncate, drop the foreign keys, copy every table except `alembic_version` in dependency order in batches, re-create the foreign keys (Postgres re-checks every row — an orphan SQLite let through fails here, named), reset serial sequences, and verify: per-table row counts and a checksum over every column of every row must match on both sides. Any failure rolls everything back.

6. With `--pause-outbound` (non-production copies only), still in that transaction: every row of `webhook_urls.enabled`, `integrations.enabled`, `integration_event_subscriptions.enabled`, `workspace_automations.enabled`, `email_event_subscriptions.enabled`, `workspace_smtp_profiles.is_active`, `workspace_mcp_servers.enabled`, `scheduled_tasks.enabled` and `group_preferences.site_auto_rebuild` that is on is switched off, and recorded with its previous value in the table `marvin_outbound_pause`. The output lists how many per table. `--unpause` gives exactly those rows their previous value back (all, or `--unpause webhook_urls integrations` …) and drops their records; a `--truncate` re-copy starts the record over. Not paused: AI providers (only run on request), and SMTP from the environment (`SMTP_HOST`, which in dev points nowhere). Pending integration retries need the scheduler and their (paused) integration, so they stay as they are.

`--dry-run` writes nothing: source and target counts, plus the full value check. Exit code 0 = copied and verified, 1 = refused or failed (the log says why), 2 = not configured for Postgres.

Rehearsal on a copy of production (2026-10-06, Postgres 16 and 17, also inside the built image as a random UID): 61 tables, 15,949 rows, 94 foreign keys re-validated, every checksum equal, one note (`ai_executions.completed_at`: one value carried `+00:00`). About 10 s. The backend then started on the copy and served entries, event-type connections, workflows and a workflow dry run.

### Loading production data into dev

Run the tool locally against dev's database through a port-forward — the production file never lands on the cluster's dev volume. Take a consistent copy of production's file (SQLite backup API in the backend pod into `/tmp`, `oc cp` it out, delete the pod-side copy), treat the local copy as sensitive and delete it afterwards. Copy with the same Marvin version dev runs (same Alembic head).

```bash
oc -n marvin-dev scale deploy/marvin-backend --replicas=0
oc -n marvin-dev port-forward svc/marvin-dev-pg-rw 15432:5432 &
S=marvin-dev-pg-app; g() { oc -n marvin-dev get secret $S -o jsonpath="{.data.$1}" | base64 -d; }
DB_ENGINE=postgres POSTGRES_SERVER=127.0.0.1 POSTGRES_PORT=15432 POSTGRES_USER=$(g username) \
  POSTGRES_PASSWORD=$(g password) POSTGRES_DB=$(g dbname) DATA_DIR=$(mktemp -d) PYTHONPATH=src \
  uv run python -m marvin.scripts.sqlite_to_postgres --source /path/to/marvin-copy.db --truncate --pause-outbound
kill %1; oc -n marvin-dev scale deploy/marvin-backend --replicas=1
shred -u /path/to/marvin-copy.db
```

`--truncate` because the backend already seeded the empty database on its first start.

## Production cutover

Planned downtime of a few minutes; the SQLite file is never modified, so it is the rollback.

**Days before**

- [ ] The restore test passes on dev (above).
- [ ] Enable the cluster while still on SQLite: in `values-iwobble.yaml` set `postgres.cluster.enabled: true`, `name: marvin-pg`, `storage.storageClass: managed-nfs-storage`; keep `config.dbEngine: sqlite`. Promote (`scripts/deploy/promote-iwobble.sh <sha>`). Check the cluster is healthy.
- [ ] Rehearse: copy a fresh production snapshot into `marvin-pg` with `--truncate` (the Job below with `--source` pointing at a snapshot, or locally through a port-forward). All tables `ok`. Note how long it took.
- [ ] Pick the window; tell Grace.

**In the window**

- [ ] Note the promoted commit: `helm history marvin -n marvin | tail -1`.
- [ ] Stop the backend and wait for it to drain: `oc -n marvin scale deploy/marvin-backend --replicas=0`; `oc -n marvin wait --for=delete pod -l app.kubernetes.io/component=backend --timeout=6m`.
- [ ] Final copy, with the **same image** production runs (so the Alembic revisions match):

    ```bash
    NS=marvin; PG=marvin-pg-app
    IMAGE=$(oc -n $NS get deploy marvin-backend -o jsonpath='{.spec.template.spec.containers[0].image}')
    oc -n $NS apply -f - <<EOF
    apiVersion: batch/v1
    kind: Job
    metadata:
      name: marvin-sqlite-to-postgres
    spec:
      backoffLimit: 0
      ttlSecondsAfterFinished: 604800
      template:
        spec:
          restartPolicy: Never
          containers:
            - name: copy
              image: $IMAGE
              command: ["python", "-m", "marvin.scripts.sqlite_to_postgres"]
              args: ["--source", "/app/data/marvin.db", "--truncate"]
              env:
                - {name: DB_ENGINE, value: postgres}
                - {name: DATA_DIR, value: /app/data}
                - {name: POSTGRES_SERVER, valueFrom: {secretKeyRef: {name: $PG, key: host}}}
                - {name: POSTGRES_PORT, valueFrom: {secretKeyRef: {name: $PG, key: port}}}
                - {name: POSTGRES_USER, valueFrom: {secretKeyRef: {name: $PG, key: username}}}
                - {name: POSTGRES_PASSWORD, valueFrom: {secretKeyRef: {name: $PG, key: password}}}
                - {name: POSTGRES_DB, valueFrom: {secretKeyRef: {name: $PG, key: dbname}}}
              volumeMounts:
                - {name: data, mountPath: /app/data}   # read-write only for SQLite's -shm; the tool opens the file read-only
          volumes:
            - {name: data, persistentVolumeClaim: {claimName: marvin-data}}
    EOF
    oc -n $NS wait --for=condition=complete job/marvin-sqlite-to-postgres --timeout=15m
    oc -n $NS logs job/marvin-sqlite-to-postgres | tail -75
    ```

- [ ] Verify: the summary line says `COPIED`, every table `ok`, `0 problem(s)`; counts match the rehearsal's order of magnitude. Anything else → stop here and roll back (below).
- [ ] Switch: in `values-iwobble.yaml` set `config.dbEngine: postgres` and the backup hourly (`backup.schedule: "0 * * * *"`, `activeDeadlineSeconds: 2700`, `startingDeadlineSeconds: 900` as in `values-dev.yaml`; bucket stays `marvin-backups`). Keep `split.backend.strategy: Recreate` for this first deploy. Commit, and promote the **same** commit's image: `scripts/deploy/promote-iwobble.sh <sha>` (scales the backend back to 1). No `--pause-outbound` here: this is production.
- [ ] Smoke: log in; entries list; open an entry and save it; a workflow dry run; the site builds; an asset loads; backend log clean; `oc -n marvin create job --from=cronjob/marvin-offsite-backup marvin-postcutover` uploads a `postgres/` dump; run the restore test against it (bucket `marvin-backups`, live side `marvin-pg-1` in `marvin`).
- [ ] Afterwards: drop the backend's `Recreate` (Postgres has no single-writer limit), delete the copy Job.

**Rollback** (any time before Postgres has data worth keeping): set `config.dbEngine: sqlite` back and promote the same commit. The backend reopens `marvin.db`, untouched since the stop. Writes made on Postgres after the switch are not carried back — decide in advance how long rollback stays on the table. The `marvin.db` file stays on `marvin-data` as a cold copy until "SQLite retired" in `tasks/todo.md`.
