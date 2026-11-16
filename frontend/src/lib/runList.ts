/**
 * What a guided setup's run step says around its list: the entries the workflow will act on (POST /api/automations/selection, the
 * workflow's own first `collect`), how many, why some are left out, and what to say when there is nothing to do. A workflow that starts
 * by previewing a template lists what it would make instead (`previewCards`). Pure, so it runs under `node --test`: the page fetches.
 */

const COUNT = /\s*\$\{count\}\s*/g;

/** The step's button with `${count}` filled in; with no count known the token goes, with brackets or a colon it leaves empty, and the
 *  words close up ("Make these sounds (${count})" reads "Make these sounds"). */
export function runButton(template: string | undefined, count: number | null): string {
  if (!template) return "Run";
  if (count != null) return template.replace(/\$\{count\}/g, String(count));
  return template.replace(COUNT, " ").replace(/\(\s*\)|\[\s*\]/g, " ").replace(/\s*:\s*$/, "").replace(/\s+/g, " ").trim();
}

/** The line above the list; null when there is nothing in it. */
export function listLine(sel: { count: number; total: number; limit?: number | null }): string | null {
  if (sel.count < 1) return null;
  if (sel.total > sel.count) return `It works on the next ${sel.count} of ${sel.total} (${sel.limit ?? sel.count} at a time):`;
  return sel.count === 1 ? "It works on this one:" : `It works on these ${sel.count}:`;
}

/** "Not included: 1 music, 3 already have a file.", from the package's reasons and the server's counts; null when none counts. */
export function leftOutLine(reasons: { label: string }[], counts: number[]): string | null {
  const said = reasons.flatMap((r, n) => ((counts[n] ?? 0) > 0 ? [`${counts[n]} ${r.label}`] : []));
  return said.length ? `Not included: ${said.join(", ")}.` : null;
}

/** What an empty list says: the package's words, or plainly (pointing on only when there is a next step). */
export function nothingLine(packageWords: string | undefined, hasNext = true): string {
  return packageWords?.trim() || `There is nothing for this step to do right now.${hasNext ? " Go on to the next step." : ""}`;
}

/** Rows in the order of `ids` (an entry query keeps its own order); an id with no row (gone, or not the reader's to see) is skipped. */
export function inOrder<T extends { id: string }>(rows: T[], ids: string[]): T[] {
  const byId = new Map(rows.map((r) => [r.id, r]));
  return ids.flatMap((id) => byId.get(id) ?? []);
}

// ── A workflow that starts by previewing a template: what it would make ──────────────────────────────────────────────

/** A template's preview, as the selection answers it (lib/api/workflowRuns.ts: TemplatePreview), loosely typed so this stays pure. */
interface PreviewRow {
  action: string;
  entryId?: string | null;
  title: string;
  asset?: { id: string; url?: string | null } | null;
  treated?: { id: string; url?: string | null } | null;
  changes?: { fields?: Record<string, unknown> } | null;
  note?: string | null;
  error?: string | null;
}
interface Preview {
  create: number;
  fill: number;
  skip: number;
  errors: number;
  rows: PreviewRow[];
}
/** A field of the entry type, as much as a card needs to say a value in words. */
interface FieldLike {
  key?: string;
  label?: string;
  type?: string;
  options?: unknown[];
}

/** The line above a template's cards: what pressing the button will do. Null when it would do nothing. */
export function previewLine(preview: Preview): string | null {
  const { create, fill, skip } = preview;
  if (create + fill < 1) return null;
  if (!fill && !skip) return create === 1 ? "It will make this one:" : `It will make these ${create}:`;
  const does = [...(create ? [`make ${create}`] : []), ...(fill ? [`fill in ${fill} that ${fill === 1 ? "is" : "are"} already there`] : [])].join(" and ");
  return `It will ${does}${skip ? `, and leave ${skip} as ${skip === 1 ? "it is" : "they are"}` : ""}:`;
}

/** What stops a template's run: a row with an error means nothing is made, so the page says so and keeps the button off. */
export function previewProblem(preview: Preview): string | null {
  if (preview.errors < 1) return null;
  const which = preview.errors === 1 ? "One of them has a problem, shown on its card." : `${preview.errors} of them have a problem, shown on their cards.`;
  return `${which} Nothing is made until that is fixed.`;
}

const PREVIEW_PILLS: Record<string, string> = { create: "New", fill: "Already there: only what is empty is filled", skip: "Left out" };
const MAX_PREVIEW_VALUES = 200;

/** A value a template sets, in words, under its field's name ("Price: $85"): a switch that is on is just its name, a choice its
 *  option's label, text as written. A field's label loses its explanation in brackets, as a column heading does. */
function valueWords(field: FieldLike | undefined, key: string, value: unknown): string {
  const name = (field?.label ?? key).replace(/\s*\(.*\)\s*$/, "") || key;
  if (typeof value === "boolean") return value ? name : "";
  const option = (field?.options ?? []).find((o) => o && typeof o === "object" && (o as { value?: unknown }).value === value) as { label?: string } | undefined;
  const scalar = (v: unknown) => typeof v === "string" || typeof v === "number";
  const said = Array.isArray(value) ? value.filter(scalar).join(", ") : scalar(value) ? String(option?.label ?? value) : "";
  const words = said.replace(/\s+/g, " ").trim();
  return words ? `${name}: ${words}` : "";
}

/** A template's rows as cards: the picture, the title the entry will have, the values it will get (never the picture's own id, which
 *  is how its field holds it), and whether it is new. A row that is left alone, or stopped, says why instead. */
export function previewCards(preview: Preview, fields: FieldLike[] = []): { href: string; title: string; picture: string | null; subtitle: string; pills: string[] }[] {
  return preview.rows.map((row) => {
    const pictures = new Set([row.asset?.id, row.treated?.id].filter(Boolean));
    const isPicture = (value: unknown) => (Array.isArray(value) ? value.some((v) => pictures.has(v)) : pictures.has(value as string));
    const values = Object.entries(row.changes?.fields ?? {})
      .filter(([, value]) => !isPicture(value))
      .map(([key, value]) => valueWords(fields.find((f) => f.key === key), key, value))
      .filter(Boolean)
      .join(" · ");
    const cut = values.length > MAX_PREVIEW_VALUES ? `${values.slice(0, MAX_PREVIEW_VALUES - 1).trimEnd()}…` : values;
    const said = row.error ?? (row.action === "skip" ? (row.note ?? "") : [cut, row.note].filter(Boolean).join(" · "));
    return {
      href: row.entryId ? `/workspace/entries/${row.entryId}` : row.asset ? `/workspace/assets/${row.asset.id}` : "#",
      title: row.title,
      picture: row.treated?.url ?? row.asset?.url ?? null,
      subtitle: said,
      // Left alone because its entry is there and complete (also what every card says once the run has made them), or left out (no entry).
      pills: [row.error ? "Problem" : row.action === "skip" && row.entryId ? "Already there" : (PREVIEW_PILLS[row.action] ?? row.action)],
    };
  });
}
