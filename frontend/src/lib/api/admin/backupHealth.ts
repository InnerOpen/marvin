/**
 * Admin Backup Health API - the installation backup targets (one CronJob each) as their runs report them.
 * The backend can't see Kubernetes: each run records itself in the database when it ends, failed ones
 * included, and the backend works out the next run and "overdue" from the recorded schedule.
 * Nothing here is ever a credential.
 */

import { fetchApi } from "../client";

export type BackupRunStatus = "ok" | "partial" | "failed" | "missed";
export type BackupTargetState = "ok" | "partial" | "failed" | "overdue" | "unknown";

export interface BackupRun {
  id: string;
  targetName: string;
  targetType: string;
  /** ok; partial (the database was saved, another step failed); failed; missed (no successful run in time). */
  status: BackupRunStatus;
  startedAt: string;
  finishedAt: string | null;
  durationSeconds: number | null;
  dbEngine: string | null;
  dbKey: string | null;
  dbBytes: number | null;
  dbGzBytes: number | null;
  configItems: number | null;
  assetsUploaded: number | null;
  assetsUploadedBytes: number | null;
  assetsUnchanged: number | null;
  pruned: number | null;
  failures: number;
  errorSummary: string | null;
  /** The pod that ran it. */
  host: string | null;
  notifiedAt: string | null;
}

export interface BackupTarget {
  name: string;
  type: string;
  state: BackupTargetState;
  schedule: string | null;
  timeZone: string | null;
  /** Why next run / overdue can't be worked out. */
  scheduleError: string | null;
  intervalSeconds: number | null;
  keepHourly: number | null;
  keepDaily: number | null;
  keepWeekly: number | null;
  location: string | null;
  settings: Record<string, string>;
  lastRun: BackupRun | null;
  lastSuccess: BackupRun | null;
  firstSeen: string | null;
  nextRunAt: string | null;
  /** A successful run must start before this, or the target is overdue. */
  dueBy: string | null;
  overdue: boolean;
  overdueSince: string | null;
}

export interface BackupHealth {
  now: string;
  targets: BackupTarget[];
  runs: BackupRun[];
}

export async function getBackupHealth(
  opts: { target?: string; limit?: number } = {},
  authToken?: string,
): Promise<BackupHealth> {
  const q = new URLSearchParams();
  if (opts.target) q.set("target", opts.target);
  if (opts.limit) q.set("limit", String(opts.limit));
  const qs = q.toString();
  return fetchApi<BackupHealth>(`/api/admin/backup-health${qs ? `?${qs}` : ""}`, { method: "GET" }, authToken);
}
