// Words for the Alerts & health page (settings/integration-health.astro): durations, relative times,
// how an alert resolved, where a retry stands, and a handled failure as one line. Pure, so it's tested
// with plain `node --test` (see integrationHealth.test.mjs).

/** "45s", "7 min", "5h 12m", "3d 4h". */
export function duration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  if (h < 24) return m % 60 ? `${h}h ${m % 60}m` : `${h}h`;
  const d = Math.floor(h / 24);
  return h % 24 ? `${d}d ${h % 24}h` : `${d}d`;
}

/** "3 min ago", "in 2h", "just now" — relative to `now`. Empty for no time. */
export function relative(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const diff = (t - now.getTime()) / 1000;
  if (Math.abs(diff) < 30) return "just now";
  return diff < 0 ? `${duration(-diff)} ago` : `in ${duration(diff)}`;
}

/** How a resolved alert ended. */
export function resolutionLabel(resolution: string | null | undefined, by?: string | null): string {
  if (resolution === "manual") return by ? `Resolved by ${by}` : "Resolved by an admin";
  if (resolution === "check") return "A health check passed";
  if (resolution === "action") return "An action succeeded";
  return resolution ? `Resolved (${resolution})` : "Resolved";
}

export interface ReminderState {
  status: string;
  reminderHours: number;
  notifiedAt?: string | null;
  remindAfter?: string | null;
}

/** An open alert's reminder state: a reminder goes out on the next failure after the window. */
export function reminderText(alert: ReminderState, now: Date = new Date()): string {
  if (alert.status !== "open") return "";
  const told = alert.notifiedAt ? `Announced ${relative(alert.notifiedAt, now)}` : "Not announced yet";
  if (!alert.reminderHours) return `${told} · reminders off`;
  if (!alert.remindAfter) return told;
  const due = new Date(alert.remindAfter).getTime() <= now.getTime();
  return due
    ? `${told} · reminds on the next failure`
    : `${told} · reminds on a failure after ${relative(alert.remindAfter, now).replace(/^in /, "")}`;
}

export interface RetryState {
  status: string;
  attempt: number;
  maxAttempts: number;
  nextAttemptAt?: string | null;
  automationEnabled?: boolean;
}

/** Where a live retry stands: "Retry 2 of 3 · in 4 min", "Waiting for the connection to recover", … */
export function retryState(retry: RetryState, now: Date = new Date()): { text: string; tone: "ok" | "warn" | "muted" } {
  if (retry.status === "running") return { text: `Retry ${retry.attempt} of ${retry.maxAttempts} running now`, tone: "ok" };
  if (retry.status === "parked") return { text: "Waiting for the connection to recover", tone: "warn" };
  const next = `Retry ${retry.attempt + 1} of ${retry.maxAttempts}`;
  if (retry.automationEnabled === false) return { text: `${next} · waits until the workflow is enabled`, tone: "muted" };
  if (!retry.nextAttemptAt) return { text: next, tone: "muted" };
  const due = new Date(retry.nextAttemptAt).getTime() <= now.getTime();
  return { text: due ? `${next} · due now (within a minute)` : `${next} · ${relative(retry.nextAttemptAt, now)}`, tone: "muted" };
}

export interface HandledFailureLine {
  providerName?: string | null;
  provider?: string | null;
  integrationSlug?: string | null;
  code?: string | null;
  outcome: string;
}

/** "Square · rate_limited — retried, succeeded on retry 1". */
export function failureLine(f: HandledFailureLine): string {
  const who = f.providerName || f.provider || f.integrationSlug || "Integration";
  return `${who}${f.code ? ` · ${f.code}` : ""} — ${f.outcome}`;
}

/** Pages in a paged list (at least 1). */
export function pageCount(total: number, perPage: number): number {
  return Math.max(1, Math.ceil(Math.max(0, total) / Math.max(1, perPage)));
}

/**
 * The page's URL with one paging parameter changed (page 1 drops it), keeping the others — two lists
 * page independently. `anchor` brings the list back into view.
 */
export function pageHref(search: string, key: string, page: number, anchor = ""): string {
  const params = new URLSearchParams(search);
  if (page <= 1) params.delete(key);
  else params.set(key, String(page));
  const query = params.toString();
  return `${query ? `?${query}` : "?"}${anchor ? `#${anchor}` : ""}`;
}

/** A positive page number from a query parameter (anything else is page 1). */
export function pageParam(value: string | null | undefined): number {
  const n = Number.parseInt(value ?? "", 10);
  return Number.isFinite(n) && n > 0 ? n : 1;
}
