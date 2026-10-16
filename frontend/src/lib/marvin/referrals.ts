// An agent's suggest_agent referrals in the bubble: "Continue with <name> →" makes that agent the bubble's and sends it
// the request the referring agent wrote (which entry, which assets…), so a read-only agent's "this needs a change"
// reaches one that can make it in one click. Pure, so `npm test` covers it (referrals.test.mjs).

export interface BubbleReferral {
  agent: string;
  name?: string | null;
  question?: string | null;
  reason?: string | null;
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
        `data-mv-question="${esc(r.question!.trim())}">Continue with ${name} →</button>${reason}</div>`
      );
    })
    .join("");
}
