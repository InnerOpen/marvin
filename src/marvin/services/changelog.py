"""Release notes for the admin's update banner, read from the repo's CHANGELOG.md.

python-semantic-release writes the changelog on every release, so it is already the list of what
each version changed; this parses it rather than keeping a second copy. The format it relies on:

    ## v1.0.0-rc.158 (2026-10-03)

    ### Features

    - **admin**: Group the admin nav, ...
      ([`dffdd86`](https://github.com/InnerOpen/marvin/commit/dffdd86...))

Release notes are a nicety: a missing or unreadable changelog yields no releases, never an error.
The file only changes with a new image, so it is parsed once per process.
"""

import re
from collections.abc import Iterable, Sequence
from functools import lru_cache
from pathlib import Path

import marvin
from marvin.core.root_logger import get_logger
from marvin.core.settings.static import APP_VERSION, BASE_DIR
from marvin.schemas.app import ChangelogItem, ChangelogRelease, ChangelogSection

logger = get_logger(__name__)

CHANGELOG_FILENAME = "CHANGELOG.md"

# A request never returns more than this many releases, however far back `since` reaches.
MAX_RELEASES = 20
# When the caller's starting point can't be placed (garbage or unknown version, unreleased commit),
# show this many of the latest releases instead of nothing.
FALLBACK_RELEASES = 5

# Bullets before any `###` heading (the very first release has no sections) land in this one.
UNSECTIONED_TITLE = "Changes"

# Shortest commit prefix worth matching; anything shorter would hit unrelated commits.
MIN_COMMIT_PREFIX = 7

_RELEASE_RE = re.compile(
    r"^##\s+\[?v?(?P<version>\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)\]?"
    r"(?:\s*(?:\(|-\s*)(?P<date>\d{4}-\d{2}-\d{2})\)?)?"
)
_SECTION_RE = re.compile(r"^###\s+(?P<title>.+?)\s*$")
_BULLET_RE = re.compile(r"^[-*]\s+(?P<text>.*)$")
_SCOPE_RE = re.compile(r"^\*\*(?P<scope>[^*]+)\*\*:\s*(?P<rest>.*)$")
# The trailing `([#20](pr url), [`abc1234`](commit url))` group semantic-release appends.
_LINKS_RE = re.compile(r"\s*\(\[.*$")
_COMMIT_LINK_RE = re.compile(r"\[`(?P<short>[0-9a-f]{7,40})`\]\((?P<url>[^)\s]+)\)")
_URL_SHA_RE = re.compile(r"/commit/(?P<sha>[0-9a-f]{7,40})")
_SEMVER_RE = re.compile(r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)(?:-(?P<pre>[0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


# ── versions ─────────────────────────────────────────────────────────────────


def version_key(version: str) -> tuple | None:
    """A sort key that orders versions by semver precedence, or None for a non-version.

    Prerelease identifiers compare numerically when numeric, so rc.9 < rc.10 < rc.158, and a final
    release sorts after all of its prereleases (1.0.0-rc.158 < 1.0.0).
    """
    m = _SEMVER_RE.match(version.strip()) if version else None
    if not m:
        return None
    core = (int(m["major"]), int(m["minor"]), int(m["patch"]))
    if m["pre"] is None:
        return (*core, (1,))
    # Numeric identifiers rank below alphanumeric ones (semver §11.4.3); the tag keeps int/str apart.
    ids = tuple((0, int(part), "") if part.isdigit() else (1, 0, part) for part in m["pre"].split("."))
    return (*core, (0, *ids))


# ── parsing ──────────────────────────────────────────────────────────────────


def _parse_item(text: str) -> ChangelogItem:
    commit = commit_url = None
    if link := _COMMIT_LINK_RE.search(text):
        commit_url = link["url"]
        full = _URL_SHA_RE.search(commit_url)
        commit = full["sha"] if full else link["short"]
    summary = _LINKS_RE.sub("", text).strip()
    scope = None
    if m := _SCOPE_RE.match(summary):
        scope, summary = m["scope"].strip(), m["rest"].strip()
    return ChangelogItem(scope=scope, summary=summary, commit=commit, commit_url=commit_url)


def parse_changelog(text: str) -> list[ChangelogRelease]:
    """Every release in the changelog, in file order (semantic-release writes newest first)."""
    releases: list[ChangelogRelease] = []
    section: ChangelogSection | None = None
    bullet: list[str] | None = None

    def flush_bullet() -> None:
        nonlocal bullet, section
        if bullet is None or not releases:
            bullet = None
            return
        if section is None:
            section = ChangelogSection(title=UNSECTIONED_TITLE)
            releases[-1].sections.append(section)
        section.items.append(_parse_item(" ".join(bullet)))
        bullet = None

    for line in text.splitlines():
        if m := _RELEASE_RE.match(line):
            flush_bullet()
            releases.append(ChangelogRelease(version=m["version"], date=m["date"]))
            section = None
        elif m := _SECTION_RE.match(line):
            flush_bullet()
            if releases:
                section = ChangelogSection(title=m["title"])
                releases[-1].sections.append(section)
        elif m := _BULLET_RE.match(line):
            flush_bullet()
            bullet = [m["text"].strip()]
        elif bullet is not None and line.startswith((" ", "\t")) and line.strip():
            bullet.append(line.strip())  # a wrapped summary or the commit-link line
        else:
            flush_bullet()

    flush_bullet()
    for release in releases:
        release.sections = [s for s in release.sections if s.items]
    return releases


# ── loading ──────────────────────────────────────────────────────────────────


def find_changelog() -> Path | None:
    """The changelog shipped with this install: the image's /app (BASE_DIR) or a source checkout's root."""
    candidates = (BASE_DIR / CHANGELOG_FILENAME, Path(marvin.__file__).resolve().parents[2] / CHANGELOG_FILENAME)
    return next((p for p in candidates if p.is_file()), None)


@lru_cache(maxsize=4)
def load_releases(path: Path | None) -> tuple[ChangelogRelease, ...]:
    """The parsed releases at `path`, cached for the life of the process; empty if unreadable."""
    if path is None:
        return ()
    try:
        return tuple(parse_changelog(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning(f"Could not read {path} for release notes: {exc}")
        return ()


def get_releases() -> tuple[ChangelogRelease, ...]:
    return load_releases(find_changelog())


# ── selecting ────────────────────────────────────────────────────────────────


def _release_with_commit(releases: Iterable[ChangelogRelease], prefix: str) -> ChangelogRelease | None:
    prefix = prefix.strip().lower()
    if len(prefix) < MIN_COMMIT_PREFIX or not re.fullmatch(r"[0-9a-f]+", prefix):
        return None
    for release in releases:
        for section in release.sections:
            for item in section.items:
                # Either side may be the shorter: the frontend reports 12 chars, a bullet may only
                # carry the 7-char form when its link has no full-sha URL.
                if item.commit and (item.commit.startswith(prefix) or prefix.startswith(item.commit)):
                    return release
    return None


def select_releases(
    releases: Sequence[ChangelogRelease],
    since: str | None = None,
    until: str | None = None,
    since_commit: str | None = None,
) -> list[ChangelogRelease]:
    """Releases newer than the caller's starting point, up to and including `until`, newest first.

    The starting point is the older of `since` (a version) and the release that lists
    `since_commit` (the admin frontend's build sha), so a tab that was behind on either half sees
    everything it missed. When neither can be placed, the latest FALLBACK_RELEASES are returned.
    `until` defaults to the running version. Never more than MAX_RELEASES.
    """
    ordered = sorted(
        ((key, release) for release in releases if (key := version_key(release.version)) is not None),
        key=lambda pair: pair[0],
        reverse=True,
    )
    until_key = version_key(until or APP_VERSION)
    if until_key is not None:
        ordered = [(key, release) for key, release in ordered if key <= until_key]

    lower_bounds = []
    if (since_key := version_key(since or "")) is not None:
        lower_bounds.append(since_key)
    # Searched across every release, not just those up to `until`: the frontend may be built from a
    # commit that the running backend's version predates.
    if since_commit and (match := _release_with_commit(releases, since_commit)):
        if (commit_key := version_key(match.version)) is not None:
            lower_bounds.append(commit_key)

    if not lower_bounds:
        return [release for _, release in ordered[:FALLBACK_RELEASES]]
    lower = min(lower_bounds)
    return [release for key, release in ordered if key > lower][:MAX_RELEASES]
