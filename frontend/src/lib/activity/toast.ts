// Pure pieces of the activity toaster (components/ActivityToaster.astro), kept out of the component
// so they can be tested with plain `node --test` (see toast.test.mjs).

/** One content change a site rebuild covers, as GET /api/platform/events/feed lists it. */
export type RebuildChange = {
  label: string;
  event?: string | null;
  entityType?: string | null;
  entityId?: string | null;
};

export type ChangeList = {
  /** How many changes the rebuild covers — the request count when known, which counts repeats. */
  total: number;
  /** Newest first, each linked when there's a page for it. */
  items: { label: string; href: string | null }[];
  /** Covered but not listed: repeat edits of a listed item, or older ones past the list's cap. */
  more: number;
};

/** Where a change links to — an entry's page; other kinds have no single page worth opening. */
export function changeHref(change: RebuildChange): string | null {
  return change.entityType === "entry" && change.entityId
    ? `/workspace/entries/${encodeURIComponent(change.entityId)}`
    : null;
}

/** What a rebuild toast's disclosure shows, or null when the event lists no changes. */
export function summarizeChanges(
  changes: RebuildChange[] | null | undefined,
  requestCount?: number | null,
): ChangeList | null {
  if (!changes?.length) return null;
  const total = Math.max(requestCount ?? 0, changes.length);
  const items = [...changes].reverse().map((c) => ({ label: c.label, href: changeHref(c) }));
  return { total, items, more: total - changes.length };
}

export const changesLabel = (total: number) => `${total} change${total === 1 ? "" : "s"}`;
export const moreLabel = (more: number) => `and ${more} more (repeat or earlier edits)`;

// Resuming with almost nothing left would whisk the toast away the moment the pointer leaves it.
export const RESUME_MIN_MS = 1500;

export type DismissTimer = {
  /** Pause for `reason` (e.g. "pointer", "open"); stays paused until every reason is released. */
  hold(reason: string): void;
  release(reason: string): void;
  cancel(): void;
};

/** A toast's auto-dismiss countdown that pauses while anything holds it, then resumes where it left off. */
export function dismissTimer(ms: number, onExpire: () => void): DismissTimer {
  const holds = new Set<string>();
  let remaining = ms;
  let startedAt = 0;
  let handle: ReturnType<typeof setTimeout> | undefined;
  let done = false;

  const run = () => {
    startedAt = Date.now();
    handle = setTimeout(() => {
      done = true;
      onExpire();
    }, remaining);
  };
  run();

  return {
    hold(reason) {
      if (done) return;
      if (holds.size === 0 && handle !== undefined) {
        clearTimeout(handle);
        handle = undefined;
        remaining = Math.max(RESUME_MIN_MS, remaining - (Date.now() - startedAt));
      }
      holds.add(reason);
    },
    release(reason) {
      if (done || !holds.delete(reason) || holds.size > 0) return;
      run();
    },
    cancel() {
      done = true;
      if (handle !== undefined) clearTimeout(handle);
    },
  };
}

// ── In-place toasts: a "queued"/"running" toast that the event ending it updates ──────────────────

export type Tone = "ok" | "info" | "warn" | "err";
/** Tones that stay until dismissed (and show in "failures only"). */
export const STICKY_TONES: ReadonlySet<Tone> = new Set<Tone>(["warn", "err"]);

/** The rebuild goes out on the first scheduler tick after its max wait, then waits for a feed poll. */
export const QUEUED_GRACE_S = 120;
/** A run whose end never arrives (the process died mid-run) shouldn't say "running…" forever. */
export const RUNNING_CAP_MS = 15 * 60_000;

const SECONDS_SHOWN_BELOW = 120;
const MINUTES_SHOWN_BELOW = 120 * 60;

/** A window from the server's settings, worded for a toast: "45 s", "2 min", "3 h". */
export function formatDuration(seconds: number): string {
  if (seconds < SECONDS_SHOWN_BELOW) return `${Math.round(seconds)} s`;
  if (seconds < MINUTES_SHOWN_BELOW) return `${Math.round(seconds / 60)} min`;
  return `${Math.round(seconds / 3600)} h`;
}

/** The feed fields that pair a toast with the event ending it, and what that toast says. */
export type ProgressEvent = {
  eventType: string;
  messageTitle: string;
  messageBody?: string | null;
  workspaceId?: string | null;
  runId?: string | null;
  workflowName?: string | null;
  targetCount?: number | null;
  quietSeconds?: number | null;
  maxWaitSeconds?: number | null;
  requestCount?: number | null;
  changes?: RebuildChange[] | null;
};

/** The toast slot an event opens or ends: one per workspace for a rebuild, one per workflow run. */
export function toastKey(e: ProgressEvent): { key: string; opens: boolean } | null {
  const rebuild = e.workspaceId ? `rebuild:${e.workspaceId}` : null;
  const run = e.runId ? `run:${e.runId}` : null;
  switch (e.eventType) {
    case "site_rebuild_queued":
      return rebuild && { key: rebuild, opens: true };
    case "webhook_triggered":
      return rebuild && { key: rebuild, opens: false };
    case "automation_started":
      return run && { key: run, opens: true };
    case "automation_ran":
    case "automation_failed":
      return run && { key: run, opens: false };
    default:
      return null;
  }
}

/** show: a toast of its own; open: a pending toast under `key`; update: the pending one becomes this. */
export type ToastStep<E> = { event: E; key: string | null; action: "show" | "open" | "update" };

/**
 * How one poll's new events (oldest first) land, given which slots already hold a pending toast.
 * An opener whose end is in the same poll is dropped, so a fast run shows only its result.
 */
export function planToasts<E extends ProgressEvent>(events: E[], isOpen: (key: string) => boolean): ToastStep<E>[] {
  const endedLater = new Set<string>();
  const dropped = new Set<E>();
  for (const e of [...events].reverse()) {
    const slot = toastKey(e);
    if (!slot) continue;
    if (!slot.opens) endedLater.add(slot.key);
    else if (endedLater.has(slot.key)) dropped.add(e);
  }

  // Slots this poll opened (true) or ended (false), over what was pending before it.
  const opened = new Map<string, boolean>();
  const steps: ToastStep<E>[] = [];
  for (const e of events) {
    if (dropped.has(e)) continue;
    const slot = toastKey(e);
    if (!slot) {
      steps.push({ event: e, key: null, action: "show" });
      continue;
    }
    const pending = opened.get(slot.key) ?? isOpen(slot.key);
    opened.set(slot.key, slot.opens);
    if (slot.opens) steps.push({ event: e, key: slot.key, action: pending ? "update" : "open" });
    else steps.push({ event: e, key: pending ? slot.key : null, action: pending ? "update" : "show" });
  }
  return steps;
}

const entriesLabel = (n: number) => `${n} entr${n === 1 ? "y" : "ies"}`;

export type ToastView = {
  tone: Tone;
  label: string;
  text: string;
  /** A muted second line. */
  note: string | null;
  /** pending: until the event ending it arrives (capped at `capMs`); sticky: until dismissed. */
  lifetime: "pending" | "sticky" | "auto";
  capMs: number | null;
};

/**
 * What a toast says and how long it stays. `kind` is the event's entry in the toaster's KINDS;
 * `merged` is true when the event is updating a pending toast in place.
 */
export function toastView(e: ProgressEvent, kind: { tone: Tone; label: string }, merged = false): ToastView {
  const view: ToastView = {
    tone: kind.tone,
    label: kind.label,
    text: e.messageBody || e.messageTitle,
    note: null,
    lifetime: STICKY_TONES.has(kind.tone) ? "sticky" : "auto",
    capMs: null,
  };
  if (e.eventType === "site_rebuild_queued") {
    const quiet = e.quietSeconds;
    const maxWait = e.maxWaitSeconds;
    view.text =
      quiet == null ? "Site rebuild queued" : `Site rebuild queued — building in about ${formatDuration(quiet)}`;
    view.note =
      maxWait == null
        ? "More changes join this build"
        : `More changes join this build (sent at the latest ${formatDuration(maxWait)} after the first)`;
    view.lifetime = "pending";
    view.capMs = ((maxWait ?? 0) + QUEUED_GRACE_S) * 1000;
  } else if (e.eventType === "automation_started") {
    const name = e.workflowName || "workflow";
    const targets = e.targetCount == null ? "" : ` · ${entriesLabel(e.targetCount)}`;
    view.text = `Workflow '${name}' is running…${targets}`;
    view.lifetime = "pending";
    view.capMs = RUNNING_CAP_MS;
  } else if (e.eventType === "webhook_triggered" && merged) {
    // With a list, its "N changes ▾" toggle carries the count; without one, the text does.
    const total = Math.max(e.requestCount ?? 0, e.changes?.length ?? 0);
    view.text = e.changes?.length || !total ? "Site rebuild sent" : `Site rebuild sent — ${changesLabel(total)}`;
  }
  return view;
}

export type KeyedToasts<T> = {
  /** Hold `handle` under `key` until taken, or until `capMs` passes (then `onExpire` gets it). */
  open(key: string, handle: T, capMs: number): void;
  /** Remove and return the pending toast under `key`, its cap cancelled. */
  take(key: string): T | undefined;
  has(key: string): boolean;
};

/** The toaster's pending toasts by slot, each with a cap so none outlives what it's waiting for. */
export function keyedToasts<T>(onExpire: (handle: T) => void): KeyedToasts<T> {
  const slots = new Map<string, { handle: T; timer: ReturnType<typeof setTimeout> }>();
  const take = (key: string) => {
    const slot = slots.get(key);
    if (!slot) return undefined;
    clearTimeout(slot.timer);
    slots.delete(key);
    return slot.handle;
  };
  return {
    open(key, handle, capMs) {
      take(key);
      const timer = setTimeout(() => {
        slots.delete(key);
        onExpire(handle);
      }, capMs);
      slots.set(key, { handle, timer });
    },
    take,
    has: (key) => slots.has(key),
  };
}
