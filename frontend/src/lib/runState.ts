/**
 * Where a workflow run stands, in words (GET /api/automations/runs/{executionId}): what a guided setup's run step and the Timeline's run
 * button say instead of an endless "Running…". Pure, with type-only imports, so it runs under `node --test`: the pages fetch.
 */

import type { WorkflowRunState } from "@/lib/api/workflowRuns";

export type RunTone = "busy" | "ask" | "ok" | "bad";

export interface RunLine {
  text: string;
  tone: RunTone;
  /** Nothing more will happen: stop asking. */
  over: boolean;
}

const JOB_WORDS: Record<string, string> = { queued: "waiting for a worker", claimed: "starting", running: "running" };

/** One line for the state a run is in. */
export function runLine(run: WorkflowRunState): RunLine {
  switch (run.state) {
    case "starting":
      return { text: "Starting…", tone: "busy", over: false };
    case "running": {
      // A run over several entries records more steps than the workflow has: a count would read wrong, so it gives none.
      const counted = run.stepsTotal > 0 && run.stepsOk <= run.stepsTotal;
      return { text: counted ? `Running: ${run.stepsOk} of ${run.stepsTotal} steps done…` : "Running…", tone: "busy", over: false };
    }
    case "waiting": {
      const theirs = run.waitingOn.some((w) => w.message != null);
      return { text: theirs ? "Waiting on you: it asks a question." : "Waiting for an admin to answer its question.", tone: "ask", over: false };
    }
    case "working":
      return { text: `Working: the ${run.job?.kind ?? "worker"} job is ${JOB_WORDS[run.job?.status ?? ""] ?? "running"}…`, tone: "busy", over: false };
    case "done":
      return { text: run.job ? `Done: the ${run.job.kind} job finished.` : "Done.", tone: "ok", over: true };
    case "failed":
      return { text: run.error ? `Failed: ${run.error}` : "Failed. The workflow’s runs say why.", tone: "bad", over: true };
    default:
      return { text: "Stopped: this run will not go on.", tone: "bad", over: true };
  }
}

/** What a server-drawn page depends on: the state, and the approvals it waits on. When this changes the page is drawn again; a step count
 *  alone only changes the line's words. */
export function runKey(run: WorkflowRunState): string {
  return [run.state, ...run.waitingOn.map((w) => w.approvalId)].join("|");
}
