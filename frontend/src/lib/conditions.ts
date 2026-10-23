// Workflow conditions in people's words: the fields a condition can read (grouped, labelled), the values a field takes
// (choices where Marvin knows them), which operators need a value, and a condition read back as a sentence.
// Used by the workflow editor (pages/automation/workflows.astro) for "Only if" and each step's "Only run this step when…",
// and by the workflow cards. Pure: the editor hands in what it knows (the trigger's field catalog, run inputs, earlier steps).

export interface CatalogField {
  field: string;
  label: string;
  description?: string;
}

export interface FieldOption {
  /** The dotted path written into the condition. Ending in "." it is a start: the person types the rest (a type's field…). */
  field: string;
  label: string;
  hint?: string;
}

export interface FieldGroup {
  label: string;
  options: FieldOption[];
}

export interface RunInput {
  name: string;
  label?: string;
  type?: string;
  options?: string[];
}

export interface EarlierStep {
  id: string;
  /** What the step is, e.g. "Wait for approval". */
  label: string;
  keys: string[];
}

export interface Choice {
  value: string;
  label: string;
}

export interface Condition {
  field?: string;
  op?: string;
  value?: unknown;
}

/** Operators that compare nothing: the row shows no value box. */
export const NO_VALUE_OPS: ReadonlySet<string> = new Set(["exists", "changed"]);

export const needsValue = (op: string | undefined): boolean => !NO_VALUE_OPS.has(op ?? "eq");

const OP_PHRASE: Record<string, string> = {
  eq: "is",
  neq: "is not",
  contains: "contains",
  in: "is one of",
  starts_with: "starts with",
  exists: "is set",
  changed: "changed",
  changed_from: "changed from",
  changed_to: "changed to",
  gt: "is more than",
  gte: "is at least",
  lt: "is less than",
  lte: "is at most",
  longer_than: "is longer than",
  shorter_than: "is shorter than",
};

export const ENTRY_STATUSES: Choice[] = [
  { value: "draft", label: "Draft" },
  { value: "published", label: "Published" },
  { value: "needs_review", label: "Needs review" },
  { value: "inbox", label: "Inbox" },
  { value: "archived", label: "Archived" },
];

const DECISIONS: Choice[] = [
  { value: "approved", label: "Approved" },
  { value: "denied", label: "Denied" },
  { value: "expired", label: "Expired" },
  { value: "stale", label: "Stale (the entry changed after it was asked)" },
];

const YES_NO: Choice[] = [
  { value: "true", label: "Yes (true)" },
  { value: "false", label: "No (false)" },
];

/** Step result keys that are yes/no. */
const BOOLEAN_KEYS = new Set(["sent", "ok", "valid", "found", "late", "satisfied", "created", "changed", "replied", "kept", "would_send", "liked", "hidden"]);

const STATUS_FIELDS = new Set(["entry.status", "event.after.status", "event.before.status"]);

/** What a path reads, in words, when no catalog or step names it: "entry.data.price" → "entry › data › price". */
export function humanPath(path: string): string {
  return path.replace(/\.$/, "").split(".").join(" › ");
}

function stepFieldParts(field: string): { id: string; key: string } | null {
  const m = /^steps\.([^.]+)\.output\.(.+)$/.exec(field);
  return m ? { id: m[1], key: m[2] } : null;
}

/**
 * The fields a condition can read, grouped: what the trigger's context offers (the catalog the API sends per trigger type),
 * the run's own inputs (a manual run), and — for a step's condition — the results of the steps before it.
 */
export function fieldGroups(catalog: CatalogField[], extras: { inputs?: RunInput[]; steps?: EarlierStep[] } = {}): FieldGroup[] {
  const groups: FieldGroup[] = [];
  const add = (label: string, options: FieldOption[]) => options.length && groups.push({ label, options });
  const option = (f: CatalogField): FieldOption => ({ field: f.field, label: f.field.endsWith(".") ? `${f.label}…` : f.label, hint: f.description });
  add("The entry", catalog.filter((f) => f.field.startsWith("entry.")).map(option));
  add("What changed", catalog.filter((f) => /^event\.(after|before|changed_fields)/.test(f.field)).map(option));
  add(
    "The event",
    catalog.filter((f) => f.field.startsWith("event.") && !/^event\.(after|before|changed_fields)/.test(f.field)).map(option),
  );
  add(
    "Run inputs",
    (extras.inputs ?? []).map((i) => ({ field: `input.${i.name}`, label: i.label || i.name, hint: "What the person running it gave" })),
  );
  add(
    "Earlier steps",
    (extras.steps ?? []).flatMap((s) => s.keys.map((k) => ({ field: `steps.${s.id}.output.${k}`, label: `${s.label} (${s.id}) → ${k}` }))),
  );
  return groups;
}

/** A field's label, from the groups, else read from its path. */
export function fieldLabel(field: string, groups: FieldGroup[]): string {
  for (const g of groups) {
    const hit = g.options.find((o) => o.field === field);
    if (hit) return hit.label.replace(/…$/, "");
    const start = g.options.find((o) => o.field.endsWith(".") && field.startsWith(o.field));
    if (start) return `${start.label.replace(/…$/, "")} “${field.slice(start.field.length)}”`;
  }
  return humanPath(field);
}

/** The values a field takes, when Marvin knows them; null when it is free text. */
export function valueChoices(field: string, ctx: { entryTypes?: Choice[]; inputs?: RunInput[] } = {}): Choice[] | null {
  if (field === "entry.entry_type") return ctx.entryTypes?.length ? ctx.entryTypes : null;
  if (STATUS_FIELDS.has(field)) return ENTRY_STATUSES;
  const step = stepFieldParts(field);
  if (step?.key === "decision") return DECISIONS;
  if (step && BOOLEAN_KEYS.has(step.key)) return YES_NO;
  const input = /^input\.(.+)$/.exec(field)?.[1];
  const spec = input ? ctx.inputs?.find((i) => i.name === input) : undefined;
  if (spec?.type === "choice" && spec.options?.length) return spec.options.map((o) => ({ value: o, label: o }));
  if (spec?.type === "boolean") return YES_NO;
  return null;
}

function valueText(value: unknown, choices: Choice[] | null, op: string): string {
  const one = (v: string) => {
    const hit = choices?.find((c) => c.value === v);
    return hit ? hit.label.replace(/ \(.*\)$/, "") : `“${v}”`;
  };
  if (value === undefined || value === null || value === "") return "“”";
  if (op === "in") {
    const items = Array.isArray(value) ? value.map(String) : String(value).split(",").map((v) => v.trim()).filter(Boolean);
    return items.map(one).join(", ");
  }
  return one(String(value));
}

/** One condition as words: "Entry type is Recipe", "Wait for approval (ok) → decision is Approved". */
export function describeCondition(c: Condition, groups: FieldGroup[], ctx: { entryTypes?: Choice[]; inputs?: RunInput[] } = {}): string {
  const field = (c.field ?? "").trim();
  if (!field) return "";
  const op = c.op || "eq";
  const label = fieldLabel(field, groups);
  const phrase = OP_PHRASE[op] ?? op;
  if (!needsValue(op)) return `${label} ${phrase}`;
  const suffix = op === "longer_than" || op === "shorter_than" ? " characters" : "";
  return `${label} ${phrase} ${valueText(c.value, valueChoices(field, ctx), op)}${suffix}`;
}

/** Leaf conditions as one sentence ("… and …"); a grouped condition ({any}, {not}) is named, not spelled out. */
export function describeConditions(list: unknown, groups: FieldGroup[], ctx: { entryTypes?: Choice[]; inputs?: RunInput[] } = {}): string {
  const items = list == null ? [] : Array.isArray(list) ? list : [list];
  const parts = items.map((c) =>
    c && typeof c === "object" && "field" in (c as object) ? describeCondition(c as Condition, groups, ctx) : "a grouped condition (see JSON)",
  );
  return parts.filter(Boolean).join(" and ");
}
