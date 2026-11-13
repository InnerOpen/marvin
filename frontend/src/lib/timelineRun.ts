/**
 * A button on a timeline that starts a workflow (a render) and then says how it is going. Starting it answers with the run's id; the run is
 * followed by that id (lib/api/workflowRuns.ts) past its approvals to the worker job it makes, and this puts where it stands in words.
 * Pure: the page fetches.
 */

import type { WorkflowRunState } from "@/lib/api/workflowRuns";
import { runLine } from "./runState.ts";

/** The worker's job entry, read once the run is over: the video it made, or why it failed. */
export interface JobRow {
  dataJson?: { status?: string; result?: { url?: string | null } | null; log?: string | null } | null;
}

export interface RunState {
  text: string;
  /** No more polling: it finished or failed. */
  finished: boolean;
  /** The finished video, when the job reports one. */
  url: string | null;
  /** It waits for an approval: point at where to answer it. */
  ask: boolean;
}

/** The run a click started: the id in the answer of `POST /api/automations/{id}/run?background=true` (null when it named none). */
export function startedRun(answer: { execution_id?: string | null } | null | undefined): string | null {
  return answer?.execution_id || null;
}

/** What to tell the person from where the run stands. `job` is the worker's job entry, given once the run is over. */
export function followed(run: WorkflowRunState | null, label: string, job: JobRow | null = null): RunState {
  if (!run) return { text: `${label}: started, but its run is not on record. Look under Workers.`, finished: true, url: null, ask: false };
  const line = runLine(run);
  if (run.state === "done") return { text: `${label}: done.`, finished: true, url: job?.dataJson?.result?.url ?? null, ask: false };
  if (run.state === "failed") return { text: `${label} failed: ${lastLine(job?.dataJson?.log) || run.error || "see the workflow’s runs"}`, finished: true, url: null, ask: false };
  return { text: `${label}: ${line.text.charAt(0).toLowerCase()}${line.text.slice(1)}`, finished: line.over, url: null, ask: run.state === "waiting" };
}

const lastLine = (log: string | null | undefined): string => (log ?? "").trim().split("\n").filter(Boolean).pop()?.slice(0, 200) ?? "";
