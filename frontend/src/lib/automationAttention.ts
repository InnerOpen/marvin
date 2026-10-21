// "Automation needs a look": the one summary (GET /api/automations/attention, and the dashboard's attention.automation) behind the
// dashboard line and the count on Settings › Automation. Pure, so `npm test` covers it (automationAttention.test.mjs).

export interface AutomationAttention {
  /** Items needing a look, all kinds together. */
  total: number;
  /** Per kind ("workflows", and later webhooks and scheduled tasks). */
  kinds: Record<string, number>;
  /** The list page, filtered to Needs attention, of the first kind with something flagged; null when nothing is. */
  firstPage: string | null;
}

/** The dashboard's line: null (hidden) when nothing needs a look. `fallback` is where to go if the server named no page. */
export function dashboardLine(
  count: number | null | undefined,
  page: string | null | undefined,
  fallback = "/automation/workflows?status=attention",
): { text: string; href: string } | null {
  const n = count ?? 0;
  if (n <= 0) return null;
  return { text: `Automation needs a look (${n})`, href: page || fallback };
}

/** The count beside the Automation tab / link: "" when nothing needs a look, "99+" for a lot. */
export function countBadge(count: number | null | undefined): string {
  const n = count ?? 0;
  return n <= 0 ? "" : n > 99 ? "99+" : String(n);
}
