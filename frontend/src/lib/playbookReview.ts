// The review panel of an imported Playbook (components/PlaybookReview.astro): the findings the backend stored on the entry
// (services/playbooks/importer.py: `metadataJson.importReview`) turned into the rows and sentences the panel shows. No DOM and no
// fetch, so `npm test` covers it (playbookReview.test.mjs). The panel is a prompt to read the Playbook, never a security verdict.

export interface ReviewTool { name: string; tool: string | null; available: boolean }
export interface ReviewLink { target: string; kind: "url" | "file"; found: boolean | null; line: number }
export interface ReviewFile { path: string; size: number; script: boolean; referenced: boolean }
export interface ReviewWarning { kind: string; file: string; line: number; excerpt: string }
export interface ImportReview {
  source?: { kind?: string; filename?: string; importedAt?: string; url?: string; repo?: string; path?: string; commit?: string };
  tools: ReviewTool[];
  narrowsTools: boolean;
  links: ReviewLink[];
  files: ReviewFile[];
  scripts: string[];
  skipped: { path: string; reason: string }[];
  warnings: ReviewWarning[];
  warningsOmitted: number;
  extraKeys: string[];
  disclaimer: string;
}

export const REVIEW_DISCLAIMER =
  "This is a keyword and link check, not a guarantee. It can miss risky wording and flag harmless text. Read the Playbook and its files yourself before you publish it.";
export const SCRIPTS_NOTE = "Marvin does not run scripts. These files are kept for reading and for export, and agents can only read them as text.";
export const NOT_A_MARVIN_TOOL = "not a Marvin tool";
export const NO_NARROWING_NOTE = "None of these names a Marvin tool, so this list does not limit what the agent can use while the Playbook runs.";
export const IMPORT_PATH_ACCEPT = ".md,.zip,text/markdown,application/zip";

const WARNING_LABELS: Record<string, string> = {
  secret_word: "Mentions secrets or credentials",
  secret_value: "Contains what looks like a real secret",
  sends_data: "Sends data to another URL or host",
};

const arr = <T>(value: unknown): T[] => (Array.isArray(value) ? (value as T[]) : []);

/** The stored review from an entry's `metadataJson`, or null when the Playbook was not imported (or the value is not a review). */
export function reviewFromMetadata(meta: Record<string, unknown> | null | undefined): ImportReview | null {
  const raw = meta?.importReview as Record<string, unknown> | undefined;
  if (!raw || typeof raw !== "object" || !Array.isArray(raw.tools) || !Array.isArray(raw.files)) return null;
  return {
    source: raw.source as ImportReview["source"],
    tools: arr<ReviewTool>(raw.tools),
    narrowsTools: raw.narrowsTools === true,
    links: arr<ReviewLink>(raw.links),
    files: arr<ReviewFile>(raw.files),
    scripts: arr<string>(raw.scripts),
    skipped: arr<{ path: string; reason: string }>(raw.skipped),
    warnings: arr<ReviewWarning>(raw.warnings),
    warningsOmitted: typeof raw.warningsOmitted === "number" ? raw.warningsOmitted : 0,
    extraKeys: arr<string>(raw.extraKeys),
    disclaimer: typeof raw.disclaimer === "string" && raw.disclaimer ? raw.disclaimer : REVIEW_DISCLAIMER,
  };
}

export function warningLabel(kind: string): string {
  return WARNING_LABELS[kind] ?? "Worth a look";
}

export function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  return bytes < 1048576 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1048576).toFixed(1)} MB`;
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

export interface SourceView {
  /** "owner/repo", plus the folder when the skill is not at the repository's root. */
  label: string;
  /** The first 7 characters of the commit the import is pinned to. */
  commit: string;
  fullCommit: string;
  /** The folder as it was at that commit, so the link shows exactly what was imported. */
  href: string;
}

const COMMIT = /^[0-9a-f]{40}$/;
const REPO = /^[\w.-]+\/[\w.-]+$/;

/** Where a GitHub import came from, or null for an upload (or a value that isn't a pinned GitHub source). */
export function sourceView(source: ImportReview["source"]): SourceView | null {
  if (source?.kind !== "github" || !source.repo || !REPO.test(source.repo) || !source.commit || !COMMIT.test(source.commit)) return null;
  const path = (source.path ?? "").replace(/^\/+|\/+$/g, "");
  return {
    label: path ? `${source.repo}, ${path}` : source.repo,
    commit: source.commit.slice(0, 7),
    fullCommit: source.commit,
    href: `https://github.com/${source.repo}/tree/${source.commit}${path ? `/${path.split("/").map(encodeURIComponent).join("/")}` : ""}`,
  };
}

export interface ReviewView {
  source: SourceView | null;
  /** One sentence for the top of the panel: what needs a look. */
  headline: string;
  tone: "ok" | "attention";
  tools: { name: string; note: string; missing: boolean }[];
  toolsNote: string;
  links: { target: string; kind: "url" | "file"; note: string; broken: boolean; line: number }[];
  files: { path: string; size: string; note: string; script: boolean }[];
  scripts: string[];
  scriptsNote: string;
  skipped: { path: string; reason: string }[];
  warnings: { label: string; where: string; excerpt: string }[];
  warningsMore: string;
  disclaimer: string;
}

export function reviewView(review: ImportReview): ReviewView {
  const missingTools = review.tools.filter((t) => !t.available).length;
  const broken = review.links.filter((l) => l.kind === "file" && l.found === false).length;
  const bits: string[] = [];
  if (review.warnings.length) bits.push(plural(review.warnings.length + review.warningsOmitted, "warning"));
  if (review.scripts.length) bits.push(plural(review.scripts.length, "script file"));
  if (missingTools) bits.push(plural(missingTools, "tool") + " Marvin lacks");
  if (broken) bits.push(plural(broken, "linked file") + " not in the import");
  if (review.skipped.length) bits.push(plural(review.skipped.length, "file") + " left out");
  return {
    source: sourceView(review.source),
    headline: bits.length ? `Look at before publishing: ${bits.join(", ")}.` : "Nothing flagged. Still read it before you publish.",
    tone: bits.length ? "attention" : "ok",
    tools: review.tools.map((t) => ({
      name: t.name,
      missing: !t.available,
      note: t.available ? (t.tool && t.tool !== t.name ? `Marvin's ${t.tool}` : "available") : NOT_A_MARVIN_TOOL,
    })),
    toolsNote: review.tools.length === 0 ? "It asks for no particular tools." : review.narrowsTools ? "" : NO_NARROWING_NOTE,
    links: review.links.map((l) => ({
      target: l.target,
      kind: l.kind,
      line: l.line,
      broken: l.kind === "file" && l.found === false,
      note: l.kind === "url" ? "web link" : l.found ? "file in this Playbook" : "file not in the import",
    })),
    files: review.files.map((f) => ({
      path: f.path,
      size: sizeLabel(f.size),
      script: f.script,
      note: f.script ? "script: unsupported, never run" : f.referenced ? "mentioned in the instructions" : "not mentioned in the instructions",
    })),
    scripts: review.scripts,
    scriptsNote: review.scripts.length ? SCRIPTS_NOTE : "",
    skipped: review.skipped,
    warnings: review.warnings.map((w) => ({ label: warningLabel(w.kind), where: `${w.file}, line ${w.line}`, excerpt: w.excerpt })),
    warningsMore: review.warningsOmitted ? `${plural(review.warningsOmitted, "more warning")} not shown.` : "",
    disclaimer: review.disclaimer,
  };
}

export const GITHUB_IMPORT_PLACEHOLDER = "https://github.com/owner/repo/tree/main/skills/name";

/** The link typed into the GitHub import field, trimmed; null when there is nothing to send. */
export function githubLink(raw: string): string | null {
  const text = raw.trim();
  return text ? text : null;
}

/** The line an import failure shows (a 4xx carries the backend's own reason). */
export function importError(e: unknown): string {
  const body = (e as { body?: unknown; responseBody?: unknown } | null) ?? {};
  const raw = body.responseBody ?? body.body;
  try {
    const parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
    const detail = (parsed as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === "string" && detail) return detail;
  } catch {
    // fall through to the generic message
  }
  return e instanceof Error && e.message ? e.message : "The import failed.";
}
