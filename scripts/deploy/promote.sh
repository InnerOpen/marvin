#!/usr/bin/env bash
# Promote one CI-built commit into a Marvin release: helm upgrade with the chart from that commit and the images CI
# built from it, then wait for both Deployments to roll out.
#
#   scripts/deploy/promote.sh <commit> <namespace> <values-file> [--dry-run]
#   scripts/deploy/promote.sh f0e7846 marvin-dev values-dev.yaml
#
# <values-file> names a file in marvin-chart/ at that commit. The release pins `image.tag=develop-<7-char sha>`: the
# immutable backend and frontend images CI built from exactly that commit, and the chart comes from the same commit
# (`git archive`), so chart and image always match. Every promotion is a helm revision described
# "promote develop-<sha>"; the last line printed is "revision <n>". Undo with scripts/deploy/rollback.sh.
#
# --dry-run renders the chart with the cluster's capabilities and server-side dry-run applies every object, which
# checks the chart, the values and the caller's RBAC for each object without changing anything.
#
# Used by .github/workflows/promote.yml and, through promote-iwobble.sh, by hand.
# Needs: git with the commit present, curl, helm, kubectl (or KUBECTL=oc) pointed at the cluster.
set -euo pipefail

usage="usage: promote.sh <commit> <namespace> <values-file> [--dry-run]"
ref="${1:?$usage}"
namespace="${2:?$usage}"
values="${3:?$usage}"
dry_run="${4:-}"
release="${RELEASE:-marvin}"
kubectl="${KUBECTL:-kubectl}"
repo_root="$(git rev-parse --show-toplevel)"

sha="$(git -C "$repo_root" rev-parse --short=7 "$ref^{commit}")"
tag="develop-$sha"

# Anonymous pull token, then HEAD the manifest: the same check as `docker manifest inspect`, without docker.
image_exists() {
  local token
  token="$(curl -fsS "https://ghcr.io/token?scope=repository:inneropen/$1:pull" | sed -E 's/.*"token":"([^"]+)".*/\1/')"
  curl -fsS -o /dev/null -I -H "Authorization: Bearer $token" \
    -H "Accept: application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json" \
    -H "Accept: application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json" \
    "https://ghcr.io/v2/inneropen/$1/manifests/$2"
}

for image in marvin-backend marvin-frontend; do
  if ! image_exists "$image" "$tag"; then
    echo "ghcr.io/inneropen/$image:$tag not found; has CI's Docker Build finished for $sha?" >&2
    exit 1
  fi
done

chart_dir="$(mktemp -d)"
trap 'rm -rf "$chart_dir"' EXIT
git -C "$repo_root" archive "$sha" marvin-chart | tar -x -C "$chart_dir"
chart="$chart_dir/marvin-chart"
[[ -f "$chart/$values" ]] || { echo "marvin-chart/$values does not exist at $sha" >&2; exit 1; }

values_args=(-n "$namespace" -f "$chart/$values" --set "image.tag=$tag")

if [[ "$dry_run" == "--dry-run" ]]; then
  helm template "$release" "$chart" "${values_args[@]}" --is-upgrade --validate \
    | "$kubectl" apply -n "$namespace" --server-side --force-conflicts --field-manager=promote-dry-run \
      --dry-run=server -f - >/dev/null
  echo "dry run ok: $release in $namespace would promote $tag"
  exit 0
fi

helm upgrade "$release" "$chart" "${values_args[@]}" --description "promote $tag" >/dev/null
"$kubectl" -n "$namespace" rollout status "deploy/$release-backend" --timeout=600s
"$kubectl" -n "$namespace" rollout status "deploy/$release-frontend" --timeout=300s
echo "promoted $tag to $release in $namespace"
echo "revision $(helm history "$release" -n "$namespace" --max 1 | awk 'NR == 2 {print $1}')"
