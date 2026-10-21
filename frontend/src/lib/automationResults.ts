// Automation results: the pure logic of Settings › Automation › Results (the status tiles, a row, the badges, the filters, Retry and
// Dismiss, the empty state, and the one line the entry editor and the dashboard show). A result is one hand-off of work to another
// system: in flight until the other side reports back, then succeeded or failed; in flight for more than 24 hours is "No reply"
// (still in flight, flagged by the backend as `noReply`). No DOM and no fetch, so `npm test` covers it (automationResults.test.mjs).
// The API: routes/groups/automation_results_controller.py. The words are Marvin's: a connection's own name is the only place
// a service is named.

import { withReturn } from "./entryBack.ts";
import { excerpt, timeAgo } from "./socialInbox.ts";

export const RESULTS_PATH = "/automation/results";
export const PAGE_SIZE = 50;

export type ResultStatus = "in_flight" | "succeeded" | "failed";
/** What the page filters on: the three statuses and No reply (in flight past 24 hours). */
export type ResultState = ResultStatus | "no_reply";
export type ActionKey = "retry" | "dismiss";

export interface ResultConnection {
  slug: string;
  name: string;
  provider: string;
}

export interface ResultItem {
  id: string;
  status: ResultStatus;
  noReply?: boolean;
  entry?: { id: string; title: string; slug?: string | null } | null;
  connection?: ResultConnection | null;
  workflow?: { id: string; name: string; slug?: string | null } | null;
  action?: { key: string; label: string } | null;
  target?: string | null;
  remoteId?: string | null;
  remoteUrl?: string | null;
  message?: string | null;
  sentAt: string;
  finishedAt?: string | null;
  attempt?: number;
  dismissed?: boolean;
  canRetry?: boolean;
}

export interface ResultsSummary {
  /** A result has been kept: the page and the Automation hub's link to it are drawn. */
  show: boolean;
  /** In flight, not counting those with no reply. */
  inFlight?: number;
  noReply?: number;
  /** Failed and not dismissed. */
  failed?: number;
  succeeded?: number;
  /** Failed plus no reply. */
  attention?: number;
  can?: { act?: boolean };
}

export type Tone = "neutral" | "new" | "good" | "warn" | "bad" | "muted";

export interface Badge {
  label: string;
  tone: Tone;
  title?: string;
}

// ── the hub link ──────────────────────────────────────────────────────────────────────────────────────────────────

/** Whether the Automation hub lists Results: only once a hand-off has been kept (the "features appear when used" rule). */
export function showResults(summary: ResultsSummary | null | undefined): boolean {
  return summary?.show === true;
}

// ── states ────────────────────────────────────────────────────────────────────────────────────────────────────────

/** The state a result is in for the page: No reply for an in-flight one past 24 hours, else its status. */
export function stateOf(item: Pick<ResultItem, "status" | "noReply">): ResultState {
  return item.status === "in_flight" && item.noReply ? "no_reply" : item.status;
}

export const STATES: { value: ResultState; label: string; hint: string; tone: Tone }[] = [
  { value: "in_flight", label: "In flight", hint: "Sent, and the other side hasn't finished", tone: "new" },
  { value: "no_reply", label: "No reply", hint: "Sent more than 24 hours ago and nothing came back", tone: "warn" },
  { value: "failed", label: "Failed", hint: "The hand-off failed, or the other side reported an error", tone: "bad" },
  { value: "succeeded", label: "Succeeded", hint: "The other side finished it", tone: "good" },
];

const BADGES: Record<ResultState, Badge> = {
  in_flight: { label: "In flight", tone: "new", title: "Sent; waiting to hear back" },
  no_reply: { label: "No reply", tone: "warn", title: "Sent more than 24 hours ago and nothing has come back" },
  failed: { label: "Failed", tone: "bad", title: "It failed" },
  succeeded: { label: "Succeeded", tone: "good", title: "Finished" },
};

/** The status badge: In flight, No reply, Failed or Succeeded; Dismissed once a person dealt with a failure or stopped waiting for a reply. */
export function stateBadge(item: Pick<ResultItem, "status" | "noReply" | "dismissed">): Badge {
  if (item.dismissed && item.status === "failed") return { label: "Dismissed", tone: "muted", title: "A failure someone dealt with" };
  if (item.dismissed && item.status === "in_flight") return { label: "Dismissed", tone: "muted", title: "Nobody is waiting for a reply to it any more" };
  return BADGES[stateOf(item)];
}

export interface StateTile {
  value: ResultState;
  label: string;
  count: number;
  tone: Tone;
  active: boolean;
  hint: string;
}

/** The four tiles above the list, each with its count (the whole workspace's, whatever the other filters) and whether it is the active filter. */
export function stateTiles(counts: ResultsSummary | null | undefined, active = ""): StateTile[] {
  const count: Record<ResultState, number> = {
    in_flight: counts?.inFlight ?? 0,
    no_reply: counts?.noReply ?? 0,
    failed: counts?.failed ?? 0,
    succeeded: counts?.succeeded ?? 0,
  };
  return STATES.map((s) => ({ ...s, count: count[s.value], active: s.value === active }));
}

// ── a row ─────────────────────────────────────────────────────────────────────────────────────────────────────────

export interface Row {
  id: string;
  /** What the hand-off was: the entry's title, else the workflow, else the connection and action, else the connection. */
  title: string;
  connection: string;
  provider: string;
  target: string;
  /** The message, else a line that says where it stands. */
  text: string;
  at: string;
  badge: Badge;
  /** Failed or no reply and not dismissed: drawn bold with a dot. */
  unread: boolean;
}

/** The target as shown: a web address (a webhook's, which may carry a token in its path or query) is cut to its host. */
function shownTarget(target: string | null | undefined): string {
  const text = (target ?? "").trim();
  if (!/^https?:\/\//i.test(text)) return text;
  try {
    return new URL(text).host;
  } catch {
    return "";
  }
}

/** What a hand-off was, for its row: the entry's title, else the workflow's name, else "Connection: action", else the connection's name. */
export function resultTitle(item: ResultItem): string {
  const connection = (item.connection?.name ?? "").trim();
  const action = (item.action?.label ?? "").trim();
  return (
    (item.entry?.title ?? "").trim() ||
    (item.workflow?.name ?? "").trim() ||
    (connection && action ? `${connection}: ${action}` : connection) ||
    "Automation result"
  );
}

const WAITING_TEXT = "Waiting to hear back";
const NOT_WAITING_TEXT = "Dismissed: not waiting for a reply";

/** One compact row: the entry, the connection and target, the message (or where it stands), when, and the status badge. */
export function resultRow(item: ResultItem): Row {
  const state = stateOf(item);
  const message = (item.message ?? "").trim();
  return {
    id: item.id,
    title: resultTitle(item),
    connection: item.connection?.name ?? "",
    provider: item.connection?.provider ?? "",
    target: shownTarget(item.target),
    text: message ? excerpt(message, 140) : item.dismissed && item.status === "in_flight" ? NOT_WAITING_TEXT : state === "in_flight" || state === "no_reply" ? WAITING_TEXT : "",
    at: item.finishedAt || item.sentAt,
    badge: stateBadge(item),
    unread: (state === "failed" && !item.dismissed) || state === "no_reply",
  };
}

export interface Line {
  label: string;
  value: string;
}

/** The facts under the open result: the connection, target, workflow, run id, times and attempt. Only what is there. */
export function detailLines(item: ResultItem, now: Date = new Date()): Line[] {
  const lines: Line[] = [];
  if (item.connection) lines.push({ label: "Connection", value: item.connection.name });
  if (shownTarget(item.target)) lines.push({ label: "Target", value: shownTarget(item.target) });
  if (item.workflow) lines.push({ label: "Workflow", value: item.workflow.name });
  if (item.remoteId) lines.push({ label: "Run", value: item.remoteId });
  lines.push({ label: "Sent", value: timeAgo(item.sentAt, now) });
  if (item.finishedAt) lines.push({ label: item.status === "failed" ? "Failed" : "Finished", value: timeAgo(item.finishedAt, now) });
  if ((item.attempt ?? 1) > 1) lines.push({ label: "Attempts", value: String(item.attempt) });
  return lines;
}

/** Where a result stands, in a sentence: "Waiting to hear back since 3 h ago", "Failed 2 d ago", "Finished 5 min ago". */
export function standing(item: ResultItem, now: Date = new Date()): string {
  const state = stateOf(item);
  if (state === "in_flight") return `Waiting to hear back, sent ${timeAgo(item.sentAt, now)}`;
  if (state === "no_reply") return `No reply since it was sent ${timeAgo(item.sentAt, now)}`;
  const when = timeAgo(item.finishedAt || item.sentAt, now);
  return state === "failed" ? `Failed ${when}` : `Finished ${when}`;
}

// ── the open result ───────────────────────────────────────────────────────────────────────────────────────────────

export interface ActionButton {
  key: ActionKey;
  label: string;
  hint: string;
}

/** The buttons for one result, for a caller who may act (the summary's `can.act`, ADMIN and above): Retry on a failure that names the
 *  workflow step and entry that made it (`canRetry`), and Dismiss on a failure or a hand-off still in flight that nobody dismissed yet
 *  (a reply that will never come). None for anyone else. */
export function actionButtons(item: Pick<ResultItem, "status" | "dismissed" | "canRetry">, can: ResultsSummary["can"] | undefined): ActionButton[] {
  if (can?.act !== true) return [];
  const buttons: ActionButton[] = [];
  if (item.status === "failed" && item.canRetry) {
    buttons.push({ key: "retry", label: "Retry", hint: "Runs the workflow's hand-off step again for this entry" });
  }
  if (item.status === "failed" && !item.dismissed) buttons.push({ key: "dismiss", label: "Dismiss", hint: "Dealt with: it stops counting as needing attention" });
  if (item.status === "in_flight" && !item.dismissed) buttons.push({ key: "dismiss", label: "Dismiss", hint: "Not waiting for a reply: it stops counting as in flight or No reply" });
  return buttons;
}

/** The entry editor, with Back returning to this page. */
export function openEntryHref(item: Pick<ResultItem, "entry">, returnTo: string): string | null {
  if (!item.entry?.id) return null;
  return withReturn(`/workspace/entries/${encodeURIComponent(item.entry.id)}`, returnTo);
}

/** What to say when Retry or Dismiss is refused: the backend's reason for a 409, a plain line for a 403, else the message. */
export function actionError(e: unknown): string {
  const status = (e as { status?: number } | null)?.status;
  const message = e instanceof Error ? e.message.trim() : String(e ?? "").trim();
  if (status === 403) return "Retrying and dismissing are for admins.";
  return message || "Something went wrong.";
}

export function errorMessage(e: unknown): string {
  const message = e instanceof Error ? e.message : String(e ?? "");
  return message.trim() || "Something went wrong.";
}

// ── filters ───────────────────────────────────────────────────────────────────────────────────────────────────────

export interface Filters {
  /** One state; "" is every state. */
  status: ResultState | "";
  /** A connection's slug; "" is every connection. */
  connection: string;
  /** One entry's id (the entry editor's line links here); "" is every entry. */
  entry: string;
  q: string;
}

export const NO_FILTERS: Filters = { status: "", connection: "", entry: "", q: "" };

const clean = (v: string | null | undefined) => (v ?? "").trim();
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function parseFilters(search: URLSearchParams): Filters {
  const status = clean(search.get("status"));
  const entry = clean(search.get("entry"));
  return {
    status: STATES.some((s) => s.value === status) ? (status as ResultState) : "",
    connection: clean(search.get("connection")),
    entry: UUID.test(entry) ? entry : "",
    q: clean(search.get("q")).slice(0, 200),
  };
}

/** The page's own query string for a view, so a filtered view can be bookmarked or linked from the dashboard. */
export function filtersToQuery(filters: Filters): string {
  const q = new URLSearchParams();
  if (clean(filters.status)) q.set("status", clean(filters.status));
  if (clean(filters.connection)) q.set("connection", clean(filters.connection));
  if (clean(filters.entry)) q.set("entry", clean(filters.entry));
  if (clean(filters.q)) q.set("q", clean(filters.q));
  const text = q.toString();
  return text ? `?${text}` : "";
}

/** The API's query for a page of results. A failed-only view leaves out dismissed failures, so the list matches the Failed tile's count. */
export function apiQuery(filters: Filters, offset = 0, limit = PAGE_SIZE): string {
  const q = new URLSearchParams();
  if (clean(filters.status)) q.set("status", clean(filters.status));
  if (clean(filters.connection)) q.set("connection", clean(filters.connection));
  if (clean(filters.entry)) q.set("entry_id", clean(filters.entry));
  if (clean(filters.q)) q.set("q", clean(filters.q));
  if (clean(filters.status) === "failed") q.set("include_dismissed", "false");
  q.set("limit", String(limit));
  if (offset > 0) q.set("offset", String(offset));
  return q.toString();
}

export function hasFilters(filters: Filters): boolean {
  return Boolean(clean(filters.status) || clean(filters.connection) || clean(filters.entry) || clean(filters.q));
}

/** The connection filter's options: each connection that has a result. */
export function connectionOptions(connections: ResultConnection[] | null | undefined): { value: string; label: string }[] {
  return (connections ?? []).map((c) => ({ value: c.slug, label: c.name }));
}

// ── the empty state ───────────────────────────────────────────────────────────────────────────────────────────────

export interface Notice {
  title: string;
  body: string;
  link?: { href: string; label: string };
}

/** What the page says when there is nothing to list: a filter that matches nothing, or no hand-off yet (then the Automation hub lists no
 *  Results either, and this page says how one appears). */
export function emptyNotice(summary: ResultsSummary | null | undefined, filtered: boolean): Notice {
  if (filtered) return { title: "Nothing matches these filters", body: "Clear a filter or change the search to see more." };
  if (!showResults(summary)) {
    return {
      title: "Nothing has been handed off yet",
      body: "When a workflow hands work to another system through a connection that follows it up, each hand-off is listed here with whether it came back.",
      link: { href: "/automation/workflows", label: "Open Workflows" },
    };
  }
  return { title: "Nothing here yet", body: "Each hand-off a workflow makes is listed here, newest first." };
}

// ── the entry editor's line and the dashboard's lines ─────────────────────────────────────────────────────────────

export interface EntryLine {
  tone: Tone;
  text: string;
  /** "Open the run", when the other side gave a link. */
  runUrl: string | null;
  /** The Results page filtered to this entry. */
  href: string;
}

/** The small line under an entry's status for its newest hand-off: "Sent to Marketing · in flight", "… · no reply yet", "… · done", or
 *  "Marketing failed: the message". `name` is the connection's own name. */
export function entryLine(item: ResultItem): EntryLine {
  const name = (item.connection?.name ?? "").trim();
  const sent = name ? `Sent to ${name}` : "Sent";
  const state = stateOf(item);
  const message = (item.message ?? "").trim();
  let text: string;
  let tone: Tone;
  if (state === "failed") {
    text = `${name || "The hand-off"} failed${message ? `: ${excerpt(message, 120)}` : ""}${item.dismissed ? " (dismissed)" : ""}`;
    tone = item.dismissed ? "muted" : "bad";
  } else if (state === "no_reply") {
    text = `${sent} · no reply yet`;
    tone = "warn";
  } else if (state === "succeeded") {
    text = `${sent} · done`;
    tone = "good";
  } else {
    text = `${sent} · in flight`;
    tone = "new";
  }
  const entry = item.entry?.id ? `?entry=${encodeURIComponent(item.entry.id)}` : "";
  return { tone, text, runUrl: item.remoteUrl || null, href: `${RESULTS_PATH}${entry}` };
}

export const DASHBOARD_LINKS = {
  failed: { href: `${RESULTS_PATH}?status=failed`, label: "Hand-offs that failed" },
  noReply: { href: `${RESULTS_PATH}?status=no_reply`, label: "Hand-offs with no reply" },
};
