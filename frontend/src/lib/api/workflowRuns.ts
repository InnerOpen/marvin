/**
 * A workflow run as whoever started it follows it: start it (POST /api/automations/{id}/run?background=true answers with the run's
 * `execution_id`), then ask where it stands (GET /api/automations/runs/{executionId}); and one workflow by slug, for a page that offers
 * to run it (GET /api/automations/state?slug=), and what it would act on before it runs (POST /api/automations/selection). Editors and
 * above may read; starting a run is an admin's. Hand-rolled until the SDK ships these.
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

/** The latest run of a workflow that acted on an entry (GET /api/automations/runs), as getRunState says it; null when there is none.
 *  What a page that did not start the run (a reload, another tab) reads to know whether one is still going. */
export async function latestRunAbout(workflow: string, entryId: string, authToken?: string): Promise<WorkflowRunState | null> {
  const query = new URLSearchParams({ automation: workflow, entry_id: entryId });
  const found = await fetchApi<WorkflowRunState[]>(`/api/automations/runs?${query}`, {}, authToken);
  return found[0] ?? null;
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

/** One condition of a reason something is left out: a `where` item of an entry query. */
export interface SelectionCondition {
  field: string;
  op: string;
  value?: unknown;
}

/** A picture as a template's preview names it. */
export interface TemplatePreviewPicture {
  id: string;
  name: string;
  filename: string;
  url?: string | null;
}

/** One entry a template would make (`create`) or fill (`fill`), or leaves alone (`skip`, with the reason in `note`). */
export interface TemplatePreviewRow {
  action: "create" | "fill" | "skip";
  entryId?: string | null;
  title: string;
  asset?: TemplatePreviewPicture | null;
  /** What would be set: title, summary, description, status, and the type's fields by key under `fields`. */
  changes?: { fields?: Record<string, unknown>; [key: string]: unknown } | null;
  tags?: string[];
  collections?: string[];
  /** The picture would be attached to the entry (it is not yet). */
  attach?: boolean;
  note?: string | null;
  /** What stops it: nothing is made while any row has one. */
  error?: string | null;
  /** With a picture preset: the treated picture the entry gets, when it was made before. */
  treated?: TemplatePreviewPicture | null;
}

/** What a template's preview step answers (POST /entries/from-template says the same): the rows, and how many of each. */
export interface TemplatePreview {
  entryType: string;
  template: string;
  total: number;
  create: number;
  fill: number;
  skip: number;
  /** create + fill: what the step that writes confirms. */
  todo: number;
  errors: number;
  rows: TemplatePreviewRow[];
}

/** The entries a workflow's first step (a `collect`) would gather if it ran now, in its order. `found` false: it does not start by
 *  gathering entries. `leftOut` counts, for each reason asked, the entries of the same query that match it instead. A workflow that
 *  starts by previewing a template answers that `preview` instead (no `ids`): `count` is its `todo`. */
export interface WorkflowSelection {
  found: boolean;
  step?: string | null;
  ids: string[];
  count: number;
  total: number;
  limit?: number | null;
  leftOut: number[];
  preview?: TemplatePreview | null;
}

export async function getSelection(slug: string, inputs: Record<string, unknown>, leftOut: SelectionCondition[][], authToken?: string): Promise<WorkflowSelection> {
  return fetchApi<WorkflowSelection>("/api/automations/selection", { method: "POST", body: JSON.stringify({ slug, inputs, left_out: leftOut }) }, authToken);
}
