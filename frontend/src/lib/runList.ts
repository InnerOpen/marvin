/**
 * What a guided setup's run step says around its list: the entries the workflow will act on (POST /api/automations/selection, the
 * workflow's own first `collect`), how many, why some are left out, and what to say when there is nothing to do. Pure, so it runs under
 * `node --test`: the page fetches.
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

/** The start of a long text (its first paragraph, cut at a word within `max`), and whether there is more to unfold. */
export function shortText(text: string, max = 400): { lead: string; more: boolean } {
  const all = text.trim();
  const para = all.split(/\n\s*\n/)[0].trim();
  if (para.length <= max) return { lead: para, more: para.length < all.length };
  const cut = para.slice(0, max);
  return { lead: `${cut.slice(0, Math.max(cut.lastIndexOf(" "), 1)).trimEnd()}…`, more: true };
}

/** What a worker job said (its log), cut short for the step: its first paragraph when it is done, its last when it failed (the reason). */
export function jobLead(log: string, failed: boolean): { lead: string; more: boolean } {
  const parts = log.trim().split(/\n\s*\n/);
  const short = shortText(failed ? parts[parts.length - 1] : log);
  return { lead: short.lead, more: short.more || (failed && parts.length > 1) };
}
