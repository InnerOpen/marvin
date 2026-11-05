// Settings → Workers: the queue of heavy jobs and what is watching it, read from the workspace's own records.
//   `job`       one task: kind, args, status (queued → claimed → running → done / failed), result, log, claimed_at
//   `job-kind`  which image and mode runs a kind, and how long it may take (timeout_seconds)
//   `worker`    a dispatcher's or runner's heartbeat: it rewrites `last_seen` every minute or so, and says which kinds it can do (`kinds`,
//               each with its contract: what it takes, accepts, produces and needs), whether it is idle or busy, and what it needs to run
// This only turns those records into what the page shows; it holds no state of its own.

/** The record types workers need; core's "Workers" blueprints add them (services/blueprints/workers.py). */
export const WORKER_TYPES = ["job", "job-kind", "worker"] as const;

/** The fields of each that this page and the workers read and write. A type with the right name but not these is something else. */
export const WORKER_FIELDS: Record<(typeof WORKER_TYPES)[number], string[]> = {
  job: ["kind", "args", "status", "result", "log"],
  "job-kind": ["kind", "mode", "image", "timeout_seconds"],
  worker: ["role", "host", "last_seen", "kinds"],
};

export interface TypeShape {
  slug: string;
  schemaJson?: Record<string, unknown>;
}

const fieldKeys = (t: TypeShape): string[] =>
  ((t.schemaJson?.fields as { key?: string }[] | undefined) ?? []).map((f) => f.key ?? "");

/** The record types this workspace lacks (by slug), and the ones it has under the same name but without the fields workers need. */
export function workerSetup(types: TypeShape[]): { missing: string[]; misfit: { slug: string; lacks: string[] }[] } {
  const missing: string[] = [];
  const misfit: { slug: string; lacks: string[] }[] = [];
  for (const slug of WORKER_TYPES) {
    const found = types.find((t) => t.slug === slug);
    if (!found) {
      missing.push(slug);
      continue;
    }
    const have = fieldKeys(found);
    const lacks = WORKER_FIELDS[slug].filter((key) => !have.includes(key));
    if (lacks.length) misfit.push({ slug, lacks });
  }
  return { missing, misfit };
}

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
  /** where the finished work can be opened or played, when the job's result holds a link */
  resultUrl: string;
  queuedAgo: number | null;
  /** claimed or running for longer than its kind allows: the dispatcher is about to fail it, or has not noticed */
  stuck: boolean;
  /** queued, and nothing registered for its kind: it will fail as soon as a dispatcher looks */
  unknownKind: boolean;
}

export interface WorkerView {
  /** the heartbeat record's id, so a worker that stopped can be removed from the page */
  id: string;
  name: string;
  role: string;
  lastSeenAgo: number | null;
  healthy: boolean;
  status: string;
  currentJob: string;
  modes: string;
  tags: string;
  kinds: string[];
  jobsDone: number | null;
}

export interface Capability {
  kind: string;
  description: string;
  inputs: { name: string; type: string; required: boolean; description: string; accepts: string[] }[];
  accepts: string[];
  produces: string[];
  needs: string[];
  /** the live workers that offer it (a runner that has it, or a dispatcher that can launch it) */
  offeredBy: string[];
}

export interface WorkersView {
  counts: Record<string, number>;
  jobs: JobView[];
  kinds: { kind: string; mode: string; image: string; url: string; timeoutSeconds: number; notes: string }[];
  workers: WorkerView[];
  /** every kind any worker offers or any job-kind record names, with its contract and who can do it now */
  capabilities: Capability[];
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

  const jobViews: JobView[] = jobs.map((row) => {
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
      resultUrl: /^https?:\/\//.test(text(field(row, "url"))) ? text(field(row, "url")) : "",
      queuedAgo: seconds(row.createdAt, now),
      stuck: (status === "claimed" || status === "running") && sinceClaim !== null && sinceClaim > limit,
      unknownKind: status === "queued" && !allowed.has(kind),
    };
  });

  const counts: Record<string, number> = Object.fromEntries(STATUSES.map((s) => [s, 0]));
  for (const job of jobViews) counts[job.status] = (counts[job.status] ?? 0) + 1;

  const list = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
  const offered = (row: RecordRow): Record<string, unknown>[] => {
    const raw = field(row, "kinds");
    return Array.isArray(raw) ? raw.filter((k): k is Record<string, unknown> => typeof k === "object" && k !== null) : [];
  };
  const workerViews: WorkerView[] = workers
    .map((row) => {
      const ago = seconds(field(row, "last_seen"), now);
      const done = field(row, "jobs_done") ?? field(row, "jobs_started");
      return {
        id: row.id,
        name: text(field(row, "host")) || row.title,
        role: text(field(row, "role")) || "worker",
        lastSeenAgo: ago,
        healthy: ago !== null && ago <= SEEN_RECENTLY_SECONDS,
        status: text(field(row, "status")) || "idle",
        currentJob: text(field(row, "current_job")),
        modes: text(field(row, "modes")),
        tags: text(field(row, "tags")),
        kinds: offered(row).map((k) => text(k.kind)).filter(Boolean),
        jobsDone: typeof done === "number" ? done : null,
      };
    })
    .sort((a, b) => (a.lastSeenAgo ?? Infinity) - (b.lastSeenAgo ?? Infinity));

  // A kind's contract is whatever a worker advertised; a job-kind record no worker has advertised still lists, with nobody offering it.
  const contracts = new Map<string, Record<string, unknown>>();
  for (const row of workers) for (const k of offered(row)) if (text(k.kind) && !contracts.has(text(k.kind))) contracts.set(text(k.kind), k);
  const names = new Set<string>([...contracts.keys(), ...kinds.map((k) => k.kind).filter(Boolean)]);
  const capabilities: Capability[] = [...names].sort().map((kind) => {
    const c = contracts.get(kind) ?? {};
    const inputs = typeof c.inputs === "object" && c.inputs !== null ? Object.entries(c.inputs as Record<string, Record<string, unknown>>) : [];
    return {
      kind,
      description: text(c.description),
      inputs: inputs.map(([name, spec]) => ({ name, type: text(spec?.type) || "string", required: spec?.required !== false, description: text(spec?.description), accepts: list(spec?.accepts) })),
      accepts: list(c.accepts),
      produces: list(c.produces),
      needs: list(c.needs),
      offeredBy: workerViews.filter((w) => w.healthy && w.kinds.includes(kind)).map((w) => w.name),
    };
  });

  const warnings: string[] = [];
  const live = workerViews.filter((w) => w.healthy);
  if (!workerViews.length) warnings.push("No dispatcher or runner has reported yet. Start one with `python -m marvin_worker work` (a runner) or `dispatch` (see the marvin-worker README).");
  else if (!live.length && counts.queued > 0) warnings.push(`${counts.queued} job${counts.queued === 1 ? " is" : "s are"} queued and no worker has reported in the last ${SEEN_RECENTLY_SECONDS / 60} minutes. Nothing will start them until one is running.`);
  // A live worker that has not advertised its kinds (an older dispatcher) might offer anything: only say a kind is uncovered when every live worker has listed its own.
  if (live.length && live.every((w) => w.kinds.length > 0)) {
    const offeredNow = new Set(live.flatMap((w) => w.kinds));
    const waiting = new Map<string, number>();
    for (const job of jobViews) if (job.status === "queued" && job.kind && !job.unknownKind && !offeredNow.has(job.kind)) waiting.set(job.kind, (waiting.get(job.kind) ?? 0) + 1);
    for (const [kind, n] of waiting) warnings.push(`${n} queued job${n === 1 ? " asks" : "s ask"} for ${kind}, and no running worker offers it.`);
  }
  const stuck = jobViews.filter((j) => j.stuck).length;
  if (stuck) warnings.push(`${stuck} job${stuck === 1 ? " has" : "s have"} run past the time allowed without an outcome.`);
  const unknown = jobViews.filter((j) => j.unknownKind).length;
  if (unknown) warnings.push(`${unknown} queued job${unknown === 1 ? " asks" : "s ask"} for a kind nobody registered: add a job kind for it.`);

  return { counts, jobs: jobViews, kinds, workers: workerViews, capabilities, warnings };
}

/** How many things on the Workers page need a look, for the count on the Settings tab: jobs that failed in the last day, jobs past
 *  their time, jobs asking for a kind nobody registered, and queued jobs when workers have reported before but none is running now.
 *  Nothing counts in a workspace that has never used workers (no jobs, no worker records). */
export function needsLook(view: WorkersView, withinSeconds: number = 86400): number {
  const failed = view.jobs.filter((j) => j.status === "failed" && (j.queuedAgo ?? Infinity) <= withinSeconds).length;
  const stuck = view.jobs.filter((j) => j.stuck).length;
  const unknown = view.jobs.filter((j) => j.unknownKind).length;
  const unattended = view.workers.length > 0 && !view.workers.some((w) => w.healthy) ? (view.counts.queued ?? 0) : 0;
  return failed + stuck + unknown + unattended;
}

/** "5 s", "3 min", "2 h", "4 d": how long ago, short. */
export function ago(secs: number | null): string {
  if (secs === null) return "never";
  if (secs < 90) return `${secs} s`;
  if (secs < 5400) return `${Math.round(secs / 60)} min`;
  if (secs < 129600) return `${Math.round(secs / 3600)} h`;
  return `${Math.round(secs / 86400)} d`;
}
