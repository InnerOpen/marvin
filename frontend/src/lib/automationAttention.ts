// "Automation needs a look": the one summary (GET /api/automations/attention, and the dashboard's attention.automation) behind the
// dashboard line and the count on Settings › Automation. Pure, so `npm test` covers it (automationAttention.test.mjs).

export interface AutomationAttention {
  /** Items needing a look, all kinds together. */
  total: number;
  /** Per kind ("workflows", and later webhooks and scheduled tasks). */
  kinds: Record<string, number>;
  /** The list page of the first kind with something flagged (the server may add `?status=attention`; the links drop it); null when nothing is. */
  firstPage: string | null;
}

/** A link to a list page without the filter another page would pin on it: the page opens the way the person left it, and they
 * change the Status box themselves. (A `?status=attention` link overrides what the page remembered, so clearing it never stuck.) */
export function plainPage(href: string): string {
  return href.split("?")[0];
}

/** The dashboard's line: null (hidden) when nothing needs a look. `fallback` is where to go if the server named no page. */
export function dashboardLine(
  count: number | null | undefined,
  page: string | null | undefined,
  fallback = "/automation/workflows",
): { text: string; href: string } | null {
  const n = count ?? 0;
  if (n <= 0) return null;
  return { text: `Automation needs a look (${n})`, href: plainPage(page || fallback) };
}

/** Words for the approvals waiting for you, on the Approvals card: "" when none. */
export function waitingText(count: number | null | undefined): string {
  const n = count ?? 0;
  return n > 0 ? ` · ${n} waiting for you` : "";
}

/** The count beside the Automation tab / link: "" when nothing needs a look, "99+" for a lot. */
export function countBadge(count: number | null | undefined): string {
  const n = count ?? 0;
  return n <= 0 ? "" : n > 99 ? "99+" : String(n);
}
