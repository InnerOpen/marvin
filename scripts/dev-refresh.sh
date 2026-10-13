#!/usr/bin/env bash
# Refresh marvin-dev from production's newest backup: `task dev:refresh` (add `-- --skip-assets` for the
# database only). See docs/manual/postgres.md → "Refreshing dev from production".
#
# Runs `python -m marvin.scripts.refresh_dev` in a Job made from dev's own backup CronJob (it has the backup
# plugin, the R2 token, dev's database and dev's asset storage), with dev's backend scaled to 0 meanwhile and
# always scaled back up. The script refuses unless the source is another bucket than the job's own and the
# database host is the one named here, so it can't replace production's database.
set -euo pipefail

NS=marvin-dev
CRONJOB=marvin-backup-r2
SOURCE_BUCKET=marvin-backups
DB_HOST=marvin-dev-pg-rw
JOB="marvin-refresh-$(date -u +%Y%m%d%H%M%S)"
EXTRA=("$@")

echo "Refreshing ${NS} from ${SOURCE_BUCKET} (newest dump) as job ${JOB}"
oc -n "$NS" get cronjob "$CRONJOB" >/dev/null

oc -n "$NS" scale deploy/marvin-backend --replicas=0
trap 'echo "Scaling the backend back up"; oc -n "$NS" scale deploy/marvin-backend --replicas=1 >/dev/null' EXIT
oc -n "$NS" wait --for=delete pod -l app.kubernetes.io/component=backend --timeout=180s || true

oc -n "$NS" create job --from=cronjob/"$CRONJOB" "$JOB" --dry-run=client -o json \
  | python3 -c '
import json, sys
job = json.load(sys.stdin)
job["spec"]["backoffLimit"] = 0  # a failed refresh is looked at, not retried
job["spec"]["ttlSecondsAfterFinished"] = 86400
pod = job["spec"]["template"]["spec"]
# The backup CronJob must sit next to a backend pod (it shares the data volume); with the backend scaled to 0
# that rule leaves the Job Pending forever. The refresh needs no data volume (database over the network,
# assets to the bucket), so it takes neither the rule nor the volume.
pod.pop("affinity", None)
pod["volumes"] = [v for v in pod.get("volumes", []) if v.get("name") != "data"]
c = pod["containers"][0]
c["volumeMounts"] = [m for m in c.get("volumeMounts", []) if m.get("name") != "data"]
c["command"] = ["python", "-m", "marvin.scripts.refresh_dev"]
c["args"] = ["--source-bucket", sys.argv[1], "--confirm-db-host", sys.argv[2], *sys.argv[3:]]
print(json.dumps(job))
' "$SOURCE_BUCKET" "$DB_HOST" "${EXTRA[@]}" \
  | oc apply -f - >/dev/null

state=""
for _ in $(seq 1 180); do
  state=$(oc -n "$NS" get job "$JOB" -o jsonpath='{.status.succeeded}/{.status.failed}')
  [[ "$state" == 1/* || "$state" == */1 ]] && break
  if oc -n "$NS" get pods -l job-name="$JOB" -o jsonpath='{.items[*].status.conditions[?(@.reason=="Unschedulable")].message}' | grep -q .; then
    echo "Refresh job can't be scheduled:"; oc -n "$NS" get events --field-selector involvedObject.kind=Pod | grep "$JOB" | tail -2
    exit 1
  fi
  sleep 10
done
oc -n "$NS" logs "job/$JOB" -c backup | grep -E "refresh|database:|outbound: .*TOTAL|assets:" || true
[[ "$state" == 1/* ]] || { echo "Refresh FAILED (job ${JOB} kept for its logs)"; exit 1; }

trap - EXIT
oc -n "$NS" scale deploy/marvin-backend --replicas=1 >/dev/null
oc -n "$NS" rollout status deploy/marvin-backend --timeout=300s
echo "Done: dev holds production's newest backup, with outbound activity paused."
