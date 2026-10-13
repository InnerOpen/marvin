"""Release notes parsed from CHANGELOG.md, for the admin's "What's new" list on the update banner."""

from marvin.schemas._marvin import _MarvinModel


class ChangelogItem(_MarvinModel):
    """One changelog bullet: `- **scope**: Summary ([`abc1234`](commit url))`."""

    scope: str | None = None
    summary: str
    # The full sha when the bullet links its commit (the link text is only the short form).
    commit: str | None = None
    commit_url: str | None = None


class ChangelogSection(_MarvinModel):
    """A `### Features` / `### Bug Fixes` / ... group within a release."""

    title: str
    items: list[ChangelogItem] = []


class ChangelogRelease(_MarvinModel):
    """A `## v1.0.0-rc.158 (2026-10-03)` release and its sections."""

    version: str
    date: str | None = None
    sections: list[ChangelogSection] = []
