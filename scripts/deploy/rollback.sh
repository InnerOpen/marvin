#!/usr/bin/env bash
# Roll a Marvin release back to an earlier helm revision and wait for both Deployments to roll out.
#
#   scripts/deploy/rollback.sh <namespace> <revision>
#
# A no-op when the release is already at <revision> (the promotion failed before it upgraded anything). Rolls back
# chart and images together. The database is not rolled back: the backend migrates at startup, so the older code runs
# on the newer schema. That holds for added tables and columns, not for a migration that drops or renames something
# the older code reads.
#
# Needs: helm, kubectl (or KUBECTL=oc) pointed at the cluster.
set -euo pipefail

namespace="${1:?usage: rollback.sh <namespace> <revision>}"
revision="${2:?usage: rollback.sh <namespace> <revision>}"
release="${RELEASE:-marvin}"
kubectl="${KUBECTL:-kubectl}"

current="$(helm history "$release" -n "$namespace" --max 1 | awk 'NR == 2 {print $1}')"
if [[ "$current" == "$revision" ]]; then
  echo "$release in $namespace is already at revision $revision; nothing to roll back"
  exit 0
fi

helm rollback "$release" "$revision" -n "$namespace"
"$kubectl" -n "$namespace" rollout status "deploy/$release-backend" --timeout=600s
"$kubectl" -n "$namespace" rollout status "deploy/$release-frontend" --timeout=300s
echo "rolled $release in $namespace back from revision $current to $revision"
