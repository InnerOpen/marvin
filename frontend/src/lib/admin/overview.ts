/**
 * Summaries for the admin overview (/admin): turn the admin API's lists into the few numbers and
 * warnings a platform operator should see first. Pure, so the thresholds are testable.
 */

/** A platform with no backup newer than this is flagged on the overview. */
export const BACKUP_STALE_DAYS = 7;

/** Last-run statuses that mean a scheduled task needs attention (see ScheduledTaskExecutionLogRead). */
export const FAILED_TASK_STATUSES = ["failed", "timeout"];

const MS_PER_MINUTE = 60_000;
const MINUTES_PER_HOUR = 60;
const HOURS_PER_DAY = 24;
const MS_PER_DAY = MS_PER_MINUTE * MINUTES_PER_HOUR * HOURS_PER_DAY;

export interface BackupSummary {
  state: "none" | "stale" | "fresh";
  latestAt: string | null;
}

export interface TaskSummary {
  total: number;
  enabled: number;
  failing: { id: string; name: string }[];
  lastRunAt: string | null;
}

interface BackupLike {
  created_at: string;
}

interface TaskLike {
  id: string;
  name: string;
  enabled: boolean;
  lastStatus: string | null;
  lastRunAt: string | null;
}

function latest(isoDates: (string | null)[]): string | null {
  let best: string | null = null;
  let bestMs = Number.NEGATIVE_INFINITY;
  for (const iso of isoDates) {
    const ms = iso ? Date.parse(iso) : Number.NaN;
    if (!Number.isNaN(ms) && ms > bestMs) {
      best = iso;
      bestMs = ms;
    }
  }
  return best;
}

/** The newest backup and whether it is recent enough; no backup at all is its own warning. */
export function summarizeBackups(backups: BackupLike[], now: number = Date.now()): BackupSummary {
  const latestAt = latest(backups.map((b) => b.created_at));
  if (!latestAt) return { state: "none", latestAt: null };
  const ageMs = now - Date.parse(latestAt);
  return { state: ageMs > BACKUP_STALE_DAYS * MS_PER_DAY ? "stale" : "fresh", latestAt };
}

/** Enabled tasks whose last run failed — a disabled task's old failure is not news. */
export function summarizeTasks(tasks: TaskLike[]): TaskSummary {
  const enabled = tasks.filter((t) => t.enabled);
  return {
    total: tasks.length,
    enabled: enabled.length,
    failing: enabled
      .filter((t) => t.lastStatus !== null && FAILED_TASK_STATUSES.includes(t.lastStatus))
      .map((t) => ({ id: t.id, name: t.name })),
    lastRunAt: latest(tasks.map((t) => t.lastRunAt)),
  };
}

/** Compact age, "just now" / "5m ago" / "3h ago" / "12d ago". */
export function formatAge(iso: string, now: number = Date.now()): string {
  const minutes = Math.floor((now - Date.parse(iso)) / MS_PER_MINUTE);
  if (minutes < 1) return "just now";
  if (minutes < MINUTES_PER_HOUR) return `${minutes}m ago`;
  const hours = Math.floor(minutes / MINUTES_PER_HOUR);
  if (hours < HOURS_PER_DAY) return `${hours}h ago`;
  return `${Math.floor(hours / HOURS_PER_DAY)}d ago`;
}
