// "Apply a template" to the entries selected on the Entries page: which template can be offered for a selection, and what
// the preview (POST /entries/apply-template, which changes nothing) says in words: for each entry what would be filled
// and what is left as it is. Pure, so `npm test` covers it (applyTemplate.test.mjs).

import type { TemplatePreview, TemplatePreviewRow } from "./api/workflowRuns";
import type { EntryTemplate, SchemaField } from "./entryTemplates";

/** The most entries one call fills (the API's limit). */
export const MAX_ENTRIES = 200;

export interface PickedEntry {
  id: string;
  entryTypeId: string;
}

export interface TemplateType {
  id: string;
  slug: string;
  name: string;
  fields: SchemaField[];
  templates: EntryTemplate[];
}

export type Selection =
  | { kind: "none" }
  | { kind: "too-many"; count: number }
  /** Entries of more than one type: a template belongs to one. `names` are the types', most entries first. */
  | { kind: "mixed"; names: string[] }
  | { kind: "no-templates"; type: TemplateType }
  | { kind: "ready"; type: TemplateType };

const record = (v: unknown): Record<string, unknown> => (v && typeof v === "object" ? (v as Record<string, unknown>) : {});

/** An entry type as the page needs it, from what the API lists (`schemaJson.fields`, `templatesJson`). */
export function templateType(raw: { id?: string; slug?: string; name?: string; schemaJson?: unknown; templatesJson?: unknown }): TemplateType {
  const fields = record(raw.schemaJson).fields;
  return {
    id: String(raw.id ?? ""),
    slug: String(raw.slug ?? ""),
    name: String(raw.name || raw.slug || ""),
    fields: Array.isArray(fields) ? (fields as SchemaField[]) : [],
    templates: Array.isArray(raw.templatesJson) ? (raw.templatesJson as EntryTemplate[]).filter((t) => t && typeof t.slug === "string" && t.slug) : [],
  };
}

/** What can be done with the entries picked: a template is offered only when they share one type that has templates. */
export function selectionOf(picked: readonly PickedEntry[], types: readonly TemplateType[]): Selection {
  if (!picked.length) return { kind: "none" };
  if (picked.length > MAX_ENTRIES) return { kind: "too-many", count: picked.length };
  const counts = new Map<string, number>();
  for (const p of picked) counts.set(p.entryTypeId, (counts.get(p.entryTypeId) ?? 0) + 1);
  const byId = new Map(types.map((t) => [t.id, t]));
  if (counts.size > 1) {
    const names = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([id]) => byId.get(id)?.name ?? "another type");
    return { kind: "mixed", names };
  }
  const type = byId.get(picked[0].entryTypeId);
  if (!type?.templates.length) return { kind: "no-templates", type: type ?? { id: picked[0].entryTypeId, slug: "", name: "This type", fields: [], templates: [] } };
  return { kind: "ready", type };
}

const label = (fields: readonly SchemaField[], key: string): string => fields.find((f) => f.key === key)?.label || key;
const has = (v: unknown): boolean => v !== null && v !== undefined && v !== "" && !(Array.isArray(v) && v.length === 0);

/** Everything a template gives a value to, by name: what a row can fill. The title only with `replace` (it is never empty). */
export function templateSets(template: EntryTemplate, fields: readonly SchemaField[], replace: boolean): string[] {
  const out: string[] = [];
  if (replace && has(template.title)) out.push("Title");
  if (has(template.summary)) out.push("Summary");
  if (has(template.entryDescription)) out.push("Description");
  for (const key of Object.keys(template.fields ?? {})) out.push(label(fields, key));
  if (template.assetField && !out.includes(label(fields, template.assetField))) out.push(label(fields, template.assetField));
  return out;
}

export interface RowLine {
  title: string;
  /** `fill`: it would change; `skip`: left as it is (`note` says why); `problem`: it stops the whole batch (`note`). */
  state: "fill" | "skip" | "problem";
  /** The values that would be set, by name. */
  fills: string[];
  /** What the template sets that this entry keeps as it is (it has a value already, or the same one). The picture field
   *  is among them only when the entry has a picture. */
  kept: string[];
  /** What is added beside the values: tags, collections, the picture. */
  adds: string[];
  note: string | null;
}

/** One preview row in words. */
export function rowLine(row: TemplatePreviewRow, template: EntryTemplate, fields: readonly SchemaField[], replace: boolean): RowLine {
  const note = row.error || row.note || null;
  if (row.action === "skip") return { title: row.title, state: "skip", fills: [], kept: [], adds: [], note };
  const changes = record(row.changes);
  const fills: string[] = [];
  if ("title" in changes) fills.push("Title");
  if ("summary" in changes) fills.push("Summary");
  if ("description" in changes) fills.push("Description");
  for (const key of Object.keys(record(changes.fields))) fills.push(label(fields, key));
  const adds: string[] = [];
  if (row.tags?.length) adds.push(`${row.tags.length === 1 ? "tag" : "tags"} ${row.tags.join(", ")}`);
  if (row.collections?.length) adds.push(`${row.collections.length === 1 ? "collection" : "collections"} ${row.collections.join(", ")}`);
  if (row.attach) adds.push("its picture, attached");
  // An entry with no picture has nothing in the template's picture field to keep: it is not named among the kept.
  const pictureField = template.assetField ? label(fields, template.assetField) : null;
  return {
    title: row.title,
    state: row.error ? "problem" : "fill",
    fills,
    kept: templateSets(template, fields, replace).filter((name) => !fills.includes(name) && !(name === pictureField && !row.asset)),
    adds,
    note,
  };
}

const entries = (n: number): string => `${n} ${n === 1 ? "entry" : "entries"}`;

/** The line over the preview's rows: how many would change, how many are left, and what stops it. */
export function previewLine(preview: Pick<TemplatePreview, "total" | "fill" | "skip" | "errors">, replace: boolean): string {
  if (!preview.fill) return `Nothing to do: ${preview.total === 1 ? "the entry is" : `all ${preview.total} entries are`} left as ${preview.total === 1 ? "it is" : "they are"}.`;
  const parts = [`${preview.fill} of ${entries(preview.total)} would be ${replace ? "changed" : "filled"}`];
  if (preview.skip) parts.push(`${preview.skip} left as ${preview.skip === 1 ? "it is" : "they are"}`);
  let text = `${parts.join(", ")}.`;
  if (preview.errors) text += ` ${preview.errors} ${preview.errors === 1 ? "has" : "have"} a problem: nothing is changed until it is fixed.`;
  return text;
}

/** The confirm button: what it does, and to how many. */
export function confirmLabel(preview: Pick<TemplatePreview, "fill"> | null, replace: boolean): string {
  if (!preview?.fill) return replace ? "Replace values" : "Fill empty fields";
  return replace ? `Replace values in ${entries(preview.fill)}` : `Fill empty fields in ${entries(preview.fill)}`;
}

/** Whether the preview can be confirmed: something to do, and no row with a problem. */
export function canConfirm(preview: Pick<TemplatePreview, "todo" | "errors"> | null): boolean {
  return !!preview && preview.todo > 0 && preview.errors === 0;
}

/** What happened, once it is done. */
export function doneLine(result: { updated?: number; skip?: number; treatmentJob?: string | null }, replace: boolean): string {
  const updated = result.updated ?? 0;
  let text = `${replace ? "Changed" : "Filled"} ${entries(updated)}`;
  if (result.skip) text += `, left ${result.skip} as ${result.skip === 1 ? "it is" : "they are"}`;
  text += ".";
  if (result.treatmentJob) text += " Their pictures are being treated now and take their place when ready.";
  return text;
}
