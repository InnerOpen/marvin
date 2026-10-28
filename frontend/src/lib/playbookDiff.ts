// What publishing a proposed Playbook change does to the live text, as the review page shows it: the lines added to and taken
// from the body (with a little unchanged text around each change), and which of the other fields differ. Pure.

export type DiffKind = "same" | "add" | "del" | "gap";
export interface DiffRow {
  kind: DiffKind;
  text: string;
}

const lines = (text: string | null | undefined): string[] => (text ? text.replace(/\r\n/g, "\n").split("\n") : []);

/** Line diff of two bodies, keeping `context` unchanged lines around each change and a `gap` row where the rest was left out. */
export function diffRows(before: string | null | undefined, after: string | null | undefined, context = 2): DiffRow[] {
  const a = lines(before);
  const b = lines(after);
  // Longest common subsequence over lines; playbooks are a few hundred lines at most.
  const lcs: number[][] = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) for (let j = b.length - 1; j >= 0; j--) lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
  const all: DiffRow[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) all.push({ kind: "same", text: a[i++] }), j++;
    else if (lcs[i + 1][j] >= lcs[i][j + 1]) all.push({ kind: "del", text: a[i++] });
    else all.push({ kind: "add", text: b[j++] });
  }
  while (i < a.length) all.push({ kind: "del", text: a[i++] });
  while (j < b.length) all.push({ kind: "add", text: b[j++] });

  const near = new Array<boolean>(all.length).fill(false);
  all.forEach((row, k) => {
    if (row.kind === "same") return;
    for (let n = Math.max(0, k - context); n <= Math.min(all.length - 1, k + context); n++) near[n] = true;
  });
  const out: DiffRow[] = [];
  all.forEach((row, k) => {
    if (near[k]) out.push(row);
    else if (out.length && out[out.length - 1].kind !== "gap") out.push({ kind: "gap", text: "" });
  });
  while (out.length && out[out.length - 1].kind === "gap") out.pop();
  return out;
}

export function diffCounts(rows: DiffRow[]): { added: number; removed: number } {
  return { added: rows.filter((r) => r.kind === "add").length, removed: rows.filter((r) => r.kind === "del").length };
}

const FIELD_LABELS: Record<string, string> = {
  description: "Description",
  license: "License",
  compatibility: "Compatibility",
  allowed_tools: "Allowed tools",
  manual_only: "Manual only",
};

/** The labels of the non-body fields a change would alter (`before`/`after` are the entries' data). */
export function changedFields(before: Record<string, unknown> | null | undefined, after: Record<string, unknown> | null | undefined): string[] {
  const norm = (v: unknown) => (v == null || v === "" || v === false ? "" : String(v));
  return Object.entries(FIELD_LABELS)
    .filter(([key]) => norm(before?.[key]) !== norm(after?.[key]))
    .map(([, label]) => label);
}
