/**
 * A button on a timeline that starts a workflow (a render) and then says how it is going. The workflow makes a `job` entry for the worker; this
 * finds the one this click started (the newest job made since, whose args name the entry) and puts its state in words. Pure: the page fetches.
 */

export interface JobRow {
  createdAt?: string | null;
  dataJson?: { status?: string; args?: unknown; result?: { url?: string | null } | null; log?: string | null } | null;
}

/** Jobs made a little before the click still count (the server's clock is not the browser's). */
const SLACK_MS = 30_000;

/** The newest job started since `since` (ms) whose args mention `slug`, or null while the workflow has not made one yet. */
export function jobFor(jobs: readonly JobRow[], slug: string, since: number): JobRow | null {
  const mine = jobs
    .filter((j) => j.createdAt && Date.parse(j.createdAt) >= since - SLACK_MS && JSON.stringify(j.dataJson?.args ?? "").includes(JSON.stringify(slug)))
    .sort((a, b) => Date.parse(b.createdAt!) - Date.parse(a.createdAt!));
  return mine[0] ?? null;
}

export interface RunState {
  text: string;
  /** No more polling: it finished or failed. */
  finished: boolean;
  /** The finished video, when the job reports one. */
  url: string | null;
}

/** What to tell the person, from the job's status, or from there being no job yet. */
export function runState(job: JobRow | null, label: string): RunState {
  if (!job) return { text: `${label}: starting…`, finished: false, url: null };
  const d = job.dataJson ?? {};
  switch (d.status) {
    case "done":
      return { text: `${label}: done.`, finished: true, url: d.result?.url ?? null };
    case "failed":
      return { text: `${label} failed: ${lastLine(d.log) || "see the job's log"}`, finished: true, url: null };
    case "claimed":
    case "running":
      return { text: `${label}: the worker is making it (a few minutes)…`, finished: false, url: null };
    default:
      return { text: `${label}: waiting for the worker…`, finished: false, url: null };
  }
}

const lastLine = (log: string | null | undefined): string => (log ?? "").trim().split("\n").filter(Boolean).pop()?.slice(0, 200) ?? "";
