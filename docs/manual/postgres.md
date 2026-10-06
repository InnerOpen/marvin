# Postgres

Marvin runs on SQLite or Postgres (`config.dbEngine`). On the iwobble cluster Postgres is a [CloudNativePG](https://cloudnative-pg.io) (CNPG) cluster per environment, rendered by the Helm chart. This page covers the `marvin-dev` environment, the cluster's backups and restores, the SQLite → Postgres copy tool and the production cutover.

What lives where once an environment is on Postgres:

| What | Where |
|---|---|
| The database | CNPG cluster `<name>` (one instance), its own PVC; app connection in Secret `<name>-app`, Service `<name>-rw` |
| Uploaded assets, `.secret` (decrypts stored secrets), `templates/` | the release's data PVC, as before |
| Base backups + WAL archive (point in time) | `s3://marvin-backups/cnpg/<name>/` via the Barman Cloud plugin |
| Nightly logical dump + config + assets | the off-site backup CronJob: `[prefix]postgres/marvin-<stamp>.dump`, `config/`, `assets/` ([Off-site backup](offsite-backup.md)) |

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
      enabled: true           # ObjectStore + plugin WAL archiving + nightly ScheduledBackup
      existingSecret: marvin-r2-backup
      bucket: marvin-backups  # endpoint: empty = BACKUP_S3_ENDPOINT looked up from that Secret
      retentionPolicy: 30d
```

The cluster can be enabled while `dbEngine` is still `sqlite` — that is how production gets its database ready before the cutover. The Cluster and ObjectStore carry `helm.sh/resource-policy: keep`: `helm uninstall` leaves the database and its PVC alone; delete them by hand when you mean it. With `dbEngine: postgres` the backend may roll (`RollingUpdate`) instead of `Recreate`; keep one replica while assets are on the RWO data volume.

Postgres 17 is used everywhere on purpose: the clusters, the CI test job and the backend image's `pg_dump` (Debian's `postgresql-client`). A `pg_dump` 17 archive does not restore cleanly into Postgres 16. Move all three together.

## Cluster prerequisites (once)

1. **CloudNativePG operator** — installed from OperatorHub (`cloudnative-pg`, `openshift-operators`, manual approval). Check: `oc get csv -n openshift-operators | grep cloudnative`.
2. **cert-manager** — the Barman Cloud plugin needs it for the operator ↔ plugin TLS. Install *cert-manager Operator for Red Hat OpenShift* from OperatorHub (default channel), then check `oc get crd certificates.cert-manager.io`.
3. **Barman Cloud plugin** into the operator's namespace (it must be the same namespace as the operator):

    ```bash
    mkdir -p /tmp/barman-cloud && cat > /tmp/barman-cloud/kustomization.yaml <<'EOF'
    apiVersion: kustomize.config.k8s.io/v1beta1
    kind: Kustomization
    namespace: openshift-operators
    resources:
      - https://github.com/cloudnative-pg/plugin-barman-cloud/releases/download/v0.15.1/manifest.yaml
    EOF
    oc apply -k /tmp/barman-cloud
    # The upstream Deployment pins runAsUser/runAsGroup 10001, which restricted-v2 rejects:
    oc adm policy add-scc-to-user nonroot-v2 -z barman-cloud -n openshift-operators
    oc -n openshift-operators rollout restart deploy/barman-cloud
    oc -n openshift-operators rollout status deploy/barman-cloud
    ```

    The plugin replaces CNPG's in-tree `spec.backup.barmanObjectStore`, deprecated since 1.26 and removed in 1.31. Without it, render with `postgres.cluster.backup.enabled=false` (no backups) until it is in.

## The `marvin-dev` environment

Release `marvin` in namespace `marvin-dev`, values `marvin-chart/values-dev.yaml`: split mode, `:develop` images with `pullPolicy: Always`, CNPG cluster `marvin-dev-pg`, a 2 Gi assets PVC, routes `marvin-marvin-dev.apps.ocp4.iwobble.com` (UI) and `marvin-api-marvin-dev.apps.ocp4.iwobble.com` (API) with `X-Robots-Tag: noindex, nofollow`, production's integration plugins, and the off-site backup under `dev/`.

Bring it up (the project exists):

```bash
# 1. R2 credentials, straight from pass (nothing printed, nothing on argv)
oc -n marvin-dev create secret generic marvin-r2-backup \
  --from-file=AWS_ACCESS_KEY_ID=<(pass show marvin/r2/access-key-id | head -n1 | tr -d '\n') \
  --from-file=AWS_SECRET_ACCESS_KEY=<(pass show marvin/r2/secret-access-key | head -n1 | tr -d '\n') \
  --from-file=BACKUP_S3_ENDPOINT=<(pass show marvin/r2/endpoint | head -n1 | tr -d '\n') \
  --from-literal=BACKUP_S3_BUCKET=marvin-backups

# 2. Everything else: CNPG Cluster + ObjectStore + ScheduledBackup, then the app
helm upgrade --install marvin marvin-chart -n marvin-dev -f marvin-chart/values-dev.yaml

# 3. Watch the database come up (the backend restarts until marvin-dev-pg-app exists)
oc -n marvin-dev get cluster marvin-dev-pg -w          # "Cluster in healthy state"
oc -n marvin-dev rollout status deploy/marvin-backend
oc -n marvin-dev get backup                             # the immediate first base backup: completed
```

On first start against the empty database the backend runs the migrations and seeds the default group and admin, as on any new install. Dev follows `develop`: `oc -n marvin-dev rollout restart deploy/marvin-backend deploy/marvin-frontend` picks up the newest build.

!!! warning "Production data in dev"
    Loading a copy of production into dev (below) brings real users, tokens, webhook URLs and scheduled tasks. Stored secrets stay unreadable (dev has its own `.secret`), but plain-text outgoing webhooks — e.g. a Cloudflare Pages deploy hook — would fire from dev's scheduler. Before the backend starts on such a copy, set `SCHEDULER_ENABLED=false` (in `extraEnv`) or disable those webhooks and tasks.

## Storage

`managed-nfs-storage` (nfs-subdir-external-provisioner, NFS 4.2 `hard` mounts from the NAS) is the only storage class on ocp4, so the clusters use it. The export keeps the pod's UID (no squashing — `marvin-data` files are owned by the pod user), which `initdb` needs. CNPG recommends block storage and discourages NFS: Postgres relies on `fsync` and locking semantics an NFS server may not give, and a misbehaving export can corrupt the database. Mitigations here: one instance, `hard` mounts, WAL archived off the cluster continuously, a nightly base backup and a nightly logical dump. Better options, in order of effort:

- **iSCSI from the NAS** via democratic-csi (ZFS zvols as block PVs, snapshots for free).
- **LVM Storage (LVMS) operator** on a node with a spare disk: local block PVs, fastest; the database is then pinned to that node.
- OpenShift Data Foundation (Ceph) — heavy for one small database.

Moving a cluster to a new class = restore from backup into a new cluster with the new `storageClass` (below), then point the app at it.

## Backups

Two independent copies:

1. **CNPG (physical, point in time)** — the plugin archives every WAL segment as it fills to `s3://marvin-backups/cnpg/<cluster>/wals/`, and the `ScheduledBackup` `<cluster>-nightly` takes a base backup at 08:00 UTC (plus one right after creation) into `.../base/`. `retentionPolicy: 30d` keeps what is needed to recover to any moment of the last 30 days. Check:

    ```bash
    oc -n marvin-dev get backup                                  # phase completed
    oc -n marvin-dev get cluster marvin-dev-pg -o jsonpath='{.status.conditions[?(@.type=="ContinuousArchiving")].status}'
    oc -n marvin-dev get objectstore marvin-dev-pg-backup -o yaml   # status: first/last recoverability point
    ```

    An on-demand base backup: `oc -n marvin-dev create -f - <<<'{"apiVersion":"postgresql.cnpg.io/v1","kind":"Backup","metadata":{"generateName":"marvin-dev-pg-manual-"},"spec":{"cluster":{"name":"marvin-dev-pg"},"method":"plugin","pluginConfiguration":{"name":"barman-cloud.cloudnative-pg.io"}}}'`

2. **Off-site job (logical)** — the nightly `marvin-offsite-backup` CronJob `pg_dump`s the database (plus config and assets). Engine-independent: it restores into any Postgres ≥ 17 without CNPG. See [Off-site backup](offsite-backup.md#postgres).

### Restore a cluster (and point-in-time recovery)

CNPG restores into a **new** cluster bootstrapped from the object store; it never rewinds a running one. Leave out `recoveryTarget` for the latest state; give `targetTime` (or `targetLSN`, `targetXID`) for a point in time.

```bash
oc -n marvin-dev apply -f - <<'EOF'
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: marvin-dev-pg-r1
spec:
  instances: 1
  imageName: ghcr.io/cloudnative-pg/postgresql:17
  storage: {size: 10Gi, storageClass: managed-nfs-storage}
  bootstrap:
    recovery:
      source: origin
      database: marvin
      owner: marvin
      recoveryTarget:
        targetTime: "2026-10-06 18:30:00+00"   # omit recoveryTarget for "as late as possible"
  externalClusters:
    - name: origin
      plugin:
        name: barman-cloud.cloudnative-pg.io
        parameters:
          barmanObjectName: marvin-dev-pg-backup
          serverName: marvin-dev-pg
EOF
oc -n marvin-dev get cluster marvin-dev-pg-r1 -w
oc -n marvin-dev exec marvin-dev-pg-r1-1 -- psql -d marvin -tAc "select count(*) from entries"
```

To make the restored cluster the app's database, point the release at it (`postgres.existingSecret: marvin-dev-pg-r1-app`, or make it the chart's cluster with `postgres.cluster.name: marvin-dev-pg-r1` plus its `bootstrap`) and give it its own archive: `postgres.cluster.backup.serverName: marvin-dev-pg-r1` — CNPG refuses to archive WAL into a non-empty folder, so a restored cluster never writes under the old name. A test restore is just: create, count, `oc delete cluster marvin-dev-pg-r1`.

### Restore from the logical dump

From a workstation with the repo, `pass` and `oc` — into an **empty** database (a fresh CNPG cluster, or the app's after a deliberate drop):

```bash
# 1. fetch + verify the newest dump (dev's keys are under dev/)
mkdir -p /tmp/r && chmod 700 /tmp/r
AWS_ACCESS_KEY_ID=$(pass show marvin/r2/access-key-id | head -n1) \
AWS_SECRET_ACCESS_KEY=$(pass show marvin/r2/secret-access-key | head -n1) \
BACKUP_S3_ENDPOINT=$(pass show marvin/r2/endpoint | head -n1) BACKUP_S3_BUCKET=marvin-backups \
BACKUP_S3_PREFIX=dev/ DB_ENGINE=postgres PYTHONPATH=src \
  uv run python -m marvin.scripts.offsite_backup restore --target /tmp/r --skip-config --skip-assets

# 2. load it through a port-forward with pg_restore >= 17 (the backend image has one)
oc -n marvin-dev port-forward svc/marvin-dev-pg-r1-rw 15432:5432 &
S=marvin-dev-pg-r1-app; g() { oc -n marvin-dev get secret $S -o jsonpath="{.data.$1}" | base64 -d; }
docker run --rm --network host -v /tmp/r:/r:ro -e PGPASSWORD="$(g password)" --entrypoint pg_restore \
  ghcr.io/inneropen/marvin-backend:develop --exit-on-error --no-owner \
  -h 127.0.0.1 -p 15432 -U "$(g username)" -d "$(g dbname)" /r/marvin.dump
kill %1; rm -rf /tmp/r
```

## SQLite → Postgres copy tool

`python -m marvin.scripts.sqlite_to_postgres` ships in the backend image. The target is the app's own Postgres (`DB_ENGINE=postgres` + `POSTGRES_*`).

```text
python -m marvin.scripts.sqlite_to_postgres --source /app/data/marvin.db --dry-run
python -m marvin.scripts.sqlite_to_postgres --source /app/data/marvin.db [--truncate] [--batch-size 1000]
```

What it does:

1. Opens the SQLite file **read-only**, in one read transaction (it never writes the source).
2. Runs `alembic upgrade head` on the target, then requires the source's Alembic revision to equal the target's — copy with the same image version that last ran on the file.
3. Refuses a target that holds data unless `--truncate` (re-runs with `--truncate` are idempotent).
4. Checks every value against the target column type before writing anything — SQLite keeps booleans as 0/1, datetimes, JSON and GUIDs as text, and enforces neither lengths nor types. Anything that does not convert exactly (invalid JSON, a datetime without a time, too long for its column, a NUL byte, NULL in a NOT NULL column, an unknown enum label) is listed and nothing is written. Lossless normalisations are reported as notes (e.g. a `+00:00` offset in a naive timestamp column → stored as naive UTC).
5. In **one transaction**: truncate, drop the foreign keys, copy every table except `alembic_version` in dependency order in batches, re-create the foreign keys (Postgres re-checks every row — an orphan SQLite let through fails here, named), reset serial sequences, and verify: per-table row counts and a checksum over every column of every row must match on both sides. Any failure rolls everything back.

`--dry-run` writes nothing: source and target counts, plus the full value check. Exit code 0 = copied and verified, 1 = refused or failed (the log says why), 2 = not configured for Postgres.

Rehearsal on a copy of production (2026-10-06, Postgres 16 and 17, also inside the built image as a random UID): 61 tables, 15,949 rows, 94 foreign keys re-validated, every checksum equal, one note (`ai_executions.completed_at`: one value carried `+00:00`). About 10 s. The backend then started on the copy and served entries, event-type connections, workflows and a workflow dry run.

### Loading production data into dev (rehearsal)

Run the tool locally against dev's database through a port-forward — the production file never lands on the cluster's dev volume. Take a consistent copy of production's file the same way as the cutover rehearsal (SQLite backup API in the backend pod, `oc cp`, delete the pod-side copy), treat the local copy as sensitive and delete it afterwards. Read the warning under [The marvin-dev environment](#the-marvin-dev-environment) first.

```bash
oc -n marvin-dev scale deploy/marvin-backend --replicas=0
oc -n marvin-dev port-forward svc/marvin-dev-pg-rw 15432:5432 &
S=marvin-dev-pg-app; g() { oc -n marvin-dev get secret $S -o jsonpath="{.data.$1}" | base64 -d; }
DB_ENGINE=postgres POSTGRES_SERVER=127.0.0.1 POSTGRES_PORT=15432 POSTGRES_USER=$(g username) \
  POSTGRES_PASSWORD=$(g password) POSTGRES_DB=$(g dbname) DATA_DIR=$(mktemp -d) PYTHONPATH=src \
  uv run python -m marvin.scripts.sqlite_to_postgres --source /path/to/marvin-copy.db --truncate
kill %1; oc -n marvin-dev scale deploy/marvin-backend --replicas=1
```

## Production cutover

Planned downtime of a few minutes; the SQLite file is never modified, so it is the rollback.

**Days before**

- [ ] Plugin + cert-manager installed (above); `marvin-r2-backup` exists in `marvin` (it does).
- [ ] Enable the cluster while still on SQLite: in `values-iwobble.yaml` set `postgres.cluster.enabled: true`, `name: marvin-pg`, `storage.storageClass: managed-nfs-storage`, `backup.enabled: true`, `backup.existingSecret: marvin-r2-backup`, `backup.bucket: marvin-backups`; keep `config.dbEngine: sqlite`. Promote (`scripts/deploy/promote-iwobble.sh <sha>`). Check the cluster is healthy and the first base backup completed.
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
- [ ] Switch: in `values-iwobble.yaml` set `config.dbEngine: postgres` (keep `split.backend.strategy: Recreate` for this first deploy), commit, and promote the **same** commit's image: `scripts/deploy/promote-iwobble.sh <sha>` (scales the backend back to 1).
- [ ] Smoke: log in; entries list; open an entry and save it; a workflow dry run; the site builds; an asset loads; backend log clean; `oc -n marvin create job --from=cronjob/marvin-offsite-backup marvin-postcutover` uploads a `postgres/` dump.
- [ ] Afterwards: drop the backend's `Recreate` (Postgres has no single-writer limit), delete the copy Job.

**Rollback** (any time before Postgres has data worth keeping): set `config.dbEngine: sqlite` back and promote the same commit. The backend reopens `marvin.db`, untouched since the stop. Writes made on Postgres after the switch are not carried back — decide in advance how long rollback stays on the table. The `marvin.db` file stays on `marvin-data` as a cold copy until "SQLite retired" in `tasks/todo.md`.
