/**
 * Marvin — agent runs that outlive the page that sent them.
 *
 * Bubble agent conversations live in server threads (the same ones the Ask page lists), and a run
 * keeps going server-side when the page awaiting it is gone. So before each agent call the bubble
 * writes a "pending run" marker to sessionStorage, and the next page load recovers the answer: the
 * run's progress record (keyed by the client-minted run id) names its thread and execution, and the
 * thread holds the stored turn. See recoverPendingRun.
 *
 * Kept free of the DOM and of runtime imports (types only) so it runs under `node --test`
 * (pending.test.ts); storage and network are passed in.
 */

import type { RunProgress, ThreadDetail, ThreadMessage } from "@/lib/api/aiAgents";

const PENDING_KEY = "marvin.pending";
/** The bubble's current thread per agent — a thread belongs to one agent, so `/use` switches threads too. */
const THREADS_KEY = "marvin.threads";
const ASK_PAGE_PATH = "/workspace/settings/ai-ask";

export const PENDING_POLL_MS = 1500;
/** Past this, stop waiting: agent runs are capped at a dozen tool steps, so this is far beyond normal. */
export const PENDING_RUN_TIMEOUT_MS = 10 * 60_000;
/**
 * How long the run may be unknown to the progress endpoint before we call it lost: covers the moment
 * before the server registers it; after that, unknown means a restart (or the request never left).
 */
export const PROGRESS_MISSING_GRACE_MS = 30_000;

export interface PendingRun {
  clientRunId: string;
  /** Agent slug the run went to. */
  agent: string;
  message: string;
  /** Epoch ms, client clock. */
  sentAt: number;
  /** Known up front when continuing a thread; learned from progress for a first message. */
  threadId?: string;
  executionId?: string;
}

export type Recovery =
  | { kind: "wait" }
  | { kind: "reply"; message: ThreadMessage; threadId: string }
  | { kind: "parked"; threadId: string; tools: string[] }
  | { kind: "failed"; error: string; threadId?: string }
  | { kind: "lost"; timedOut: boolean; threadId?: string }
  | { kind: "cancelled" };

type KV = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function readJson<T>(store: KV, key: string): T | null {
  try {
    return JSON.parse(store.getItem(key) || "null") as T | null;
  } catch {
    return null;
  }
}

function writeJson(store: KV, key: string, value: unknown): void {
  try {
    store.setItem(key, JSON.stringify(value));
  } catch {
    /* quota or disabled storage — recovery degrades to this page only */
  }
}

function remove(store: KV, key: string): void {
  try {
    store.removeItem(key);
  } catch {
    /* ignore */
  }
}

export function threadFor(agent: string, store: KV = sessionStorage): string | undefined {
  return readJson<Record<string, string>>(store, THREADS_KEY)?.[agent] || undefined;
}

export function rememberThread(agent: string, threadId: string | null | undefined, store: KV = sessionStorage): void {
  const threads = readJson<Record<string, string>>(store, THREADS_KEY) ?? {};
  if (threadId) threads[agent] = threadId;
  else delete threads[agent];
  writeJson(store, THREADS_KEY, threads);
}

export function loadPending(store: KV = sessionStorage): PendingRun | null {
  const run = readJson<PendingRun>(store, PENDING_KEY);
  return run?.clientRunId && run.agent ? run : null;
}

export function savePending(run: PendingRun, store: KV = sessionStorage): void {
  writeJson(store, PENDING_KEY, run);
}

export function clearPending(store: KV = sessionStorage): void {
  remove(store, PENDING_KEY);
}

/** Whether `run` is still the tab's pending run — false once "Clear" (or a newer run) replaced it. */
export function ownsPending(run: PendingRun, store: KV = sessionStorage): boolean {
  return loadPending(store)?.clientRunId === run.clientRunId;
}

/** "Clear": the next message opens a new thread, and nothing waits on the old one. */
export function forgetConversation(store: KV = sessionStorage): void {
  remove(store, THREADS_KEY);
  remove(store, PENDING_KEY);
}

/** A v4 UUID for `clientRunId` (the server only tracks runs keyed by a real UUID). */
export function newRunId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  // randomUUID needs a secure context; over plain http, build the same thing from random bytes.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // RFC 4122 variant
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** The Ask page, opened on `threadId` when there is one. */
export function askThreadHref(threadId?: string): string {
  return threadId ? `${ASK_PAGE_PATH}?thread=${encodeURIComponent(threadId)}` : ASK_PAGE_PATH;
}

/** `run` with whatever ids `progress` adds; the same object when it adds nothing. */
export function withProgress(run: PendingRun, progress: RunProgress | null): PendingRun {
  const threadId = run.threadId ?? progress?.threadId ?? undefined;
  const executionId = run.executionId ?? progress?.executionId ?? undefined;
  return threadId === run.threadId && executionId === run.executionId ? run : { ...run, threadId, executionId };
}

/**
 * The assistant turn answering `run`: the one stored with its execution id; failing that (the
 * progress record expired before we learned the id), the turn right after the latest user turn
 * with the same text.
 */
export function findReply(thread: ThreadDetail, run: PendingRun): ThreadMessage | null {
  const messages = [...(thread.messages ?? [])].sort((a, b) => a.seq - b.seq);
  if (run.executionId) {
    return messages.find((m) => m.role === "assistant" && m.executionId === run.executionId) ?? null;
  }
  for (let i = messages.length - 2; i >= 0; i--) {
    if (messages[i].role === "user" && messages[i].content === run.message) {
      return messages[i + 1].role === "assistant" ? messages[i + 1] : null;
    }
  }
  return null;
}

function isParkedOn(thread: ThreadDetail, run: PendingRun): boolean {
  const last = [...(thread.messages ?? [])].sort((a, b) => a.seq - b.seq).at(-1);
  return thread.status === "awaiting_approval" && last?.role === "user" && last.content === run.message;
}

function parkedTools(progress: RunProgress): string[] {
  const ev = [...progress.events].reverse().find((e) => e.type === "awaiting_approval");
  return (ev?.calls ?? []).map((c) => c.tool);
}

export interface Observation {
  now: number;
  /** null = the progress endpoint doesn't know the run (404) or couldn't be reached. */
  progress: RunProgress | null;
  /** The run's thread, when its id is known and it was fetched this round. */
  thread: ThreadDetail | null;
  /** When the current streak of unknown-run answers began; null while the run is known. */
  missingSince: number | null;
}

/** One recovery decision from what the server says right now. Pure. */
export function assess(run: PendingRun, obs: Observation): Recovery {
  const { progress, thread, now, missingSince } = obs;
  const threadId = run.threadId ?? progress?.threadId ?? undefined;
  if (progress?.status === "failed") return { kind: "failed", error: progress.error || "the run failed", threadId };
  if (thread) {
    const reply = findReply(thread, run);
    if (reply) return { kind: "reply", message: reply, threadId: thread.id };
    if (isParkedOn(thread, run))
      return { kind: "parked", threadId: thread.id, tools: (thread.pending ?? []).map((c) => c.tool) };
  }
  if (progress?.status === "awaiting_approval" && threadId)
    return { kind: "parked", threadId, tools: parkedTools(progress) };
  if (now - run.sentAt > PENDING_RUN_TIMEOUT_MS) return { kind: "lost", timedOut: true, threadId };
  if (!progress && missingSince !== null && now - missingSince > PROGRESS_MISSING_GRACE_MS) {
    return { kind: "lost", timedOut: false, threadId };
  }
  return { kind: "wait" };
}

export interface RecoveryDeps {
  getRunProgress(id: string): Promise<RunProgress>;
  getThread(id: string): Promise<ThreadDetail>;
  sleep(ms: number): Promise<void>;
  now(): number;
  /** The run learned an id; persist it so a further navigation doesn't lose it. */
  onUpdate?(run: PendingRun): void;
  /** Every progress answer, as it arrives — e.g. the bubble character showing the agent at work. */
  onProgress?(progress: RunProgress): void;
  /** Checked each round — e.g. "Clear" was pressed. */
  isCancelled?(): boolean;
}

/**
 * Poll until the run's answer is in its thread, it failed or parked, or we give up. The thread is
 * fetched only once the run is no longer running (or unknown), not on every round.
 */
export async function recoverPendingRun(start: PendingRun, deps: RecoveryDeps): Promise<Recovery> {
  let run = start;
  let missingSince: number | null = null;
  for (;;) {
    if (deps.isCancelled?.()) return { kind: "cancelled" };
    const progress = await deps.getRunProgress(run.clientRunId).catch(() => null);
    if (progress) {
      missingSince = null;
      deps.onProgress?.(progress);
    } else missingSince ??= deps.now();
    const next = withProgress(run, progress);
    if (next !== run) {
      run = next;
      deps.onUpdate?.(run);
    }
    const thread =
      run.threadId && progress?.status !== "running" ? await deps.getThread(run.threadId).catch(() => null) : null;
    const verdict = assess(run, { progress, thread, now: deps.now(), missingSince });
    if (verdict.kind !== "wait") return verdict;
    await deps.sleep(PENDING_POLL_MS);
  }
}

/**
 * While the run's own request is in flight, learn its thread and execution ids from progress and
 * hand them to `onUpdate`, so a navigation mid-run still knows where the answer will land. Stops
 * once both are known — unless there's an `onProgress` to keep informed — or when the returned
 * function is called.
 */
export function learnWhileInFlight(
  start: PendingRun,
  deps: Pick<RecoveryDeps, "getRunProgress" | "sleep" | "onUpdate" | "onProgress">,
): () => void {
  let run = start;
  let stopped = false;
  void (async () => {
    while (!stopped && (deps.onProgress || !(run.threadId && run.executionId))) {
      await deps.sleep(PENDING_POLL_MS);
      if (stopped) break;
      const progress = await deps.getRunProgress(run.clientRunId).catch(() => null);
      if (stopped) break;
      if (progress) deps.onProgress?.(progress);
      const next = withProgress(run, progress);
      if (next !== run) {
        run = next;
        deps.onUpdate?.(run);
      }
    }
  })();
  return () => {
    stopped = true;
  };
}
