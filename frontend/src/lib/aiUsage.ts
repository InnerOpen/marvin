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

const amount = (value: number) => (Number.isInteger(value) ? value.toLocaleString() : (Math.round(value * 10) / 10).toLocaleString());

/** What an integration call's row shows where an AI run shows tokens and dollars (backend: services/integrations/usage_log.py `metadata_json`).
 * Estimated: "285 characters × 0.5" and "142.5 billed" (units times the model's multiplier). Measured, when the provider read its own meter:
 * the characters, and "300 credits · 98,760 left" (a sound or music is billed by the audio's length, so the credits are the number to trust).
 * null for a row with no such record. */
export function integrationCall(
  meta: { unit?: string; units?: number; multiplier?: number; credits?: number; credits_remaining?: number } | null | undefined,
): { used: string; billed: string } | null {
  if (!meta || typeof meta.units !== "number") return null;
  if (meta.unit !== "characters") return { used: meta.units === 1 ? "1 call" : `${amount(meta.units)} calls`, billed: "—" };
  if (typeof meta.credits === "number") {
    const left = typeof meta.credits_remaining === "number" ? ` · ${amount(meta.credits_remaining)} left` : "";
    return { used: `${amount(meta.units)} characters`, billed: `${amount(meta.credits)} credits${left}` };
  }
  const multiplier = typeof meta.multiplier === "number" && meta.multiplier > 0 ? meta.multiplier : 1;
  const left = typeof meta.credits_remaining === "number" ? ` · ${amount(meta.credits_remaining)} left` : "";
  return { used: `${amount(meta.units)} characters × ${amount(multiplier)}`, billed: `${amount(meta.units * multiplier)} billed${left}` };
}

/** Whether an integration row shows units and a multiplier (ElevenLabs characters) in place of tokens and dollars. A call billed in tokens
 * (OpenAI Images) has tokens, so it shows them and its estimated cost like an AI run. */
export function isUnitBilled(triggerType: string | null | undefined, totalTokens: number | null | undefined): boolean {
  return triggerType === "integration" && !(Number(totalTokens) > 0);
}
