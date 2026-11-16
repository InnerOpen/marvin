/**
 * A job's result as a guided step shows it: the plain text a worker job writes (its log, or a report it leaves on an entry, like a
 * story's Fountain check or chapter plan) read into blocks a page can lay out (a verdict, a strip of counts, findings grouped by kind, a
 * table, lists folded away), so every step shows a job's words the same way. Pure, so it runs under `node --test`: it returns data, never
 * HTML, and `components/JobResult.astro` renders it.
 *
 * It only reads what the text already says. Every line of the text lands in exactly one block, in the order written; a line it does not
 * recognise becomes a text block in its place, shown as written. The text itself stays reachable whatever is recognised.
 */

/** A piece of a line: `code` is what the job quoted between backticks (a line of the script, what to write). */
export interface Seg {
  text: string;
  code?: boolean;
}
export type Tone = "good" | "warn" | "bad" | "plain";

export interface Finding {
  line: number | null;
  text: Seg[];
  /** The quoted bits only, for a row whose words its group says once. */
  quotes: string[];
}
export interface FindingGroup {
  title: string;
  /** The words every row of the group shares, said once (the quotes stand as …); null when the rows differ. */
  why: Seg[] | null;
  rows: Finding[];
  /** `name → handle` pairs, when the group is one such list. */
  pairs: [string, string][] | null;
  /** What follows the pairs, or a row like "and 26 more like these" that belongs to the group above it. */
  after: string[];
  count: number;
}
export interface TableRow {
  n: string;
  name: string;
  cells: string[];
  list: string[];
  note: string | null;
}

export type Block = { src: string } & (
  | { kind: "stamp"; when: string; parts: string[] }
  | { kind: "verdict"; tone: Tone; text: Seg[]; sub: Seg[][] }
  | { kind: "stats"; items: { value: string; label: string }[] }
  | { kind: "note"; text: Seg[] }
  | { kind: "findings"; title: string; count: number | null; said: string; tone: Tone; groups: FindingGroup[] }
  | { kind: "table"; columns: string[]; listColumn: string; rows: TableRow[] }
  | { kind: "pairs"; title: string; pairs: [string, string][] }
  | { kind: "lists"; text: Seg[]; lists: { label: string; items: string[] }[] }
  | { kind: "lack"; text: Seg[] }
  | { kind: "log"; rows: { when: string; what: string; parts: { text: string; bits: string[] | null }[] }[] }
  | { kind: "text"; text: string }
);

export interface JobResult {
  blocks: Block[];
  /** The text as the job wrote it. */
  raw: string;
  /** Whether anything was laid out (else the blocks are the text as written, and the raw text needs no second showing). */
  formatted: boolean;
}

const STAMP = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})? UTC\b/;
const MAX_VERDICT = 300;
const MAX_LIST_ITEMS = 2000;

/** A line cut into plain words and the bits quoted between backticks. */
export function segs(line: string): Seg[] {
  const out: Seg[] = [];
  let at = 0;
  for (const m of line.matchAll(/`([^`\n]+)`/g)) {
    if (m.index > at) out.push({ text: line.slice(at, m.index) });
    out.push({ text: m[1], code: true });
    at = m.index + m[0].length;
  }
  if (at < line.length) out.push({ text: line.slice(at) });
  return out;
}

/** How a verdict reads: stopped or failed, done or clear to go on, skipped, or just said. */
export function toneOf(line: string): Tone {
  if (/^(failed|error)\b|\bwill stop\b|\bcould not\b|\bcannot\b|\bfailed\b/i.test(line)) return "bad";
  if (/^skipped\b/i.test(line)) return "warn";
  if (/^done\b|\bwill go ahead\b|\bcan go on\b|\bnothing to fix\b|^nothing new\b/i.test(line)) return "good";
  return "plain";
}

/** "It reads as 14 chapters, 599 beats and 48 characters." → counts with their names; null unless the line is (after a few words) a
 *  list of at least three counts and nothing else. */
export function statsOf(line: string): { value: string; label: string }[] | null {
  const body = line.trim().replace(/\.$/, "");
  const first = body.search(/(?:about |~)?\d/);
  if (
    first < 0 ||
    body.slice(0, first).trim().split(/\s+/).filter(Boolean).length > 4 ||
    /[:(]/.test(body.slice(0, first))
  )
    return null;
  const items = body.slice(first).split(/, and |, | and /);
  if (items.length < 3) return null;
  const out: { value: string; label: string }[] = [];
  for (const item of items) {
    const m = item.match(/^(about |~)?(\d[\d,.]*) ([a-z][a-z' -]*)$/i);
    if (!m || m[3].split(" ").length > 4) return null;
    out.push({ value: `${m[1] ? "~" : ""}${m[2]}`, label: m[3] });
  }
  return out;
}

/** "a → b; c → d" (or with commas) as pairs; null unless every piece is one name, one arrow, one name. */
function pairsOf(list: string, sep: string): [string, string][] | null {
  const pieces = list.split(sep);
  if (pieces.length < 2) return null;
  const out: [string, string][] = [];
  for (const piece of pieces) {
    const parts = piece.split(" → ");
    if (parts.length !== 2 || !parts[0].trim() || !parts[1].trim() || /[,;]/.test(piece)) return null;
    out.push([parts[0].trim(), parts[1].trim()]);
  }
  return out;
}

// ── Findings: "Worth a look (43): what that means." then indented rows ─────────────────────────────────────────────────

const SECTION = /^([A-Z][^:()\n]{0,60}?)(?: \((\d+)\))?:(?: (.*))?$/;
const MORE_ROW = /^and \d+ more\b/i;

/** The words of a row with its quotes taken out, the same for every row of one kind. */
function template(text: string): string {
  return text.replace(/`[^`\n]+`/g, "…");
}
/** The opening words of a row's kind, to group by: quotes out, numbers as #, the first four words. */
function kindKey(text: string): string {
  return template(text).replace(/^…\s*/, "").replace(/\d+/g, "#").toLowerCase().split(/\s+/).slice(0, 4).join(" ");
}
/** A row's first clause, quotes out: "`A RIVER.` stands alone in capitals, so…" → "stands alone in capitals". */
function clause(text: string): string {
  return template(text)
    .replace(/^…\s*/, "")
    .split(/[,.;:(]| so /)[0]
    .trim();
}
function sentence(text: string): string {
  const t = text.replace(/^(is|are) /, "").trim();
  return t ? t[0].toUpperCase() + t.slice(1) : t;
}
function sharedStart(texts: string[]): string {
  const words = texts.map((t) => t.split(/\s+/));
  const out: string[] = [];
  for (let i = 0; i < words[0].length; i++) {
    if (words.every((w) => w[i] === words[0][i])) out.push(words[0][i]);
    else return `${out.join(" ")} …`;
  }
  return out.join(" ");
}

function findingsOf(lines: string[]): Block | null {
  const head = lines[0].match(SECTION);
  const rows = lines.slice(1);
  if (!head || !rows.length || !rows.every((l) => /^\s+\S/.test(l))) return null;
  const groups: FindingGroup[] = [];
  const byKey = new Map<string, FindingGroup>();
  let last: FindingGroup | null = null;
  for (const raw of rows) {
    const item = raw.replace(/^\s+(?:[-*•] )?/, "");
    if (MORE_ROW.test(item) && last) {
      last.after.push(item);
      last.count += Number(item.match(/\d+/)?.[0] ?? 0); // the rows it did not list are still rows of this kind
      continue;
    }
    const named = !/^line \d+:/.test(item) ? item.match(/^([^:`]{3,80}): (.+?)(?:\. ([^→]+))?$/) : null;
    const pairs = named ? pairsOf(named[2], ", ") : null;
    if (named && pairs) {
      const group: FindingGroup = {
        title: sentence(named[1]),
        why: null,
        rows: [],
        pairs,
        after: named[3] ? [named[3]] : [],
        count: pairs.length,
      };
      groups.push(group);
      last = group;
      continue;
    }
    const m = item.match(/^line (\d+): (.*)$/);
    const text = m ? m[2] : item;
    const finding: Finding = {
      line: m ? Number(m[1]) : null,
      text: segs(text),
      quotes: segs(text).flatMap((s) => (s.code ? [s.text] : [])),
    };
    const key = kindKey(text);
    let group = byKey.get(key);
    if (!group) {
      group = { title: "", why: null, rows: [], pairs: null, after: [], count: 0 };
      byKey.set(key, group);
      groups.push(group);
    }
    group.rows.push(finding);
    group.count += 1;
    last = group;
  }
  for (const g of groups) {
    if (g.pairs) continue;
    const texts = g.rows.map((r) => r.text.map((s) => (s.code ? `\`${s.text}\`` : s.text)).join(""));
    g.title = sentence(sharedStart(texts.map(clause)));
    const same =
      g.rows.length > 1 &&
      texts.every((t) => template(t) === template(texts[0])) &&
      g.rows.every((r) => r.quotes.length > 0);
    if (!same) continue;
    // A quote every row has alike (the same thing to write) is said once with the words; a row keeps only the quotes of its own.
    const alike = g.rows[0].quotes.map((q, i) => g.rows.every((r) => r.quotes[i] === q));
    let n = 0;
    g.why = g.rows[0].text.map((s) => (s.code ? (alike[n++] ? s : { text: "…" }) : s));
    for (const r of g.rows) r.quotes = r.quotes.filter((_, i) => !alike[i]);
  }
  const title = head[1].trim();
  const said = (head[3] ?? "").trim();
  const tone: Tone = /\bstop|\bfix before|\bmust\b/i.test(`${title} ${said}`) ? "bad" : "warn";
  return {
    kind: "findings",
    src: lines.join("\n"),
    title,
    count: head[2] ? Number(head[2]) : null,
    said,
    tone,
    groups,
  };
}

// ── A table of chapters: "  1  Opening    scenes 1–16  ·  ~10 pp  ·  53 beats  ·  53 lines  ·  Brave, Date" ──────────────

const TABLE_ROW = /^\s*(\d+)\s{2,}(\S.*?)\s{2,}(\S.*\s·\s.*)$/;
const UNIT_NAMES: Record<string, string> = { pp: "Pages", page: "Pages", pages: "Pages" };

function tableOf(lines: string[]): Block | null {
  const parsed = lines.map((l) => l.match(TABLE_ROW));
  if (!parsed.every(Boolean)) return null;
  const cellsOf = parsed.map((m) => (m as RegExpMatchArray)[3].split(/\s+·\s+/));
  const width = cellsOf[0].length;
  if (width < 2 || !cellsOf.every((c) => c.length === width)) return null;
  // Each column but the last is a count with its unit ("53 beats", "~10 pp") or a unit and its range ("scenes 1–16"), the same unit down
  // the column; the last may be a list of names instead.
  const columns: string[] = [];
  const numeric = (cell: string) =>
    cell.match(/^(?:~|about )?[\d.,]+(?:[–-][\d.,]+)? ([a-z]+)$/i)?.[1] ??
    cell.match(/^([a-z]+) [\d.,]+(?:[–-][\d.,]+)?$/i)?.[1];
  for (let c = 0; c < width; c++) {
    const units = cellsOf.map((cells) => numeric(cells[c].replace(/ \([^)]*\)$/, "")));
    if (units.every((u) => u && u.toLowerCase() === units[0]?.toLowerCase())) {
      const unit = String(units[0]).toLowerCase();
      columns.push(UNIT_NAMES[unit] ?? unit[0].toUpperCase() + unit.slice(1));
    } else if (c === width - 1) {
      columns.push("");
    } else {
      return null;
    }
  }
  const hasList = columns[width - 1] === "";
  const cut = (cell: string) =>
    cell
      .replace(/^(?:about )/, "~")
      .replace(/^(~?[\d.,]+(?:[–-][\d.,]+)?) [a-z]+$/i, "$1")
      .replace(/^[a-z]+ ([\d.,]+(?:[–-][\d.,]+)?)$/i, "$1");
  const rows: TableRow[] = parsed.map((m, i) => {
    const cells = [...cellsOf[i]];
    let note: string | null = null;
    const lastCell = cells[width - 1];
    const marked = lastCell.match(/^(.*?) \(([^()]+)\)$/);
    if (marked && hasList) {
      cells[width - 1] = marked[1];
      note = marked[2];
    }
    const list = hasList ? cells[width - 1].split(", ").filter(Boolean) : [];
    return {
      n: (m as RegExpMatchArray)[1],
      name: (m as RegExpMatchArray)[2].trim(),
      cells: (hasList ? cells.slice(0, -1) : cells).map(cut),
      list,
      note,
    };
  });
  const listColumn = hasList ? (columns.includes("Lines") ? "Who speaks" : "") : "";
  return { kind: "table", src: lines.join("\n"), columns: hasList ? columns.slice(0, -1) : columns, listColumn, rows };
}

// ── "made 37 scenes (a, b, c…) and 4 sounds to fill in (x, y…)": lists of exactly as many names as the count says ──────

/** Each `N label (a, b, …)` in a line whose list holds exactly N names (so a remark in brackets is never taken for a list), with the
 *  line as it reads without those lists. Null when there is none, or a bracket does not close. */
export function listsOf(line: string): { text: string; lists: { label: string; items: string[] }[] } | null {
  const lists: { label: string; items: string[] }[] = [];
  let text = "";
  let at = 0;
  const open = /(\d+) ([a-z][a-z' -]{0,40}?) \(/gi;
  for (let m = open.exec(line); m; m = open.exec(line)) {
    let depth = 1;
    let end = m.index + m[0].length;
    for (; end < line.length && depth > 0; end++) {
      if (line[end] === "(") depth += 1;
      else if (line[end] === ")") depth -= 1;
    }
    if (depth !== 0) return null;
    const inside = line.slice(m.index + m[0].length, end - 1);
    const items = inside.split(", ").map((s) => s.trim());
    const count = Number(m[1]);
    if (count >= 2 && count <= MAX_LIST_ITEMS && items.length === count && items.every(Boolean)) {
      lists.push({ label: `${m[1]} ${m[2]}`, items });
      text += line.slice(at, m.index + m[0].length - 2);
      at = end;
    }
    open.lastIndex = end;
  }
  if (!lists.length) return null;
  return { text: (text + line.slice(at)).replace(/\s+/g, " ").trim(), lists };
}

// ── A sheet log: "2026-11-16 18:12 UTC · add · from the Fountain · +599 beats, +768 lines, +14 chapters" ──────────────

function logRowOf(line: string) {
  const parts = line.split(" · ");
  if (parts.length < 3 || !STAMP.test(parts[0])) return null;
  return {
    when: parts[0],
    what: parts[1],
    parts: parts.slice(2).map((p) => ({ text: p, bits: /^[+-]?\d/.test(p) ? p.split(", ") : null })),
  };
}

// ── The whole text ─────────────────────────────────────────────────────────────────────────────────────────────────

function paragraphs(text: string): string[][] {
  const out: string[][] = [];
  let now: string[] = [];
  for (const line of text.split("\n")) {
    if (line.trim()) now.push(line.replace(/\s+$/, ""));
    else if (now.length) {
      out.push(now);
      now = [];
    }
  }
  if (now.length) out.push(now);
  return out;
}

function verdictOk(line: string): boolean {
  return line.length <= MAX_VERDICT && !/^\s/.test(line) && !/^[#>|*-]/.test(line);
}

/** One paragraph read into blocks, or null when nothing in it is recognised. `lead` is true for the text's first paragraph (after a stamp). */
function blocksOf(lines: string[], lead: boolean): Block[] | null {
  const src = lines.join("\n");
  if (lines.every((l) => logRowOf(l)))
    return [{ kind: "log", src, rows: lines.map((l) => logRowOf(l) as NonNullable<ReturnType<typeof logRowOf>>) }];
  const findings = findingsOf(lines);
  if (findings) return [findings];
  const table = tableOf(lines);
  if (table) return [table];
  if (lines.length === 1) {
    const line = lines[0];
    const stats = statsOf(line);
    if (stats) return [{ kind: "stats", src, items: stats }];
    const lack = line.match(/^[^:]{0,40}\bstill lacks?: (.+)$/);
    if (lack) return [{ kind: "lack", src, text: segs(lack[1]) }];
    const pairs = line.match(/^([A-Z][\w ]{0,30}): (.+ → .+)$/);
    const said = pairs ? pairsOf(pairs[2], "; ") : null;
    if (pairs && said) return [{ kind: "pairs", src, title: pairs[1], pairs: said }];
    const lists = listsOf(line);
    if (lists) return [{ kind: "lists", src, text: segs(lists.text), lists: lists.lists }];
    if (/^Checked .*\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(line) && line.length < 80)
      return [{ kind: "note", src, text: segs(line) }];
  }
  if (!lead || !verdictOk(lines[0])) return null;
  // The opening paragraph: its first line says how it went, the lines under it say more, a line of counts is a strip of counts, and
  // what follows that is a note.
  const verdict: Block = { kind: "verdict", src: lines[0], tone: toneOf(lines[0]), text: segs(lines[0]), sub: [] };
  const out: Block[] = [verdict];
  for (const line of lines.slice(1)) {
    const stats = statsOf(line);
    if (stats) out.push({ kind: "stats", src: line, items: stats });
    else if (out.length === 1 && verdict.kind === "verdict") {
      verdict.sub.push(segs(line));
      verdict.src += `\n${line}`;
    } else out.push({ kind: "note", src: line, text: segs(line) });
  }
  return out;
}

/** A job's text read into blocks. A failed job's reason is its last paragraph (what it said last), shown as the verdict. */
export function jobResult(text: string, opts: { failed?: boolean } = {}): JobResult {
  const raw = String(text ?? "")
    .replace(/\r\n?/g, "\n")
    .trim();
  const paras = paragraphs(raw);
  if (!paras.length) return { blocks: [], raw, formatted: false };
  if (opts.failed) {
    const last = paras[paras.length - 1];
    return {
      blocks: [
        { kind: "verdict", src: last.join("\n"), tone: "bad", text: segs(last[0]), sub: last.slice(1).map(segs) },
      ],
      raw,
      formatted: paras.length > 1 || last.length > 1,
    };
  }
  const blocks: Block[] = [];
  let lead = true;
  paras.forEach((lines, i) => {
    if (i === 0 && paras.length > 1 && lines.length === 1 && STAMP.test(lines[0]) && lines[0].includes(" · ")) {
      const [when, ...parts] = lines[0].split(" · ");
      blocks.push({ kind: "stamp", src: lines[0], when, parts });
      return;
    }
    const found = blocksOf(lines, lead);
    lead = false;
    if (found) {
      blocks.push(...found);
      return;
    }
    const prev = blocks[blocks.length - 1];
    if (prev?.kind === "text") {
      prev.text += `\n\n${lines.join("\n")}`;
      prev.src += `\n${lines.join("\n")}`;
    } else blocks.push({ kind: "text", src: lines.join("\n"), text: lines.join("\n") });
  });
  // A lone sentence said plainly is the text as written: nothing was laid out, so it needs no second showing.
  const lone =
    blocks.length === 1 && blocks[0].kind === "verdict" && blocks[0].tone === "plain" && !blocks[0].sub.length;
  return { blocks, raw, formatted: !lone && blocks.some((b) => b.kind !== "text") };
}
