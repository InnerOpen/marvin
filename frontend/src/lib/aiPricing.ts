/** Admin → AI pricing helpers (backend: services/ai/price_overrides.py). */
export interface AIPriceRow {
  provider: string;
  model: string;
  source: "override" | "provider" | "core" | "self_hosted" | "none" | string;
  inputPer1m: number | null;
  outputPer1m: number | null;
  overridden: boolean;
  runs: number;
  unpricedRuns: number;
}

export interface AIPriceOverride {
  provider: string;
  model: string;
  inputPer1m: number;
  outputPer1m: number;
  updatedAt?: string | null;
}

export const SOURCE_LABELS: Record<string, string> = {
  override: "Your price",
  provider: "Provider's table",
  core: "Marvin's table",
  self_hosted: "Self-hosted (free)",
  none: "No price",
};

export function groupByProvider(rows: AIPriceRow[]): { provider: string; rows: AIPriceRow[] }[] {
  const groups = new Map<string, AIPriceRow[]>();
  for (const row of rows) groups.set(row.provider, [...(groups.get(row.provider) ?? []), row]);
  return [...groups.entries()].map(([provider, list]) => ({ provider, rows: list }));
}

function usd(n: number): string {
  return `$${Number(n.toFixed(4))}`;
}

export function priceText(row: AIPriceRow): string {
  if (row.inputPer1m == null || row.outputPer1m == null) return "—";
  return `${usd(row.inputPer1m)} / ${usd(row.outputPer1m)}`;
}

/** The overrides with this model's price set (added or replaced). */
export function withOverride(list: AIPriceOverride[], provider: string, model: string, input: number, output: number): AIPriceOverride[] {
  const rest = list.filter((o) => !(o.provider === provider && o.model === model));
  return [...rest, { provider, model, inputPer1m: input, outputPer1m: output }];
}

export function withoutOverride(list: AIPriceOverride[], provider: string, model: string): AIPriceOverride[] {
  return list.filter((o) => !(o.provider === provider && o.model === model));
}
