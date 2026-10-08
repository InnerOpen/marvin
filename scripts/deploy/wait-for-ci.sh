#!/usr/bin/env bash
# Wait for the CI workflows that gate a promotion to finish on one develop commit.
#
#   scripts/deploy/wait-for-ci.sh <sha> [--latest-only]
#
# Exits 0 once Docker Build, Test Suite and SDK Quality Gate have all succeeded for the push of <sha>, and 1 when one
# failed. With --latest-only it exits 3 as soon as develop moves past <sha>: the newer push promotes instead (and its CI
# cancels this commit's). A run GitHub cancelled while <sha> is still wanted (usually no runner picked it up) is
# re-run, up to MAX_ATTEMPTS times.
#
# Needs: gh (authenticated; actions:write to re-run), jq. GITHUB_REPOSITORY defaults to InnerOpen/marvin.
set -euo pipefail

sha="${1:?usage: wait-for-ci.sh <sha> [--latest-only]}"
latest_only="${2:-}"
repo="${GITHUB_REPOSITORY:-InnerOpen/marvin}"

WORKFLOWS=("Docker Build" "Test Suite" "SDK Quality Gate")
POLL_SECONDS=30
MAX_ATTEMPTS=3

while true; do
  # Runs first, then the tip: a cancel caused by a newer push is visible only after that push is.
  runs="$(gh api "repos/$repo/actions/runs?head_sha=$sha&event=push&branch=develop&per_page=100")"
  if [[ "$latest_only" == "--latest-only" ]]; then
    tip="$(gh api "repos/$repo/commits/develop" -q .sha)"
    if [[ "$tip" != "$sha" ]]; then
      echo "develop has moved on to ${tip:0:7}; that push promotes instead of ${sha:0:7}"
      exit 3
    fi
  fi

  waiting=()
  for workflow in "${WORKFLOWS[@]}"; do
    run="$(jq -c --arg wf "$workflow" '[.workflow_runs[] | select(.name == $wf)] | max_by(.run_number) // empty' <<<"$runs")"
    if [[ -z "$run" ]]; then
      waiting+=("$workflow (not started)")
      continue
    fi
    IFS=$'\t' read -r id status conclusion attempt url \
      < <(jq -r '[.id, .status, (.conclusion // "-"), .run_attempt, .html_url] | @tsv' <<<"$run")
    case "$status/$conclusion" in
      completed/success) ;;
      completed/cancelled)
        if ((attempt >= MAX_ATTEMPTS)); then
          echo "$workflow was cancelled on all $attempt attempts: $url" >&2
          exit 1
        fi
        gh api -X POST "repos/$repo/actions/runs/$id/rerun-failed-jobs" >/dev/null
        echo "$workflow was cancelled; re-running it (attempt $((attempt + 1)))"
        waiting+=("$workflow (re-run)")
        ;;
      completed/*)
        echo "$workflow concluded $conclusion: $url" >&2
        exit 1
        ;;
      *) waiting+=("$workflow ($status)") ;;
    esac
  done

  if ((${#waiting[@]} == 0)); then
    echo "CI is green for ${sha:0:7}: ${WORKFLOWS[*]}"
    exit 0
  fi
  echo "waiting: ${waiting[*]}"
  sleep "$POLL_SECONDS"
done
