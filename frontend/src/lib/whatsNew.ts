/**
 * "What's new" on the update banner: which release notes to show, and in what order.
 *
 * The backend parses CHANGELOG.md (GET /api/app/changes, services/changelog.py) and returns every
 * section semantic-release wrote. Most of those are for developers, so this keeps what a person
 * using the admin would notice. Kept free of the DOM so it runs under `node --test`
 * (whatsNew.test.mjs); AppLayout renders the result.
 */

export type ChangelogItem = {
  scope?: string | null;
  summary: string;
  commit?: string | null;
  commitUrl?: string | null;
};
export type ChangelogSection = { title: string; items: ChangelogItem[] };
export type ChangelogRelease = { version: string; date?: string | null; sections: ChangelogSection[] };
export type RenderedVersion = { frontend: string; backend: string };

export type WhatsNewItem = {
  scope: string | null;
  summary: string;
  shortCommit: string | null;
  commitUrl: string | null;
};
export type WhatsNewSection = { title: string; items: WhatsNewItem[] };
export type WhatsNewRelease = { version: string; date: string | null; sections: WhatsNewSection[] };

export const CHANGES_PATH = "/api/app/changes";

/** The length git and the changelog use for an abbreviated commit. */
export const SHORT_COMMIT_LENGTH = 7;

/** Shown first, in this order; any other user-facing section follows in changelog order. */
const SECTION_ORDER = ["breaking changes", "features", "bug fixes", "performance improvements"];

/** Developer-facing sections: nothing a user of the admin would notice. */
const NOISE_SECTIONS = new Set([
  "chores",
  "continuous integration",
  "build system",
  "testing",
  "code style",
  "refactoring",
]);

/** Shown only for a release that changed nothing else — a docs-only release still says what it did. */
const FALLBACK_SECTION = "documentation";

/** Placeholders version.ts reports when it couldn't tell; they place nothing in the changelog. */
const UNKNOWN_VERSIONS = new Set(["", "unknown", "dev"]);

const sectionKey = (title: string) => title.trim().toLowerCase();

function sectionRank(title: string): number {
  const rank = SECTION_ORDER.indexOf(sectionKey(title));
  return rank === -1 ? SECTION_ORDER.length : rank;
}

/** The release-notes request for a tab rendered at `rendered`: everything after its backend version or frontend commit. */
export function changesUrl(rendered: RenderedVersion | undefined, base = ""): string {
  const params = new URLSearchParams();
  if (rendered && !UNKNOWN_VERSIONS.has(rendered.backend)) params.set("since", rendered.backend);
  if (rendered && !UNKNOWN_VERSIONS.has(rendered.frontend)) params.set("since_commit", rendered.frontend);
  const query = params.toString();
  return `${base}${CHANGES_PATH}${query ? `?${query}` : ""}`;
}

/** A release's heading: "v1.0.0-rc.158" for a version, as-is for the backend's "Unreleased" entry. */
export function releaseLabel(version: string): string {
  return /^\d/.test(version) ? `v${version}` : version;
}

/** Only web links to a commit page are rendered as links; anything else in the file stays text. */
export function safeCommitUrl(url: string | null | undefined): string | null {
  return url && /^https:\/\//i.test(url) ? url : null;
}

export function formatItem(item: ChangelogItem): WhatsNewItem {
  return {
    scope: item.scope?.trim() || null,
    summary: item.summary,
    shortCommit: item.commit ? item.commit.slice(0, SHORT_COMMIT_LENGTH) : null,
    commitUrl: safeCommitUrl(item.commitUrl),
  };
}

/** A release's user-facing sections, most important first; Documentation only when nothing else remains. */
export function visibleSections(release: ChangelogRelease): WhatsNewSection[] {
  const kept = release.sections.filter((s) => s.items.length > 0 && !NOISE_SECTIONS.has(sectionKey(s.title)));
  const substantive = kept.filter((s) => sectionKey(s.title) !== FALLBACK_SECTION);
  const chosen = substantive.length > 0 ? substantive : kept;
  return chosen
    .map((section, index) => ({ section, index }))
    .sort((a, b) => sectionRank(a.section.title) - sectionRank(b.section.title) || a.index - b.index)
    .map(({ section }) => ({ title: section.title, items: section.items.map(formatItem) }));
}

/** The releases worth listing, newest first as the API returns them; a chores-only release is dropped. */
export function prepareReleases(releases: ChangelogRelease[]): WhatsNewRelease[] {
  return releases
    .map((release) => ({ version: release.version, date: release.date ?? null, sections: visibleSections(release) }))
    .filter((release) => release.sections.length > 0);
}
