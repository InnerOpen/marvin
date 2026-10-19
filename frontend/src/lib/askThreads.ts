/**
 * The Ask page's threads panel: which rows to show, and which hand-offs nest under which thread.
 *
 * A router run that hands off opens a child thread for the specialist (`parentThreadId` set). The
 * panel lists threads with `children: true` and shows each hand-off under the thread it came from;
 * with "this agent only" on a specialist, the specialist's hand-off threads are its own rows and say
 * where they came from. Kept free of the DOM so it runs under `node --test` (askThreads.test.mjs).
 */

import type { Thread } from "@/lib/api/aiAgents";

export type ThreadGroup = {
  thread: Thread;
  /** The hand-offs this thread made, most recent first. */
  children: Thread[];
};

/** Milliseconds of a thread's last activity. The API sends naive UTC timestamps, so a bare one is read as UTC. */
export function activityOf(t: Thread): number {
  const iso = t.lastMessageAt || t.createdAt;
  if (!iso) return 0;
  const ms = Date.parse(/Z$|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(ms) ? 0 : ms;
}

const byActivity = (a: number, b: number) => b - a;

/**
 * Group a `listThreads({ children: true })` result into rows. Without `agent` the rows are the
 * top-level threads; with it, every thread of that agent (its hand-off threads included). Any other
 * thread nests under its parent row — or, when that parent isn't a row (a deeper hand-off, an orphan),
 * becomes a row itself rather than disappearing. Rows are ordered by their latest activity, children's
 * included.
 */
export function groupThreads(rows: readonly Thread[], agent: string | null = null): ThreadGroup[] {
  const isRow = (t: Thread) => (agent ? t.agentSlug === agent : !t.parentThreadId);
  const groups = new Map<string, ThreadGroup>();
  for (const t of rows) if (isRow(t)) groups.set(t.id, { thread: t, children: [] });
  const strays: Thread[] = [];
  for (const t of rows) {
    if (groups.has(t.id)) continue;
    const parent = t.parentThreadId ? groups.get(t.parentThreadId) : undefined;
    if (parent) parent.children.push(t);
    else strays.push(t);
  }
  for (const t of strays) groups.set(t.id, { thread: t, children: [] });

  const latest = (g: ThreadGroup) => Math.max(activityOf(g.thread), ...g.children.map(activityOf));
  const list = [...groups.values()];
  for (const g of list) g.children.sort((a, b) => byActivity(activityOf(a), activityOf(b)));
  return list.sort((a, b) => byActivity(latest(a), latest(b)));
}

/** "from a hand-off in “<parent>”" for a hand-off thread shown as its own row; null for any other row. */
export function handOffNote(t: Thread): string | null {
  if (!t.parentThreadId) return null;
  return t.parentTitle ? `from a hand-off in “${t.parentTitle}”` : "from a hand-off";
}


/** The shortest search the server runs (services/ai/threads.py SEARCH_MIN_CHARS). */
export const SEARCH_MIN_CHARS = 2;

const escapeHtml = (s: string) =>
  s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string);

/** ``text`` as HTML with every case-insensitive occurrence of ``needle`` wrapped in <mark> — the rest escaped. */
export function highlight(text: string, needle: string): string {
  const n = needle.trim();
  if (!n) return escapeHtml(text);
  const lower = text.toLowerCase();
  const find = n.toLowerCase();
  let out = "";
  let from = 0;
  for (let at = lower.indexOf(find); at >= 0; at = lower.indexOf(find, from)) {
    out += escapeHtml(text.slice(from, at)) + "<mark>" + escapeHtml(text.slice(at, at + n.length)) + "</mark>";
    from = at + n.length;
  }
  return out + escapeHtml(text.slice(from));
}
