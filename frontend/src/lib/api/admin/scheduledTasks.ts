/**
 * Admin Scheduled Tasks API - manage system and workspace tasks
 */

import { fetchApi } from "../client";

export interface ScheduledTaskRead {
  id: string;
  groupId: string | null;
  name: string;
  slug: string;
  description: string | null;
  enabled: boolean;
  scheduleType: string;
  scheduleConfig: Record<string, any>;
  taskType: string;
  taskConfig: Record<string, any>;
  lastRunAt: string | null;
  nextRunAt: string | null;
  lastStatus: string | null;
  lastDurationMs: number | null;
  failureCount: number;
}

export interface ScheduledTaskExecutionLogRead {
  id: string;
  taskId: string;
  groupId: string | null;
  executedAt: string;
  status: string;
  durationMs: number | null;
  errorMessage: string | null;
  errorTraceback: string | null;
  output: string | null;
  retryAttempt: number;
}

export async function listAllTasks(authToken?: string): Promise<ScheduledTaskRead[]> {
  return fetchApi<ScheduledTaskRead[]>("/api/admin/scheduled-tasks", { method: "GET" }, authToken);
}

export async function getSystemTask(id: string, authToken?: string): Promise<ScheduledTaskRead> {
  return fetchApi<ScheduledTaskRead>(`/api/admin/scheduled-tasks/${id}`, { method: "GET" }, authToken);
}

export async function getSystemTaskHistory(
  id: string,
  limit = 50,
  authToken?: string,
): Promise<ScheduledTaskExecutionLogRead[]> {
  return fetchApi<ScheduledTaskExecutionLogRead[]>(
    `/api/admin/scheduled-tasks/${id}/history?limit=${limit}`,
    { method: "GET" },
    authToken,
  );
}

export async function getGlobalLog(limit = 100, authToken?: string): Promise<ScheduledTaskExecutionLogRead[]> {
  return fetchApi<ScheduledTaskExecutionLogRead[]>(
    `/api/admin/scheduled-tasks/log?limit=${limit}`,
    { method: "GET" },
    authToken,
  );
}
