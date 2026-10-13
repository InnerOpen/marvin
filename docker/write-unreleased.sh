#!/usr/bin/env bash
# Record the commits this build contains that no release lists yet, for the admin's "What's new".
#
# Images are built from the code commit; the release job adds that commit's CHANGELOG.md section
# afterwards, in a `chore(release)` commit that triggers no rebuild. So the image's changelog always
# stops one release short of its own code. This writes the gap — every commit since the last
# release tag — and services/changelog.py shows it as an "Unreleased" entry above the changelog.
#
# Usage: docker/write-unreleased.sh [OUT_FILE] [REV]   (defaults: UNRELEASED.txt, HEAD)
# Needs the full history and tags (actions/checkout `fetch-depth: 0`). Without a reachable release
# tag — a shallow clone — it writes the header alone rather than the whole history. At a release
# commit (the tag is on REV itself) the range is empty, so a version-tagged image lists nothing.
set -euo pipefail

out="${1:-UNRELEASED.txt}"
rev="${2:-HEAD}"

last_tag="$(git describe --tags --abbrev=0 --match 'v[0-9]*' "$rev" 2>/dev/null || true)"
{
    echo "# since: ${last_tag:-none}"
    echo "# built: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    if [ -n "$last_tag" ]; then
        # sha<TAB>subject, newest first; the release bookkeeping commits are not changes.
        git log --no-merges --format='%H%x09%s' "${last_tag}..${rev}" | grep -Ev $'^[0-9a-f]+\tchore\\(release\\):' || true
    fi
} >"$out"
echo "Wrote $(grep -cv '^#' "$out" || true) unreleased commit(s) since ${last_tag:-<no tag>} to $out"
