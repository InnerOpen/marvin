/**
 * Formatting for Admin → Backup health: badges, sizes, durations and "how long ago" — pure, so it is
 * tested with node --test (backupHealth.test.mjs).
 */

export type Tone = "ok" | "warn" | "err" | "muted";

const STATE: Record<string, { label: string; tone: Tone }> = {
  ok: { label: "OK", tone: "ok" },
  partial: { label: "Partial", tone: "warn" },
  failed: { label: "Failed", tone: "err" },
  missed: { label: "Missed", tone: "err" },
  overdue: { label: "Overdue", tone: "err" },
  unknown: { label: "No schedule", tone: "muted" },
};

/** The badge for a target state or a run status. */
export function stateBadge(state: string): { label: string; tone: Tone } {
  return STATE[state] ?? { label: state, tone: "muted" };
}

export function formatBytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (n < 1000) return `${n} B`;
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)} kB`;
  if (n < 1_000_000_000) return `${(n / 1_000_000).toFixed(1)} MB`;
  return `${(n / 1_000_000_000).toFixed(2)} GB`;
}

/** 8.7 s, 4 min 05 s, 1 h 02 min. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m} min ${String(Math.round(seconds % 60)).padStart(2, "0")} s`;
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
}

/** "every hour", "every 24 h", "every 15 min". */
export function formatInterval(seconds: number | null | undefined): string {
  if (!seconds) return "—";
  if (seconds === 3600) return "every hour";
  if (seconds % 3600 === 0) return `every ${seconds / 3600} h`;
  if (seconds < 3600) return `every ${Math.round(seconds / 60)} min`;
  return `every ${(seconds / 3600).toFixed(1)} h`;
}

/** "in 12 min", "3 h ago", "just now" — relative to `now` (both ISO strings or dates). */
export function relativeTime(when: string | null | undefined, now: string | Date): string {
  if (!when) return "—";
  const diff = new Date(when).getTime() - new Date(now).getTime();
  const abs = Math.abs(diff);
  const minute = 60_000;
  if (abs < minute) return "just now";
  let text: string;
  if (abs < 60 * minute) text = `${Math.round(abs / minute)} min`;
  else if (abs < 48 * 60 * minute) text = `${Math.round(abs / (60 * minute))} h`;
  else text = `${Math.round(abs / (24 * 60 * minute))} days`;
  return diff > 0 ? `in ${text}` : `${text} ago`;
}

/** 48 hourly · 30 daily · 8 weekly; a count that is off (0) or wasn't recorded is left out. */
export function formatRetention(t: {
  keepHourly: number | null;
  keepDaily: number | null;
  keepWeekly: number | null;
}): string {
  const parts = [
    [t.keepHourly, "hourly"],
    [t.keepDaily, "daily"],
    [t.keepWeekly, "weekly"],
  ]
    .filter(([n]) => n !== null && n !== undefined && n !== 0)
    .map(([n, label]) => `${n} ${label}`);
  return parts.length ? parts.join(" · ") : "—";
}

/** Schedule and zone for people: "0 * * * * (America/New_York)". */
export function formatSchedule(schedule: string | null, timeZone: string | null): string {
  if (!schedule) return "—";
  return timeZone ? `${schedule} (${timeZone})` : `${schedule} (UTC)`;
}
