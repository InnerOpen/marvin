// Settings → Workers: the queue of heavy jobs and what is watching it, read from the workspace's own records.
//   `job`       one task: kind, args, status (queued → claimed → running → done / failed), result, log, claimed_at
//   `job-kind`  which image and mode runs a kind, and how long it may take (timeout_seconds)
//   `worker`    a dispatcher's heartbeat: it rewrites its `last_seen` every minute or so
// This only turns those records into what the page shows; it holds no state of its own.

export interface RecordRow {
  id: string;
  slug: string;
  title: string;
  createdAt?: string | null;
  dataJson?: Record<string, unknown> | null;
}

export const STATUSES = ["queued", "claimed", "running", "done", "failed"] as const;
export type JobStatus = (typeof STATUSES)[number];

const DEFAULT_TIMEOUT_SECONDS = 3600;
const GRACE_SECONDS = 120; // the dispatcher's own allowance before it fails a silent job
export const SEEN_RECENTLY_SECONDS = 180; // a dispatcher beats about every minute; three minutes of quiet is trouble

const field = (row: RecordRow, key: string): unknown => row.dataJson?.[key];
const text = (v: unknown): string => (typeof v === "string" ? v : "");
const seconds = (iso: unknown, now: number): number | null => {
  const t = typeof iso === "string" ? Date.parse(iso) : NaN;
  return Number.isNaN(t) ? null : Math.max(0, Math.round((now - t) / 1000));
};

export interface JobView {
  id: string;
  title: string;
  kind: string;
  status: string;
  log: string;
  queuedAgo: number | null;
  /** claimed or running for longer than its kind allows: the dispatcher is about to fail it, or has not noticed */
  stuck: boolean;
  /** queued, and nothing registered for its kind: it will fail as soon as a dispatcher looks */
  unknownKind: boolean;
}

export interface DispatcherView {
  name: string;
  lastSeenAgo: number | null;
  healthy: boolean;
  modes: string;
  jobsStarted: number | null;
}

export interface WorkersView {
  counts: Record<string, number>;
  jobs: JobView[];
  kinds: { kind: string; mode: string; image: string; url: string; timeoutSeconds: number; notes: string }[];
  dispatchers: DispatcherView[];
  /** what to tell the person at the top: nothing running, jobs waiting with no one to start them, jobs stuck */
  warnings: string[];
}

export function summarize(jobs: RecordRow[], kindRows: RecordRow[], workers: RecordRow[], now: number = Date.now()): WorkersView {
  const kinds = kindRows.map((row) => ({
    kind: text(field(row, "kind")),
    mode: text(field(row, "mode")) || "kubernetes",
    image: text(field(row, "image")),
    url: text(field(row, "url")),
    timeoutSeconds: Number(field(row, "timeout_seconds")) || DEFAULT_TIMEOUT_SECONDS,
    notes: text(field(row, "notes")),
  }));
  const allowed = new Map(kinds.map((k) => [k.kind, k.timeoutSeconds]));

  const views: JobView[] = jobs.map((row) => {
    const kind = text(field(row, "kind"));
    const status = text(field(row, "status")) || "queued";
    const sinceClaim = seconds(field(row, "claimed_at"), now);
    const limit = (allowed.get(kind) ?? DEFAULT_TIMEOUT_SECONDS) + GRACE_SECONDS;
    return {
      id: row.id,
      title: row.title,
      kind,
      status,
      log: text(field(row, "log")),
      queuedAgo: seconds(row.createdAt, now),
      stuck: (status === "claimed" || status === "running") && sinceClaim !== null && sinceClaim > limit,
      unknownKind: status === "queued" && !allowed.has(kind),
    };
  });

  const counts: Record<string, number> = Object.fromEntries(STATUSES.map((s) => [s, 0]));
  for (const job of views) counts[job.status] = (counts[job.status] ?? 0) + 1;

  const dispatchers: DispatcherView[] = workers
    .map((row) => {
      const ago = seconds(field(row, "last_seen"), now);
      return {
        name: text(field(row, "host")) || row.title,
        lastSeenAgo: ago,
        healthy: ago !== null && ago <= SEEN_RECENTLY_SECONDS,
        modes: text(field(row, "modes")),
        jobsStarted: typeof field(row, "jobs_started") === "number" ? (field(row, "jobs_started") as number) : null,
      };
    })
    .sort((a, b) => (a.lastSeenAgo ?? Infinity) - (b.lastSeenAgo ?? Infinity));

  const warnings: string[] = [];
  const anyHealthy = dispatchers.some((d) => d.healthy);
  if (!anyHealthy && counts.queued > 0) warnings.push(`${counts.queued} job${counts.queued === 1 ? " is" : "s are"} queued and no dispatcher has reported in the last ${SEEN_RECENTLY_SECONDS / 60} minutes. Nothing will start them until one is running.`);
  if (!dispatchers.length) warnings.push("No dispatcher has reported yet. Start one with `python -m marvin_worker dispatch` (see the marvin-worker README).");
  const stuck = views.filter((j) => j.stuck).length;
  if (stuck) warnings.push(`${stuck} job${stuck === 1 ? " has" : "s have"} run past the time allowed without an outcome.`);
  const unknown = views.filter((j) => j.unknownKind).length;
  if (unknown) warnings.push(`${unknown} queued job${unknown === 1 ? " asks" : "s ask"} for a kind nobody registered: add a job kind for it.`);

  return { counts, jobs: views, kinds, dispatchers, warnings };
}

/** "5 s", "3 min", "2 h", "4 d": how long ago, short. */
export function ago(secs: number | null): string {
  if (secs === null) return "never";
  if (secs < 90) return `${secs} s`;
  if (secs < 5400) return `${Math.round(secs / 60)} min`;
  if (secs < 129600) return `${Math.round(secs / 3600)} h`;
  return `${Math.round(secs / 86400)} d`;
}
