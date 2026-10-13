/** The AI usage card's note about runs with no price (backend: services/ai/budget.py `unpriced`). */
export interface UnpricedModel {
  provider: string;
  model: string;
  runs: number;
  tokens: number;
}

const SHOWN = 3;

/** One sentence, or null when every run this month had a price. */
export function unpricedNotice(runs: number | undefined, models: UnpricedModel[] | undefined): string | null {
  if (!runs || !models?.length) return null;
  const names = models.slice(0, SHOWN).map((m) => `${m.provider} ${m.model}`);
  const more = models.length > SHOWN ? ` and ${models.length - SHOWN} more` : "";
  const what = runs === 1 ? "1 run" : `${runs.toLocaleString()} runs`;
  return `${what} this month used a model with no price (${names.join(", ")}${more}), so ${runs === 1 ? "its" : "their"} cost isn't in the figure above and the monthly limit can't see it. A platform admin can set a price in Admin → AI Pricing.`;
}
