/**
 * The workspace Scheduled tasks page's reads (EDITOR and above; a 403 below): the workspace's tasks with Marvin's own (`system`),
 * and a task's run history. Acting on a task (switch, run now, delete) goes through the SDK's scheduledTasks, which is ADMIN.
 * Not in the SDK yet, so these use fetchApi. Pass authToken in SSR.
 */

import type { ScheduledTaskRow, TaskRun } from "../scheduledTaskList";
import { fetchApi } from "./client";

const BASE = "/api/platform/scheduled-tasks/overview";

export const listScheduledTaskOverview = (authToken?: string) => fetchApi<ScheduledTaskRow[]>(BASE, {}, authToken);

export const getScheduledTaskRuns = (id: string, limit = 20) =>
  fetchApi<TaskRun[]>(`${BASE}/${encodeURIComponent(id)}/history?limit=${limit}`);
