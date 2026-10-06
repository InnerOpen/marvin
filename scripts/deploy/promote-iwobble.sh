#!/usr/bin/env bash
# Promote one CI-built commit to production (release `marvin`, namespace `marvin`, iwobble cluster).
#
#   scripts/deploy/promote-iwobble.sh <commit>          # a sha or ref on origin; usually develop's tip
#   scripts/deploy/promote-iwobble.sh <commit> --dry-run
#
# Production pins `image.tag=develop-<7-char sha>`: the immutable backend and frontend images CI built from
# exactly that commit. The chart comes from the same commit (`git archive`), so chart and image always match.
# Every promotion is a helm revision: `helm history marvin -n marvin`; undo with
# `helm rollback marvin <revision> -n marvin`.
#
# Needs: git (with origin fetched), docker (manifest inspect, public GHCR), helm, oc logged in.
set -euo pipefail

ref="${1:?usage: promote-iwobble.sh <commit> [--dry-run]}"
dry_run="${2:-}"
repo_root="$(git rev-parse --show-toplevel)"

git -C "$repo_root" fetch -q origin
sha="$(git -C "$repo_root" rev-parse --short=7 "$ref^{commit}")"
tag="develop-$sha"

for image in marvin-backend marvin-frontend; do
  if ! docker manifest inspect "ghcr.io/inneropen/$image:$tag" >/dev/null 2>&1; then
    echo "ghcr.io/inneropen/$image:$tag not found; has CI's Docker Build finished for $sha?" >&2
    exit 1
  fi
done

chart_dir="$(mktemp -d)"
trap 'rm -rf "$chart_dir"' EXIT
git -C "$repo_root" archive "$sha" marvin-chart | tar -x -C "$chart_dir"

args=(upgrade marvin "$chart_dir/marvin-chart" -n marvin
  -f "$chart_dir/marvin-chart/values-iwobble.yaml"
  --set "image.tag=$tag"
  --description "promote $tag")

if [[ "$dry_run" == "--dry-run" ]]; then
  helm "${args[@]}" --dry-run=server >/dev/null
  echo "dry run ok: would promote $tag"
  exit 0
fi

helm "${args[@]}" >/dev/null
oc -n marvin rollout status deploy/marvin-backend --timeout=600s
oc -n marvin rollout status deploy/marvin-frontend --timeout=300s
echo "promoted $tag ($(helm history marvin -n marvin --max 1 -o json | python3 -c 'import json,sys; print("revision", json.load(sys.stdin)[-1]["revision"])'))"
