// The Entries page's structured search (tasks/structured-search-plan.md): condition chips ↔ the page URL ↔ the query
// spec POST /api/platform/entries/query takes (the engine the assistants' find_entries uses, so the page and the AI
// find the same entries). Chips are ANDed; a chip's own values are ORed ("Tag is denim or repair"). Pure, so
// `npm test` covers it (entryQuery.test.mjs).

export interface Cond {
  /** type | status | tag | collection | title | images | created | updated | published | field:<key> */
  dim: string;
  op: string;
  value?: string | string[] | number | boolean | null;
}

export interface FieldDef {
  key: string;
  label: string;
  /** text | number | boolean | select | date */
  kind: string;
  options?: { value: string; label: string }[];
}

export const STATUSES: Record<string, string> = {
  inbox: "Inbox",
  draft: "Draft",
  needs_review: "Needs review",
  approved: "Approved",
  published: "Published",
  archived: "Archived",
  trashed: "In the Trash",
};

/** Dimensions offered for every entry; a chosen type's own fields come on top (fieldsFor). */
export const DIMENSIONS: Record<string, string> = {
  type: "Type",
  status: "Status",
  tag: "Tag",
  collection: "Collection",
  title: "Title",
  images: "Images",
  created: "Created",
  updated: "Updated",
  published: "Published",
};

/** One chip each: a second "Tag is …" joins the first as another value (the engine ORs a tag list). */
const LIST_DIMS = new Set(["type", "status", "tag", "collection"]);
const DATE_DIMS = new Set(["created", "updated", "published"]);

export const OP_LABELS: Record<string, string> = {
  is: "is",
  contains: "contains",
  yes: "has some",
  after: "after",
  before: "before",
  within: "in the last",
  eq: "is",
  neq: "is not",
  in: "is one of",
  gt: ">",
  gte: "≥",
  lt: "<",
  lte: "≤",
  exists: "is set",
  missing: "is empty",
};

const FIELD_OPS: Record<string, string[]> = {
  text: ["contains", "eq", "neq", "exists", "missing"],
  number: ["eq", "neq", "gt", "gte", "lt", "lte", "exists", "missing"],
  date: ["eq", "gt", "gte", "lt", "lte", "exists", "missing"],
  select: ["eq", "neq", "exists", "missing"],
  boolean: ["eq"],
};

/** The operators a dimension (or a field of the given kind) offers. */
export function opsFor(dim: string, field?: FieldDef): string[] {
  if (LIST_DIMS.has(dim)) return ["is"];
  if (dim === "title") return ["contains"];
  if (dim === "images") return ["yes"];
  if (DATE_DIMS.has(dim)) return ["after", "before", "within"];
  return FIELD_OPS[field?.kind ?? "text"] ?? FIELD_OPS.text;
}

/** A field kind the builder can compare, from an entry type field's `type`; null for ones it can't (json, assets…). */
export function fieldKind(type: string | undefined): string | null {
  if (type === "text" || type === "textarea" || type === "markdown") return "text";
  if (type === "number") return "number";
  if (type === "boolean") return "boolean";
  if (type === "select") return "select";
  if (type === "date" || type === "datetime") return "date";
  return null;
}

interface TypeLike {
  slug: string;
  schemaJson?: Record<string, unknown>;
}

/** The fields to offer: the chosen types' fields they all share (all types' fields when none is chosen is too many,
 * so none then). */
export function fieldsFor(types: TypeLike[], chosen: string[]): FieldDef[] {
  const picked = types.filter((t) => chosen.includes(t.slug));
  if (!picked.length) return [];
  const per = picked.map((t) => {
    const fields = ((t.schemaJson?.fields as any[]) ?? []).filter((f) => f?.key && fieldKind(f.type));
    return new Map<string, FieldDef>(
      fields.map((f) => [
        f.key,
        {
          key: f.key,
          label: f.label || f.key,
          kind: fieldKind(f.type)!,
          ...(Array.isArray(f.options) ? { options: f.options.map((o: any) => (typeof o === "string" ? { value: o, label: o } : { value: String(o.value), label: String(o.label ?? o.value) })) } : {}),
        },
      ]),
    );
  });
  return [...per[0].values()].filter((f) => per.every((m) => m.get(f.key)?.kind === f.kind));
}

const list = (v: Cond["value"]): string[] => (Array.isArray(v) ? v.map(String) : v == null || v === "" ? [] : [String(v)]);

/** Add a chip: a list dimension already chipped takes the new values instead of a second chip. */
export function addCond(conds: Cond[], next: Cond): Cond[] {
  if (LIST_DIMS.has(next.dim)) {
    const at = conds.findIndex((c) => c.dim === next.dim);
    if (at >= 0) {
      const merged = [...new Set([...list(conds[at].value), ...list(next.value)])];
      return conds.map((c, i) => (i === at ? { ...c, value: merged } : c));
    }
  }
  return [...conds, next];
}

/** A quick menu's pick (Type / Status / Tag): that one value replaces the chip's values; "" (All …) removes the chip. */
export function setListCond(conds: Cond[], dim: string, value: string | null): Cond[] {
  const at = conds.findIndex((c) => c.dim === dim);
  if (!value) return at >= 0 ? withoutCond(conds, at) : conds;
  const chip: Cond = { dim, op: "is", value: [value] };
  return at >= 0 ? conds.map((c, i) => (i === at ? chip : c)) : [...conds, chip];
}

/** The search box's Enter: its text becomes the one "Title contains" chip. */
export function setTitleCond(conds: Cond[], text: string): Cond[] {
  const rest = conds.filter((c) => c.dim !== "title");
  return text.trim() ? [...rest, { dim: "title", op: "contains", value: text.trim() }] : rest;
}

/** The value a quick menu shows: the chip's, when it has exactly one ("" otherwise). */
export function singleValue(conds: Cond[], dim: string): string {
  const values = list(conds.find((c) => c.dim === dim)?.value);
  return values.length === 1 ? values[0] : "";
}

/** The old links (`?status=inbox,draft` from the sidebar, `?tag=leather`) as chips. */
export function legacyConds(params: URLSearchParams): Cond[] {
  const conds: Cond[] = [];
  const statuses = (params.get("status") ?? "").split(",").map((v) => v.trim()).filter((v) => v in STATUSES);
  if (statuses.length) conds.push({ dim: "status", op: "is", value: statuses });
  const tag = (params.get("tag") ?? "").trim();
  if (tag) conds.push({ dim: "tag", op: "is", value: [tag] });
  return conds;
}

export function withoutCond(conds: Cond[], index: number): Cond[] {
  return conds.filter((_, i) => i !== index);
}

/** The query spec the API takes for these chips. */
export function toSpec(conds: Cond[]): Record<string, unknown> {
  const spec: Record<string, any> = { sort: { by: "updated_at", direction: "desc" } };
  const where: { field: string; op: string; value?: unknown }[] = [];
  for (const c of conds) {
    if (c.dim === "type") spec.entry_types = list(c.value);
    else if (c.dim === "status") spec.status = list(c.value);
    else if (c.dim === "tag") spec.tags = list(c.value);
    else if (c.dim === "collection") spec.collection = list(c.value);
    else if (c.dim === "title") spec.query = String(c.value ?? "");
    else if (c.dim === "images") spec.has_images = true;
    else if (DATE_DIMS.has(c.dim)) {
      if (c.op === "within") spec[`${c.dim}_after`] = `-${Math.max(1, Number(c.value) || 1)}d`;
      else spec[`${c.dim}_${c.op}`] = String(c.value ?? "");
    } else if (c.dim.startsWith("field:")) {
      const field = c.dim.slice("field:".length);
      if (c.op === "exists" || c.op === "missing") where.push({ field, op: c.op });
      else if (c.op === "in") where.push({ field, op: "in", value: list(c.value) });
      else where.push({ field, op: c.op, value: c.value });
    }
  }
  if (where.length) spec.where = where;
  return spec;
}

/** The chips in a URL (`?c=` holds them as JSON); bad input reads as none. */
export function readConds(params: URLSearchParams): Cond[] {
  const raw = params.get("c");
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((c) => c && typeof c.dim === "string" && typeof c.op === "string") : [];
  } catch {
    return [];
  }
}

export function condsHref(conds: Cond[], path = "/workspace/entries"): string {
  return conds.length ? `${path}?c=${encodeURIComponent(JSON.stringify(conds))}` : path;
}

export interface LabelContext {
  types?: Record<string, string>;
  tags?: Record<string, string>;
  collections?: Record<string, string>;
  fields?: Record<string, string>;
}

/** "Type is Bench Note", "Tag is denim or repair", "readTime contains 2 min", "Published in the last 30 days". */
export function condLabel(c: Cond, ctx: LabelContext = {}): string {
  const names = (map: Record<string, string> | undefined) => list(c.value).map((v) => map?.[v] ?? v).join(" or ");
  if (c.dim === "type") return `Type is ${names(ctx.types)}`;
  if (c.dim === "status") return `Status is ${names(STATUSES)}`;
  if (c.dim === "tag") return `Tag is ${names(ctx.tags)}`;
  if (c.dim === "collection") return `Collection is ${names(ctx.collections)}`;
  if (c.dim === "title") return `Title contains “${c.value ?? ""}”`;
  if (c.dim === "images") return "Has images";
  if (DATE_DIMS.has(c.dim)) {
    const what = DIMENSIONS[c.dim];
    return c.op === "within" ? `${what} in the last ${c.value} days` : `${what} ${c.op} ${c.value}`;
  }
  const key = c.dim.slice("field:".length);
  const field = ctx.fields?.[key] ?? key;
  if (c.op === "exists" || c.op === "missing") return `${field} ${OP_LABELS[c.op]}`;
  const value = Array.isArray(c.value) ? c.value.join(" or ") : typeof c.value === "boolean" ? (c.value ? "yes" : "no") : String(c.value ?? "");
  return `${field} ${OP_LABELS[c.op] ?? c.op} ${value}`;
}
