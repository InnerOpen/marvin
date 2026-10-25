// The caption check (POST /api/groups/social-inbox/caption-check): what each network that posts will make of a caption — its
// length against the limit, what the feed shows before "… more", and the issues. Pure: the caller fetches; this reads a step's
// arguments and draws the result. Used by the workflow editor under a social.post step (pages/automation/workflows.astro).
// Backend: services/integrations/caption_check.py.

export interface CaptionIssue {
  code: string;
  message: string;
  severity: "error" | "warn" | string;
}

export interface CaptionResult {
  network: string;
  integration?: string;
  name?: string;
  unknown?: boolean;
  unit?: string;
  length?: number;
  max?: number;
  over?: boolean;
  visibleText?: string | null;
  cut?: boolean;
  issues: CaptionIssue[];
}

export interface CaptionRequest {
  text: string;
  link?: string;
  integrations?: string[];
}

const esc = (s: unknown) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string);

/** What to check from a social.post step: its `args` JSON's text and link, and its integration when one is named. None when there
 * is no text yet or the JSON doesn't parse. */
export function captionRequest(argsJson: string, integration = ""): CaptionRequest | null {
  let args: unknown;
  try {
    args = JSON.parse(argsJson || "{}");
  } catch {
    return null;
  }
  if (!args || typeof args !== "object") return null;
  const { text, link } = args as { text?: unknown; link?: unknown };
  if (typeof text !== "string" || !text.trim()) return null;
  const out: CaptionRequest = { text };
  if (typeof link === "string" && link.trim()) out.link = link.trim();
  if (integration.trim() && !integration.includes("${")) out.integrations = [integration.trim()];
  return out;
}

/** Whether the caption is a template that only becomes the real text when the workflow runs. */
export function isTemplate(text: string): boolean {
  return /\$\{[^}]+\}/.test(text);
}

/** One card per network: the count against the limit, the visible window boxed, the issues (errors first). */
export function captionResultsHtml(results: CaptionResult[], text: string): string {
  if (!results.length) return `<p class="hint small">No connected network posts yet, so there's nothing to check against.</p>`;
  const note = isTemplate(text)
    ? `<p class="hint small">Checked as written: the <code>\${…}</code> parts become the real text when the workflow runs.</p>`
    : "";
  return (
    note +
    results
      .map((r) => {
        const title = esc(r.name || r.integration || r.network);
        if (r.unknown) return `<div class="cc-card"><strong>${title}</strong> <span class="hint small">states no limits to check against</span></div>`;
        const count = `<span class="cc-count${r.over ? " over" : ""}">${r.length ?? 0} / ${r.max ?? 0} ${esc(r.unit ?? "characters")}</span>`;
        const visible =
          r.visibleText != null
            ? `<div class="cc-visible" title="What the feed shows">${esc(r.visibleText)}${r.cut ? `<span class="cc-more">… more</span>` : ""}</div>`
            : "";
        const issues = [...r.issues].sort((a, b) => (a.severity === "error" ? 0 : 1) - (b.severity === "error" ? 0 : 1));
        const list = issues.length
          ? `<ul class="cc-issues">${issues.map((i) => `<li class="${i.severity === "error" ? "cc-error" : "cc-warn"}">${esc(i.message)}</li>`).join("")}</ul>`
          : `<p class="hint small cc-ok">Looks fine for ${title}.</p>`;
        return `<div class="cc-card"><div class="cc-head"><strong>${title}</strong>${count}</div>${visible}${list}</div>`;
      })
      .join("")
  );
}
