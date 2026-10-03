/**
 * Smart-collection rules ↔ the visual builder (SmartCollectionFields.astro).
 *
 * The rules JSON is the source of truth; the builder is a view over it. Reading the builder
 * overlays its keys onto the last valid JSON, so keys the builder doesn't show (another target's
 * dimensions, anything hand-written) survive a round trip. Shape: services/collections/smart_collections.py.
 */

export type TargetType = "entry" | "asset" | "resource";
export type Rules = Record<string, unknown>;

export interface Condition {
  field: string;
  op: string;
  value?: unknown;
}

export interface BuilderState {
  match: "all" | "any";
  entryTypes: string[];
  statuses: string[];
  publishedWithinDays: number | null;
  where: Condition[];
  assetTypes: string[];
  mimeTypes: string[];
  resourceTypes: string[];
  tags: string[];
  createdWithinDays: number | null;
}

// Both arms name both keys: the frontend's tsconfig isn't strict, so `!parsed.ok` doesn't narrow.
export type ParseResult =
  | { ok: true; rules: Rules; error?: undefined }
  | { ok: false; rules?: undefined; error: string };

/** The publish lifecycle, in order (schemas/platform/entries.py ENTRY_STATUSES). */
export const ENTRY_STATUSES = ["inbox", "processing", "draft", "needs_review", "approved", "published", "archived"];
export const ASSET_TYPES = ["image", "document", "video", "audio", "archive", "svg", "other"];
/** Same ops as a workflow query's `where` (services/entries/query.py WHERE_OPS). */
export const WHERE_OPS = ["eq", "neq", "in", "contains", "exists", "missing", "gt", "gte", "lt", "lte"];
export const VALUELESS_OPS = new Set(["exists", "missing"]);
const NUMERIC_OPS = new Set(["gt", "gte", "lt", "lte"]);

const UNIVERSAL_KEYS = ["tags", "created_within_days", "match"];
/** The keys the builder owns for each target; everything else in the JSON is left alone. */
export const BUILDER_KEYS: Record<TargetType, string[]> = {
  entry: ["entry_types", "statuses", "published_within_days", "where", ...UNIVERSAL_KEYS],
  asset: ["asset_types", "mime_types", ...UNIVERSAL_KEYS],
  resource: ["resource_types", ...UNIVERSAL_KEYS],
};

function strings(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((v) => String(v).trim()).filter(Boolean);
}

function days(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function stateFromRules(rules: Rules | null | undefined): BuilderState {
  const r = rules ?? {};
  const where = Array.isArray(r.where)
    ? r.where
        .filter((c): c is Record<string, unknown> => !!c && typeof c === "object" && !Array.isArray(c))
        .map((c) => ({ field: String(c.field ?? ""), op: String(c.op ?? "eq"), value: c.value }))
    : [];
  return {
    match: r.match === "any" ? "any" : "all",
    entryTypes: strings(r.entry_types),
    statuses: strings(r.statuses),
    publishedWithinDays: days(r.published_within_days),
    where,
    assetTypes: strings(r.asset_types),
    mimeTypes: strings(r.mime_types),
    resourceTypes: strings(r.resource_types),
    tags: strings(r.tags),
    createdWithinDays: days(r.created_within_days),
  };
}

/** A condition's value as the builder's text input shows it. */
export function conditionValueText(value: unknown): string {
  if (value === undefined || value === null) return "";
  if (Array.isArray(value)) return value.join(", ");
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

/** A condition's typed-in text as the rule stores it: a list for `in`, a number for comparisons. */
export function conditionValueFromText(op: string, text: string): unknown {
  if (VALUELESS_OPS.has(op)) return undefined;
  if (op === "in") return splitList(text);
  const trimmed = text.trim();
  if (NUMERIC_OPS.has(op) && trimmed !== "" && Number.isFinite(Number(trimmed))) return Number(trimmed);
  return text;
}

export function splitList(text: string): string[] {
  return text
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

/** Overlay the builder's state for `target` onto `base`, dropping empty dimensions. */
export function rulesFromState(state: BuilderState, target: TargetType, base: Rules = {}): Rules {
  const rules: Rules = { ...base };
  for (const key of BUILDER_KEYS[target]) delete rules[key];
  const set = (key: string, value: unknown) => {
    const empty = value === null || value === undefined || (Array.isArray(value) && value.length === 0);
    if (!empty) rules[key] = value;
  };
  if (target === "entry") {
    set("entry_types", state.entryTypes);
    set("statuses", state.statuses);
    set("published_within_days", state.publishedWithinDays);
    set(
      "where",
      state.where
        .filter((c) => c.field.trim())
        .map((c) => {
          const condition: Condition = { field: c.field.trim(), op: c.op || "eq" };
          if (!VALUELESS_OPS.has(condition.op) && c.value !== undefined) condition.value = c.value;
          return condition;
        }),
    );
  } else if (target === "asset") {
    set("asset_types", state.assetTypes);
    set("mime_types", state.mimeTypes);
  } else {
    set("resource_types", state.resourceTypes);
  }
  set("tags", state.tags);
  set("created_within_days", state.createdWithinDays);
  if (state.match === "any") rules.match = "any";
  return rules;
}

/** Parse the JSON editor's text. Blank is an empty rule set; anything but an object is an error. */
export function parseRules(text: string): ParseResult {
  if (!text.trim()) return { ok: true, rules: {} };
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return { ok: false, error: 'Rules must be a JSON object, e.g. {"statuses": ["published"]}.' };
  }
  return { ok: true, rules: parsed as Rules };
}

/** Pretty JSON for the editor; an empty rule set is blank so the placeholder example shows. */
export function formatRules(rules: Rules): string {
  return Object.keys(rules).length ? JSON.stringify(rules, null, 2) : "";
}
