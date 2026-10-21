// The Scheduled tasks page's list: the Schedule filter (hourly, daily, weekly, other), how a schedule reads, the adapter that
// feeds the shared list kit (organizedList.ts) and the cards. Pure, so `npm test` covers it (scheduledTaskList.test.mjs).

import type { Choice, ListAdapter } from "./organizedList.ts";
import { menuHtml, switchHtml } from "./organizedListHtml.ts";
import { timeAgo } from "./socialInbox.ts";

/** A task as `GET /api/platform/scheduled-tasks/overview` returns it (camelCase), as far as the list needs. */
export interface ScheduledTaskRow {
  id: string;
  name: string;
  slug?: string;
  description?: string | null;
  enabled: boolean;
  taskType?: string;
  scheduleType?: string;
  /** The stored schedule; its own keys are snake_case (cron_expression, interval_seconds, run_at, timezone). */
  scheduleConfig?: Record<string, any> | null;
  lastRunAt?: string | null;
  nextRunAt?: string | null;
  /** success | failed | timeout | cancelled; null: never run. */
  lastStatus?: string | null;
  lastDurationMs?: number | null;
  sourceIntegrationId?: string | null;
  sourceBlueprint?: string | null;
  /** Marvin's own: a platform task. Read-only. */
  system?: boolean;
  /** Why it needs a look (the server decides): "last_run_failed"; null/absent: it doesn't. */
  attention?: string | null;
}

export interface TaskRun {
  id: string;
  status: string;
  executedAt: string;
  durationMs?: number | null;
  errorMessage?: string | null;
  output?: string | null;
}

export type ScheduleBucket = "hourly" | "daily" | "weekly" | "other";

export const SCHEDULE_OPTIONS: Choice[] = [
  { value: "hourly", label: "Hourly" },
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "other", label: "Other" },
];

const esc = (s: unknown): string =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string,
  );

const pick = (config: Record<string, any> | null | undefined, camel: string, snake: string) => config?.[camel] ?? config?.[snake];

const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const DAY_NAMES: Record<string, number> = { sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6 };
const isNumber = (s: string) => /^\d+$/.test(s);
const two = (n: number | string) => String(n).padStart(2, "0");

/** The parts of a five-field cron expression, or null. */
function cronFields(task: ScheduledTaskRow) {
  if (task.scheduleType !== "cron") return null;
  const parts = String(pick(task.scheduleConfig, "cronExpression", "cron_expression") ?? "")
    .trim()
    .split(/\s+/);
  return parts.length === 5 ? { minute: parts[0], hour: parts[1], dom: parts[2], month: parts[3], dow: parts[4] } : null;
}

const weekday = (dow: string): number | null => {
  if (isNumber(dow)) return Number(dow) % 7;
  return DAY_NAMES[dow.toLowerCase().slice(0, 3)] ?? null;
};

/** Which Schedule filter bucket a task falls in. Only the plain shapes count as hourly, daily or weekly: an interval of
 * exactly an hour, a day or a week, or a cron of one minute past every hour, one time every day, one time one weekday. */
export function scheduleBucket(task: ScheduledTaskRow): ScheduleBucket {
  if (task.scheduleType === "interval") {
    const secs = Number(pick(task.scheduleConfig, "intervalSeconds", "interval_seconds"));
    return secs === 3600 ? "hourly" : secs === 86400 ? "daily" : secs === 604800 ? "weekly" : "other";
  }
  const c = cronFields(task);
  if (!c || c.month !== "*" || !isNumber(c.minute)) return "other";
  if (c.hour === "*" && c.dom === "*" && c.dow === "*") return "hourly";
  if (!isNumber(c.hour) || c.dom !== "*") return "other";
  if (c.dow === "*") return "daily";
  return weekday(c.dow) !== null && !c.dow.includes(",") && !c.dow.includes("-") ? "weekly" : "other";
}

const plural = (n: number, unit: string) => `${n} ${unit}${n === 1 ? "" : "s"}`;

/** "Every hour", "Every 15 minutes", "Every day at 03:00 (Europe/London)", "Every Monday at 07:30"; what it can't say, as it is. */
export function scheduleText(task: ScheduledTaskRow): string {
  const config = task.scheduleConfig;
  if (!config) return "No schedule";
  if (task.scheduleType === "interval") {
    const secs = Number(pick(config, "intervalSeconds", "interval_seconds"));
    if (!secs) return "—";
    const [n, unit] =
      secs % 86400 === 0 ? [secs / 86400, "day"] : secs % 3600 === 0 ? [secs / 3600, "hour"] : [Math.max(1, Math.round(secs / 60)), "minute"];
    return n === 1 ? `Every ${unit}` : `Every ${plural(n, unit)}`;
  }
  if (task.scheduleType === "once") return `Once: ${pick(config, "runAt", "run_at") || "—"}`;
  const c = cronFields(task);
  const expr = pick(config, "cronExpression", "cron_expression");
  const bucket = scheduleBucket(task);
  if (!c || bucket === "other") return `Cron: ${expr ?? "—"}`;
  const tz = config.timezone && config.timezone !== "UTC" ? ` (${config.timezone})` : "";
  if (bucket === "hourly") return `Every hour at :${two(c.minute)}`;
  const at = `${two(c.hour)}:${two(c.minute)}${tz}`;
  return bucket === "daily" ? `Every day at ${at}` : `Every ${DAYS[weekday(c.dow)!]} at ${at}`;
}

/** The adapter for the shared list kit: Marvin's own tasks are the `system` source; `attention` is the server's flag. */
export function scheduledTaskAdapter(): ListAdapter<ScheduledTaskRow> {
  return {
    id: (t) => t.id,
    name: (t) => t.name,
    search: (t) => [t.slug ?? "", t.taskType ?? "", t.description ?? "", scheduleText(t)],
    source: (t) => ({
      system: !!t.system,
      integrationId: t.sourceIntegrationId ?? null,
      blueprint: t.sourceBlueprint ?? null,
    }),
    enabled: (t) => t.enabled,
    attention: (t) => !!t.attention,
    facets: { schedule: scheduleBucket },
  };
}

const RUN_OUTCOMES: Record<string, string> = {
  success: "succeeded",
  failed: "failed",
  timeout: "timed out",
  cancelled: "cancelled",
};
const isFailure = (status: string | null | undefined) => status === "failed" || status === "timeout";

const ATTENTION_REASONS: Record<string, string> = { last_run_failed: "The last run failed" };

/** "Last run 2 h ago · failed" (failures marked), or "Not run yet". */
export function lastRunHtml(task: ScheduledTaskRow, now: Date = new Date()): string {
  const when = timeAgo(task.lastRunAt, now);
  if (!when || !task.lastStatus) return '<div class="st-last none">Not run yet</div>';
  const outcome = RUN_OUTCOMES[task.lastStatus] ?? task.lastStatus;
  return `<div class="st-last${isFailure(task.lastStatus) ? " failed" : ""}">Last run ${esc(when)} · ${esc(outcome)}</div>`;
}

export function attentionHtml(task: ScheduledTaskRow): string {
  if (!task.attention) return "";
  const why = ATTENTION_REASONS[task.attention] ?? "Needs a look";
  return `<div class="st-attention" title="${esc(why)}"><strong>Needs a look</strong> · ${esc(why)}</div>`;
}

/** One compact task card. Everyone who can see the page gets the history; the switch, Run now, Edit and Delete are for admins
 * (`canManage`) and never for Marvin's own. The page attaches handlers by class (js-toggle, js-run, js-edit, js-history,
 * js-delete) and fills `.st-history`. */
export function scheduledTaskCardHtml(
  task: ScheduledTaskRow,
  options: { canManage: boolean; linked: boolean; now?: Date },
): string {
  const acts = options.canManage && !task.system;
  const next = task.enabled && task.nextRunAt ? ` · next ${esc(new Date(task.nextRunAt).toISOString().slice(0, 16).replace("T", " "))} UTC` : "";
  return `<article class="org-card st-card${task.enabled ? "" : " off"}${options.linked ? " linked" : ""}" data-id="${esc(task.id)}">
    <div class="org-card-main">
      <div class="org-card-title"><strong>${esc(task.name)}</strong></div>
      <div class="org-card-sub">${task.enabled ? "" : "Off · "}${esc(scheduleText(task))}${next}</div>
      ${task.description ? `<div class="st-description">${esc(task.description)}</div>` : ""}
      ${attentionHtml(task)}
      ${lastRunHtml(task, options.now)}
      <div class="st-history" hidden></div>
    </div>
    <div class="org-card-actions">
      ${acts ? switchHtml({ on: task.enabled, cls: "js-toggle", label: task.name }) : ""}
      ${acts ? `<button type="button" class="org-btn primary js-run"${task.enabled ? "" : ' disabled title="Switch the task on to run it"'}>Run now</button>` : ""}
      <button type="button" class="org-btn js-history">Runs</button>
      ${
        acts
          ? menuHtml([
              { cls: "js-edit", label: "Edit" },
              { cls: "js-delete", label: "Delete", danger: true },
            ])
          : ""
      }
    </div>
  </article>`;
}

/** A task's runs, newest first: when, how it went, how long, and what it did or why it failed. */
export function historyHtml(runs: TaskRun[], now: Date = new Date()): string {
  if (!runs.length) return '<div class="st-run none">No runs yet.</div>';
  return runs
    .map((run) => {
      const outcome = RUN_OUTCOMES[run.status] ?? run.status;
      const took = run.durationMs == null ? "" : ` · ${(run.durationMs / 1000).toFixed(1)} s`;
      const note = run.errorMessage || run.output;
      return `<div class="st-run${isFailure(run.status) ? " failed" : ""}"><strong>${esc(outcome)}</strong> · ${esc(timeAgo(run.executedAt, now))}${took}${note ? `<div class="st-run-note">${esc(note)}</div>` : ""}</div>`;
    })
    .join("");
}
