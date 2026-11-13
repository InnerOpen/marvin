/**
 * A workflow run as whoever started it follows it: start it (POST /api/automations/{id}/run?background=true answers with the run's
 * `execution_id`), then ask where it stands (GET /api/automations/runs/{executionId}); and one workflow by slug, for a page that offers
 * to run it (GET /api/automations/state?slug=). Editors and above may read; starting a run is an admin's. Hand-rolled until the SDK
 * ships these.
 */

import { ApiRequestError, fetchApi } from "./client";

export interface RunWaitingOn {
  approvalId: string;
  /** Null when the approval is above the reader's role: not theirs to read or answer. */
  message?: string | null;
  approvers: "editor" | "admin" | string;
}

/** The worker job the run's last step started. */
export interface RunJob {
  entryId: string;
  slug: string;
  kind: string;
  status: string;
  finished: boolean;
}

export interface WorkflowRunState {
  executionId: string;
  automationSlug: string;
  automationName?: string | null;
  state: "starting" | "running" | "waiting" | "working" | "done" | "failed" | "cancelled";
  startedAt?: string | null;
  finishedAt?: string | null;
  error?: string | null;
  stepsTotal: number;
  stepsOk: number;
  stepsFailed: number;
  waitingOn: RunWaitingOn[];
  /** The newest run that went on from this one after an approval or a wait. */
  continuedBy?: string | null;
  job?: RunJob | null;
}

export interface WorkflowStateRead {
  found: boolean;
  id?: string | null;
  enabled: boolean;
  name?: string | null;
  /** The signed-in person may run it now: an admin, and it is on. */
  canRun: boolean;
}

/** Where the run stands now; null when the workspace has no such run. */
export async function getRunState(executionId: string, authToken?: string): Promise<WorkflowRunState | null> {
  try {
    return await fetchApi<WorkflowRunState>(`/api/automations/runs/${encodeURIComponent(executionId)}`, {}, authToken);
  } catch (e) {
    if (e instanceof ApiRequestError && e.status === 404) return null;
    throw e;
  }
}

export async function getWorkflowState(slug: string, authToken?: string): Promise<WorkflowStateRead> {
  return fetchApi<WorkflowStateRead>(`/api/automations/state?slug=${encodeURIComponent(slug)}`, {}, authToken);
}

/** Start a workflow now without waiting for it. Returns the run's id to follow (null when the server could not record the run). */
export async function startRun(workflowId: string, inputs: Record<string, unknown>, authToken?: string): Promise<string | null> {
  const started = await fetchApi<{ execution_id?: string | null }>(
    `/api/automations/${encodeURIComponent(workflowId)}/run?background=true`,
    { method: "POST", body: JSON.stringify({ inputs }) },
    authToken,
  );
  return started?.execution_id ?? null;
}
