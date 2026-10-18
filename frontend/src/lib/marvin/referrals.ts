// An agent's suggest_agent referrals in the bubble: "Continue with <name> →" makes that agent the bubble's and sends it
// the request the referring agent wrote (which entry, which assets…), so a read-only agent's "this needs a change"
// reaches one that can make it in one click. Pure, so `npm test` covers it (referrals.test.mjs).

/** What the referring agent found, for the receiving one to act on without asking again: ids and slugs, a short note. */
export interface ReferralContext {
  entry?: string | null;
  assetIds?: string[] | null;
  summary?: string | null;
}

export interface BubbleReferral {
  agent: string;
  name?: string | null;
  question?: string | null;
  reason?: string | null;
  tool?: string | null;
  context?: ReferralContext | null;
}

/**
 * The message "Continue with <agent> →" sends: the referring agent's request plus, when it found anything, a
 * plain-text "Handed over" line (entry, asset ids, note, the tool it needs). It is ordinary text in the user's own
 * message, so the receiving agent still looks every id up and checks permissions itself, and the user sees exactly
 * what was passed. Shared by the bubble and the Ask page so the two send the same thing.
 */
export function referralQuestion(r: BubbleReferral): string {
  const question = (r.question ?? "").trim();
  const c = r.context;
  const parts: string[] = [];
  if (c?.entry) parts.push(`entry ${c.entry}`);
  if (c?.assetIds?.length) parts.push(`${c.assetIds.length === 1 ? "asset" : "assets"} ${c.assetIds.join(", ")}`);
  if (c?.summary) parts.push(`note: ${c.summary}`);
  if (!parts.length) return question;
  const needs = r.tool ? ` To do: ${r.tool}.` : "";
  return `${question}\n\nHanded over with: ${parts.join("; ")}.${needs} Check each before acting.`;
}

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

export function referralsHtml(referrals: BubbleReferral[] | null | undefined): string {
  return (referrals ?? [])
    .filter((r) => r?.agent && r.question?.trim())
    .map((r) => {
      const name = esc(r.name || r.agent);
      const reason = r.reason ? ` <span class="mv-ref-reason">${esc(r.reason)}</span>` : "";
      return (
        `<div class="mv-sources mv-referral"><button type="button" class="mv-continue" data-mv-continue-agent="${esc(r.agent)}" ` +
        `data-mv-question="${esc(referralQuestion(r))}">Continue with ${name} →</button>${reason}</div>`
      );
    })
    .join("");
}
