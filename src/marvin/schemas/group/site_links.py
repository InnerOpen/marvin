"""The Site links setup check (services/site_links.py): what keeps entry links from working in this workspace."""

from marvin.schemas._marvin import _MarvinModel


class SiteLinkFix(_MarvinModel):
    """Where the problem is fixed: a label and an app path."""

    label: str
    path: str


class SiteLinkProblem(_MarvinModel):
    kind: str
    """no_site_address | no_page_pattern | probe_failed"""
    message: str
    fix: SiteLinkFix
    entry_type: str | None = None
    """The entry type's slug, for a problem about one type."""
    url: str | None = None
    """The link that was fetched, for probe_failed."""


class SiteLinksStatus(_MarvinModel):
    """``ok`` when nothing is wrong. A probe answers with the problems it found; it never lists what passed."""

    ok: bool
    problems: list[SiteLinkProblem]
