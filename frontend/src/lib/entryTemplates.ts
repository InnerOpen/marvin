// Entry templates on the entry type page (pages/workspace/entry-types/[id].astro): the title preview and the form <-> template
// mapping. The variables and their values follow the server (services/entries/templates.py), which checks a template again
// when it is saved. No imports: `npm test` loads this file with plain `node --test`.

export const TEMPLATE_VARIABLES = ["asset.name", "asset.filename", "n", "date"] as const;
export const TEMPLATE_STATUSES = ["inbox", "draft", "needs_review"] as const;
/** Field types a template gives no value to: the picture goes in an asset field (`assetField`); the rest are picked or hand-written. */
export const SKIPPED_FIELD_TYPES = ["asset", "asset-list", "resource", "resource-list", "json"];
export const ASSET_FIELD_TYPES = ["asset", "asset-list"];

const VARIABLE = /\{([^{}]*)\}/g;

export type TemplateValues = Record<string, string | number | null | undefined>;

export interface SchemaField {
  key?: string;
  label?: string;
  type?: string;
  options?: string[];
}

/** A template as the API answers and takes it (camelCase). */
export interface EntryTemplate {
  slug: string;
  name: string;
  description?: string | null;
  title?: string;
  summary?: string | null;
  entryDescription?: string | null;
  fields?: Record<string, unknown>;
  tags?: string[];
  collections?: string[];
  status?: string;
  assetRole?: string | null;
  assetField?: string | null;
}

/** The editor's values, as the inputs hold them. A field's value is "" when not set; a boolean is "true" / "false" / "". */
export interface TemplateForm {
  slug: string;
  name: string;
  description: string;
  title: string;
  summary: string;
  entryDescription: string;
  status: string;
  assetField: string;
  assetRole: string;
  tags: string;
  collections: string[];
  fields: Record<string, string>;
}

/** The `{…}` variables a text uses, in order (trimmed, as the server reads them). */
export function variablesIn(text: string): string[] {
  return [...text.matchAll(VARIABLE)].map((m) => m[1].trim());
}

/** The variables in `text` that are not template variables (`{}` counts, as ""). */
export function unknownVariables(text: string): string[] {
  const known: readonly string[] = TEMPLATE_VARIABLES;
  return [...new Set(variablesIn(text).filter((v) => !known.includes(v)))];
}

/** `text` with its variables filled from `values`; one with no value (or unknown) is left as written. */
export function renderPattern(text: string, values: TemplateValues): string {
  return text.replace(VARIABLE, (whole, name: string) => {
    const value = values[name.trim()];
    return value == null ? whole : String(value);
  });
}

/** The values for a sample picture: the entry's number 1, today's date. As the server: a picture's name falls back to its filename. */
export function sampleValues(
  asset: { name?: string | null; originalFilename?: string | null; filename?: string | null } | null | undefined,
  today: Date = new Date(),
): TemplateValues {
  const pic = asset ?? { name: "Snowy Owl", filename: "IMG_0042.jpg" };
  const filename = pic.originalFilename || pic.filename || null;
  const pad = (n: number) => String(n).padStart(2, "0");
  return {
    "asset.name": pic.name || filename,
    "asset.filename": filename,
    n: 1,
    date: `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`,
  };
}

/** A slug from a name, as the page makes one for the type itself. */
export function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^\w\s-]/g, "")
    .replace(/[\s_-]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/** The fields a template can give a value to, in schema order. */
export function valueFields(fields: SchemaField[]): SchemaField[] {
  return fields.filter((f) => f.key && !SKIPPED_FIELD_TYPES.includes(f.type ?? "text"));
}

/** The fields the picture can go in. */
export function assetFields(fields: SchemaField[]): SchemaField[] {
  return fields.filter((f) => f.key && ASSET_FIELD_TYPES.includes(f.type ?? ""));
}

/** The editor's values for a template, or for a new one (`null`): the picture in the first asset field, inbox, featured. */
export function formFromTemplate(template: EntryTemplate | null, fields: SchemaField[]): TemplateForm {
  const t = template ?? { slug: "", name: "", assetField: assetFields(fields)[0]?.key ?? null };
  const values: Record<string, string> = {};
  for (const [key, value] of Object.entries(t.fields ?? {})) {
    values[key] = value == null ? "" : typeof value === "object" ? JSON.stringify(value) : String(value);
  }
  return {
    slug: t.slug,
    name: t.name,
    description: t.description ?? "",
    title: t.title ?? "{asset.name}",
    summary: t.summary ?? "",
    entryDescription: t.entryDescription ?? "",
    status: t.status ?? "inbox",
    assetField: t.assetField ?? "",
    assetRole: t.assetRole ?? "featured",
    tags: (t.tags ?? []).join(", "),
    collections: [...(t.collections ?? [])],
    fields: values,
  };
}

function fieldValue(type: string | undefined, raw: string): unknown {
  if (type === "boolean") return raw === "true";
  // A number with a variable in it ("{n}") goes as text; the server fills it and checks it.
  if (type === "number" && !raw.includes("{")) {
    const n = Number(raw);
    return Number.isFinite(n) ? n : raw;
  }
  return raw;
}

/** The template for the editor's values: blanks are left out (the server's defaults), and so is a field with no value.
 *  `stored` is the template being edited: values it holds for fields the editor does not show (an asset or json field, or a
 *  field not in the schema) are kept, so the server can say what is wrong with them rather than the editor dropping them. */
export function templateFromForm(form: TemplateForm, fields: SchemaField[], stored?: EntryTemplate | null): EntryTemplate {
  const shown = new Map(valueFields(fields).map((f) => [f.key as string, f]));
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(stored?.fields ?? {})) {
    if (!shown.has(key)) out[key] = value;
  }
  for (const [key, field] of shown) {
    const raw = (form.fields[key] ?? "").trim();
    const before = stored?.fields?.[key];
    // A list or object value (shown as its JSON) left as it was stays a list, not its text.
    if (before != null && typeof before === "object" && raw === JSON.stringify(before)) out[key] = before;
    else if (raw !== "") out[key] = fieldValue(field.type, raw);
  }
  const text = (s: string) => s.trim() || null;
  const list = (items: string[]) => [...new Set(items.map((s) => s.trim()).filter(Boolean))];
  const template: EntryTemplate = {
    slug: form.slug.trim(),
    name: form.name.trim(),
    description: text(form.description),
    title: form.title.trim() || "{asset.name}",
    summary: text(form.summary),
    entryDescription: text(form.entryDescription),
    fields: out,
    tags: list(form.tags.split(",")),
    collections: list(form.collections),
    status: (TEMPLATE_STATUSES as readonly string[]).includes(form.status) ? form.status : "inbox",
    assetRole: form.assetRole.trim() || "featured",
    assetField: form.assetField.trim() || null,
  };
  return template;
}

/** The list with `template` in place of the one with slug `replacing` (or added at the end when `replacing` is null). */
export function putTemplate(list: EntryTemplate[], template: EntryTemplate, replacing: string | null): EntryTemplate[] {
  const at = replacing == null ? -1 : list.findIndex((t) => t.slug === replacing);
  return at < 0 ? [...list, template] : list.map((t, i) => (i === at ? template : t));
}
