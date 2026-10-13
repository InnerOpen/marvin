"""Release notes for the admin's update banner, read from the repo's CHANGELOG.md.

python-semantic-release writes the changelog on every release, so it is already the list of what
each version changed; this parses it rather than keeping a second copy. The format it relies on:

    ## v1.0.0-rc.158 (2026-10-03)

    ### Features

    - **admin**: Group the admin nav, ...
      ([`dffdd86`](https://github.com/InnerOpen/marvin/commit/dffdd86...))

The image is built from a code commit before the release job writes that commit's section, so its
changelog always stops short of its own code. CI records the gap at build time
(docker/write-unreleased.sh → UNRELEASED.txt: the commits since the last release tag), and it is
shown as an "Unreleased" entry above the releases.

Release notes are a nicety: a missing or unreadable file yields nothing, never an error. Both files
only change with a new image, so each is parsed once per process.
"""

import re
from collections.abc import Iterable, Sequence
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

import marvin
from marvin.core.root_logger import get_logger
from marvin.core.settings.static import APP_VERSION, BASE_DIR
from marvin.schemas.app import ChangelogItem, ChangelogRelease, ChangelogSection

logger = get_logger(__name__)

CHANGELOG_FILENAME = "CHANGELOG.md"
UNRELEASED_FILENAME = "UNRELEASED.txt"
UNRELEASED_VERSION = "Unreleased"

# Conventional-commit types worth a line in "What's new", titled as semantic-release titles them in
# CHANGELOG.md. The rest (chore, ci, test, style, refactor, build) are developer bookkeeping.
UNRELEASED_SECTIONS = {"feat": "Features", "fix": "Bug Fixes", "perf": "Performance Improvements", "docs": "Documentation"}

# A request never returns more than this many releases, however far back `since` reaches.
MAX_RELEASES = 20
# When the caller's starting point can't be placed (garbage or unknown version, unknown commit),
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
_CONVENTIONAL_RE = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]*)\))?!?:\s*(?P<summary>.+)$")
_BUILT_RE = re.compile(r"^#\s*built:\s*(?P<date>\d{4}-\d{2}-\d{2})")
_UNRELEASED_LINE_RE = re.compile(r"^(?P<sha>[0-9a-f]{7,40})\t(?P<subject>.+)$")
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


# ── unreleased commits ───────────────────────────────────────────────────────


class UnreleasedCommit(NamedTuple):
    sha: str
    type: str | None  # the conventional-commit type, or None for a free-form subject
    scope: str | None
    summary: str


class Unreleased(NamedTuple):
    built: str | None
    commits: tuple[UnreleasedCommit, ...]  # newest first; every commit, so since_commit can place any


def _parse_subject(sha: str, subject: str) -> UnreleasedCommit:
    m = _CONVENTIONAL_RE.match(subject)
    if not m:
        return UnreleasedCommit(sha, None, None, subject)
    summary = m["summary"].strip()
    # semantic-release capitalises the summary in CHANGELOG.md; match it so both entries read alike.
    return UnreleasedCommit(sha, m["type"], (m["scope"] or "").strip() or None, summary[:1].upper() + summary[1:])


def parse_unreleased(text: str) -> Unreleased:
    """The commits docker/write-unreleased.sh recorded: `# key: value` headers, then `sha<TAB>subject` lines."""
    built = None
    commits = []
    for line in text.splitlines():
        if m := _BUILT_RE.match(line):
            built = m["date"]
        elif m := _UNRELEASED_LINE_RE.match(line):
            commits.append(_parse_subject(m["sha"], m["subject"].strip()))
    return Unreleased(built, tuple(commits))


def _commit_url_base(releases: Iterable[ChangelogRelease]) -> str | None:
    """The repo's commit-URL prefix, taken from the changelog's own links rather than configured twice."""
    for release in releases:
        for section in release.sections:
            for item in section.items:
                if item.commit_url and (m := _URL_SHA_RE.search(item.commit_url)):
                    return item.commit_url[: m.start()] + "/commit/"
    return None


def unreleased_release(commits: Iterable[UnreleasedCommit], built: str | None, url_base: str | None) -> ChangelogRelease | None:
    """The commits as a release-shaped "Unreleased" entry, or None when none of them is user-facing."""
    sections: dict[str, ChangelogSection] = {}
    for commit in commits:
        title = UNRELEASED_SECTIONS.get(commit.type or "")
        if title is None:
            continue
        section = sections.setdefault(title, ChangelogSection(title=title))
        section.items.append(
            ChangelogItem(
                scope=commit.scope,
                summary=commit.summary,
                commit=commit.sha,
                commit_url=f"{url_base}{commit.sha}" if url_base else None,
            )
        )
    if not sections:
        return None
    return ChangelogRelease(version=UNRELEASED_VERSION, date=built, sections=list(sections.values()))


# ── loading ──────────────────────────────────────────────────────────────────


def find_install_file(filename: str) -> Path | None:
    """A file shipped beside this install: the image's /app (BASE_DIR) or a source checkout's root."""
    candidates = (BASE_DIR / filename, Path(marvin.__file__).resolve().parents[2] / filename)
    return next((p for p in candidates if p.is_file()), None)


def find_changelog() -> Path | None:
    return find_install_file(CHANGELOG_FILENAME)


def find_unreleased() -> Path | None:
    return find_install_file(UNRELEASED_FILENAME)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning(f"Could not read {path} for release notes: {exc}")
        return None


@lru_cache(maxsize=4)
def load_releases(path: Path | None) -> tuple[ChangelogRelease, ...]:
    """The parsed releases at `path`, cached for the life of the process; empty if unreadable."""
    text = _read(path) if path else None
    return tuple(parse_changelog(text)) if text else ()


@lru_cache(maxsize=4)
def load_unreleased(path: Path | None) -> Unreleased | None:
    """The image's unreleased commits, cached like the changelog; None if absent or unreadable."""
    text = _read(path) if path else None
    return parse_unreleased(text) if text else None


def get_releases() -> tuple[ChangelogRelease, ...]:
    return load_releases(find_changelog())


def get_unreleased() -> Unreleased | None:
    return load_unreleased(find_unreleased())


# ── selecting ────────────────────────────────────────────────────────────────


def _commit_prefix(since_commit: str | None) -> str | None:
    prefix = (since_commit or "").strip().lower()
    return prefix if len(prefix) >= MIN_COMMIT_PREFIX and re.fullmatch(r"[0-9a-f]+", prefix) else None


def _same_commit(sha: str | None, prefix: str) -> bool:
    # Either side may be the shorter: the frontend reports 12 chars, a bullet may only carry the
    # 7-char form when its link has no full-sha URL.
    return bool(sha) and (sha.startswith(prefix) or prefix.startswith(sha))


def _release_with_commit(releases: Iterable[ChangelogRelease], prefix: str) -> ChangelogRelease | None:
    for release in releases:
        for section in release.sections:
            if any(_same_commit(item.commit, prefix) for item in section.items):
                return release
    return None


def select_releases(
    releases: Sequence[ChangelogRelease],
    since: str | None = None,
    until: str | None = None,
    since_commit: str | None = None,
    unreleased: Unreleased | None = None,
) -> list[ChangelogRelease]:
    """What the caller hasn't seen, newest first: an "Unreleased" entry, then releases up to `until`.

    The starting point is `since_commit` (the admin frontend's build sha) when it can be placed —
    among the unreleased commits, or in a release's bullets — and `since` (a version) otherwise.
    The commit wins because it is the finer of the two: an image built from a code commit still
    reports the previous release's version, so the version lags the code by one release. When
    neither can be placed, the latest FALLBACK_RELEASES are returned.

    `until` defaults to the running version; the unreleased commits are newer than it, so they are
    only included when `until` is left to default. Never more than MAX_RELEASES entries.
    """
    ordered = sorted(
        ((key, release) for release in releases if (key := version_key(release.version)) is not None),
        key=lambda pair: pair[0],
        reverse=True,
    )
    until_key = version_key(until or APP_VERSION)
    if until_key is not None:
        ordered = [(key, release) for key, release in ordered if key <= until_key]

    commits = unreleased.commits if unreleased and until is None else ()
    prefix = _commit_prefix(since_commit)
    cut = next((i for i, c in enumerate(commits) if _same_commit(c.sha, prefix)), None) if prefix else None

    if cut is not None:
        # The caller's frontend is past every release; only the unreleased commits after it are new.
        picked: list[ChangelogRelease] = []
        commits = commits[:cut]
    else:
        # Searched across every release, not just those up to `until`: the frontend may be built
        # from a commit that the running backend's version predates.
        match = _release_with_commit(releases, prefix) if prefix else None
        lower = version_key(match.version) if match else version_key(since or "")
        if lower is None:
            picked = [release for _, release in ordered[:FALLBACK_RELEASES]]
        else:
            picked = [release for key, release in ordered if key > lower]

    entry = unreleased_release(commits, unreleased.built if unreleased else None, _commit_url_base(releases))
    return ([entry] if entry else []) + picked[: MAX_RELEASES - (1 if entry else 0)]
