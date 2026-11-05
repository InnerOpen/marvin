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

/** One provider's calls this month in the unit it bills in (backend: services/ai/budget.py `integration_tally`). */
export interface IntegrationTally {
  provider: string;
  unit: string;
  calls: number;
  units: number;
  billed: number;
}

const n = (value: number) => Math.round(value).toLocaleString();

/** A line per integration ("elevenlabs: 12 calls, 4,300 characters, 2,900 billed at the models' multipliers"), none when none was called. */
export function integrationLines(tally: IntegrationTally[] | undefined): string[] {
  return (tally ?? []).map((t) => {
    const calls = `${n(t.calls)} ${t.calls === 1 ? "call" : "calls"}`;
    if (t.unit === "calls") return `${t.provider}: ${calls}`;
    const billed = Math.round(t.billed) !== Math.round(t.units) ? `, ${n(t.billed)} billed at the models' multipliers` : "";
    return `${t.provider}: ${calls}, ${n(t.units)} ${t.unit}${billed}`;
  });
}
