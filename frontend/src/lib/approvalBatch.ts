/**
 * Answering several waiting approvals at once ("Approve all 20"): which cards go together (the same workflow, two or more, the
 * same choices), what they are likely to cost in all, and what the batch sends (each card's own choice and changed boxes).
 * Free of the DOM so it runs under `node --test` (approvalBatch.test.mjs).
 */

export interface BatchCard {
  id: string;
  automationSlug?: string | null;
  automationName?: string | null;
  choices?: string[] | null;
  estimate?: { text: string; total?: { amount: number; unit: string } | null } | null;
}

export interface BatchGroup {
  slug: string;
  name: string;
  ids: string[];
  /** The choices every card in it offers (the batch offers one button per choice), or none. */
  choices: string[];
}

const sameChoices = (a: readonly string[], b: readonly string[]): boolean =>
  a.length === b.length && a.every((c, i) => c === b[i]);

/** The cards that can be answered together: by workflow, two or more, offering the same choices. In the order first seen. */
export function batchGroups(cards: readonly BatchCard[]): BatchGroup[] {
  const groups = new Map<string, BatchGroup & { mixed: boolean }>();
  for (const card of cards) {
    const slug = card.automationSlug ?? "";
    if (!slug) continue;
    const choices = card.choices ?? [];
    const group = groups.get(slug);
    if (!group) {
      groups.set(slug, { slug, name: card.automationName ?? slug, ids: [card.id], choices, mixed: false });
      continue;
    }
    group.ids.push(card.id);
    if (!sameChoices(group.choices, choices)) group.mixed = true;
  }
  return [...groups.values()]
    .filter((g) => g.ids.length > 1 && !g.mixed)
    .map(({ slug, name, ids, choices }) => ({ slug, name, ids, choices }));
}

const shown = (amount: number, unit: string): string =>
  unit === "USD" ? `$${amount.toFixed(2)}` : `${Math.round(amount).toLocaleString("en-US")} ${unit}`;

/** What the picked cards are likely to cost in all: a total per unit of the ones with an estimate, and how many have none. */
export function combinedEstimate(cards: readonly BatchCard[]): string | null {
  const totals = new Map<string, number>();
  let unknown = 0;
  let paid = 0;
  for (const card of cards) {
    if (!card.estimate) continue;
    paid += 1;
    const total = card.estimate.total;
    if (total) totals.set(total.unit, (totals.get(total.unit) ?? 0) + total.amount);
    else unknown += 1;
  }
  if (!paid) return null;
  const parts = [...totals].map(([unit, amount]) => shown(amount, unit));
  const sum = parts.length ? `About ${parts.join(" + ")} in all` : "";
  const rest = unknown ? `${unknown} of ${paid} cost unknown` : "";
  return [sum, rest].filter(Boolean).join("; ");
}

/** A batch button's text: "Approve all 20", "Keep all 20", "Deny all 20" (or "Approve these 3" when some are left out). */
export function batchLabel(word: string, picked: number, total: number): string {
  return picked === total ? `${word} all ${total}` : `${word} these ${picked}`;
}

/** What "Approve all" sends for each picked card: its id, the batch's choice, and the boxes it changed. */
export function batchItems(
  ids: readonly string[],
  choice: string | null,
  changed: (id: string) => Record<string, string>,
): { id: string; choice?: string; fields?: Record<string, string> }[] {
  return ids.map((id) => {
    const fields = changed(id);
    return { id, ...(choice ? { choice } : {}), ...(Object.keys(fields).length ? { fields } : {}) };
  });
}
