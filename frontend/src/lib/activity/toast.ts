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
