#!/usr/bin/env bash
# Promote one CI-built commit to production (release `marvin`, namespace `marvin`, iwobble cluster) by hand.
# The usual path is the Promote workflow (.github/workflows/promote.yml); this is its manual fallback.
#
#   scripts/deploy/promote-iwobble.sh <commit>          # a sha or ref on origin; usually develop's tip
#   scripts/deploy/promote-iwobble.sh <commit> --dry-run
#
# See promote.sh for what a promotion does. Every promotion is a helm revision: `helm history marvin -n marvin`;
# undo with `scripts/deploy/rollback.sh marvin <revision>`.
#
# Needs: git (origin reachable), curl, helm, kubectl, logged in to the cluster.
set -euo pipefail

ref="${1:?usage: promote-iwobble.sh <commit> [--dry-run]}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

git -C "$here" fetch -q origin
"$here/promote.sh" "$ref" marvin values-iwobble.yaml ${2:+"$2"}
