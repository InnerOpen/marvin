#!/usr/bin/env bash
# Smoke-check a Marvin release through its public Routes, the way a browser reaches it.
#
#   scripts/deploy/smoke.sh <namespace> [<commit>]
#
# Checks the UI's /healthz and the API's /readyz (database reachable) answer 200. With <commit>, also that
# /version.json reports that build as the live frontend (so the new pods, not the old ones, are serving) and that the
# backend pods have logged no ERROR or Traceback since they started. Without it, only reachability is checked.
# Hosts come from the release's Routes, so there is no per-environment config. No credentials are used.
#
# Needs: curl, kubectl (or KUBECTL=oc) pointed at the cluster.
set -euo pipefail

namespace="${1:?usage: smoke.sh <namespace> [<commit>]}"
expect="${2:-}"
release="${RELEASE:-marvin}"
kubectl="${KUBECTL:-kubectl}"

SETTLE_SECONDS=15     # let the router pick up the new endpoints and the backend finish starting up
ATTEMPTS=12           # each check retries for up to ATTEMPTS * RETRY_SECONDS
RETRY_SECONDS=5

route_url() {
  local host tls
  host="$("$kubectl" -n "$namespace" get route "$1" -o jsonpath='{.spec.host}')"
  tls="$("$kubectl" -n "$namespace" get route "$1" -o jsonpath='{.spec.tls.termination}')"
  echo "$([[ -n "$tls" ]] && echo https || echo http)://$host"
}

# Retries until <predicate> holds for the body/status of <url>; prints what it saw either way.
expect_url() {
  local label="$1" url="$2" predicate="$3" status body
  for ((i = 1; i <= ATTEMPTS; i++)); do
    body="$(curl -sS --max-time 10 -w '\n%{http_code}' "$url" 2>/dev/null || true)"
    status="${body##*$'\n'}"
    body="${body%$'\n'*}"
    if "$predicate" "$status" "$body"; then
      echo "ok   $label: $status ${body:0:120}"
      return 0
    fi
    sleep "$RETRY_SECONDS"
  done
  echo "FAIL $label: $status ${body:0:200} ($url)" >&2
  return 1
}

# The predicates are called through expect_url.
# shellcheck disable=SC2317
is_ok() { [[ "$1" == 200 ]]; }
# shellcheck disable=SC2317
is_expected_build() { [[ "$1" == 200 && "$2" == *"\"frontend\":\"${expect:0:12}"* ]]; }

ui="$(route_url "$release")"
api="$(route_url "$release-api")"
sleep "$SETTLE_SECONDS"

failed=0
expect_url "ui /healthz" "$ui/healthz" is_ok || failed=1
expect_url "api /readyz" "$api/readyz" is_ok || failed=1

if [[ -n "$expect" ]]; then
  expect_url "ui /version.json is ${expect:0:12}" "$ui/version.json" is_expected_build || failed=1
  # The pods are new since the rollout, so their whole log is this release's.
  errors="$("$kubectl" -n "$namespace" logs --tail=-1 --prefix --all-containers \
    -l "app.kubernetes.io/instance=$release,app.kubernetes.io/component=backend" | grep -E 'ERROR|Traceback' || true)"
  if [[ -n "$errors" ]]; then
    echo "FAIL backend logged errors since the rollout:" >&2
    head -20 <<<"$errors" >&2
    failed=1
  else
    echo "ok   backend log: no ERROR or Traceback"
  fi
fi

exit "$failed"
