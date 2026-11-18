/**
 * Dragging a line on the Timeline to nudge it: the page's glue around the pure maths in timeline.ts (`nudgeAfterDrag`, `relaid`). A line block
 * in a lane that names a nudge field moves left or right under the mouse (snapping to NUDGE_SNAP, shift for free), the lines after it in its beat
 * follow, and on drop the line's nudge is saved: the entry is read and sent back whole, because saving an entry replaces its fields. The page
 * then reloads at the same place, so every beat is timed again. A small ↺ beside a nudged line puts it back where it falls.
 *
 * Sounds move the same way. A sound the item places itself (a beat's `sounds`: `at` seconds into it) gets a new `at`; a sound a cue on a word
 * plays gets a `nudge` on that cue (seconds after, or before, its word), and a ↺ that removes it. Only that one entry of the item's list changes.
 */
import { fetchApi } from "@/lib/api/client";
import { atAfterDrag, type LineTiming, nudgeAfterDrag, relaid, withListEntry } from "@/lib/timeline";

/** One item's timed pieces, as the page hands them over: what `relaid` needs to lay them again while one moves. */
export interface DragItem {
  clock: number;
  timing: { lead: number; gap: number; tail: number };
  lines: (LineTiming & { id: string; natural: number; start: number })[];
}

/** What a draggable piece carries: its item and the field its nudge is saved in. */
interface DragOf {
  item: string;
  field: string;
}

/** A moved piece must travel this far (px) before it is a drag and not a click that opens it. */
const DRAG_PX = 4;
const SCROLL_KEY = "tl-scroll";

const words = (nudge: number) =>
  nudge === 0
    ? "back where it falls"
    : `nudged ${nudge > 0 ? "+" : "−"}${Math.abs(nudge).toFixed(3).replace(/0$/, "")} s`;

/** Save a line's nudge: read the entry, change that one key (0 clears it), send it all back. */
export async function saveNudge(id: string, field: string, nudge: number): Promise<string> {
  const path = `/api/platform/entries/${encodeURIComponent(id)}`;
  const entry = await fetchApi<{ title: string; slug: string; dataJson?: Record<string, unknown> }>(path);
  const data = { ...(entry.dataJson ?? {}) };
  if (nudge === 0) delete data[field];
  else data[field] = nudge;
  await fetchApi(path, {
    method: "PATCH",
    body: JSON.stringify({ title: entry.title, slug: entry.slug, dataJson: data }),
  });
  return entry.title;
}

/** Reload the page where it is: the scroll of each track's box and of the page, put back once the zoom is restored. */
function reloadInPlace(root: HTMLElement) {
  const boxes = [...root.querySelectorAll<HTMLElement>("[data-scroll]")].map((b) => b.scrollLeft);
  try {
    sessionStorage.setItem(
      SCROLL_KEY,
      JSON.stringify({ path: location.pathname + location.search, boxes, y: window.scrollY }),
    );
  } catch {
    /* a private window comes back at the start, nothing more */
  }
  location.reload();
}

function restoreScroll(root: HTMLElement) {
  let kept: { path: string; boxes: number[]; y: number } | null = null;
  try {
    kept = JSON.parse(sessionStorage.getItem(SCROLL_KEY) || "null");
    sessionStorage.removeItem(SCROLL_KEY);
  } catch {
    return;
  }
  if (!kept || kept.path !== location.pathname + location.search) return;
  const { boxes, y } = kept;
  requestAnimationFrame(() =>
    requestAnimationFrame(() => {
      for (const [i, b] of [...root.querySelectorAll<HTMLElement>("[data-scroll]")].entries())
        b.scrollLeft = boxes[i] ?? 0;
      window.scrollTo(0, y);
    }),
  );
}

/** What a draggable sound carries: the item and list entry it is (`withListEntry`), what moving it writes, and where it is now. */
interface SoundDrag {
  /** `at`: a placed sound's offset in its item; `nudge`: a cue sound's shift from its word. */
  kind: "at" | "nudge";
  item: string;
  field: string;
  index: number;
  refKey: string;
  ref: string;
  key: string;
  /** Where the block starts on the film now, where its item's sound starts, its `at` (kind at) or its un-nudged place and nudge (kind nudge). */
  start: number;
  clock: number;
  at: number;
  natural: number;
  nudge: number;
}

/** Write one key of one entry of an item's JSON list (undefined removes it): the item is read and sent back whole. */
export async function saveListEntry(
  d: Pick<SoundDrag, "item" | "field" | "index" | "refKey" | "ref" | "key">,
  value: number | undefined,
): Promise<string> {
  const path = `/api/platform/entries/${encodeURIComponent(d.item)}`;
  const entry = await fetchApi<{ title: string; slug: string; dataJson?: Record<string, unknown> }>(path);
  const data = withListEntry(entry.dataJson ?? {}, d.field, d.index, d.refKey, d.ref, d.key, value);
  if (!data) throw new Error(`${entry.title} has changed since this page was drawn: reload it and try again`);
  await fetchApi(path, {
    method: "PATCH",
    body: JSON.stringify({ title: entry.title, slug: entry.slug, dataJson: data }),
  });
  return entry.title;
}

/**
 * The gesture every draggable block shares: a press that moves DRAG_PX is a drag (else a click, which opens the block as before); the mouse or a
 * pen only (a finger scrolls the box; ctrl or cmd-click opens it in a tab); Escape puts it back; the click after a drag is swallowed. `move` gets
 * the seconds dragged and whether shift is held and returns the label to show; `drop` saves (false when it failed: the block is put back).
 */
function dragGesture(
  el: HTMLElement,
  move: (seconds: number, free: boolean) => string,
  drop: () => Promise<boolean>,
  putBack: () => void,
): void {
  let from: { x: number; perSecond: number } | null = null;
  let moved = false;
  const swallowClick = () => el.addEventListener("click", (c) => c.preventDefault(), { once: true, capture: true });
  const reset = () => {
    putBack();
    el.classList.remove("is-dragging");
    delete el.dataset.nudgeTip;
    document.removeEventListener("keydown", onKey);
    from = null;
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key !== "Escape" || !from) return;
    swallowClick(); // letting go after Escape does not open it
    reset();
  };
  el.draggable = false;
  el.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || e.pointerType === "touch" || e.ctrlKey || e.metaKey) return;
    const box = el.closest<HTMLElement>("[data-track]");
    const inner = el.closest<HTMLElement>(".tl-inner");
    const seconds = Number(box?.dataset.seconds || "0");
    if (!box || !inner || !(seconds > 0) || inner.clientWidth <= 0) return;
    from = { x: e.clientX, perSecond: inner.clientWidth / seconds };
    moved = false;
  });
  el.addEventListener("pointermove", (e) => {
    if (!from) return;
    const dx = e.clientX - from.x;
    if (!moved && Math.abs(dx) < DRAG_PX) return;
    if (!moved) {
      moved = true;
      el.setPointerCapture(e.pointerId);
      el.classList.add("is-dragging");
      document.addEventListener("keydown", onKey);
    }
    el.dataset.nudgeTip = move(dx / from.perSecond, e.shiftKey);
  });
  el.addEventListener("pointerup", async () => {
    if (!from) return;
    if (!moved) {
      from = null; // a click: it opens, as before
      return;
    }
    swallowClick();
    from = null;
    document.removeEventListener("keydown", onKey);
    if (!(await drop())) reset();
  });
  el.addEventListener("pointercancel", () => from && reset());
}

/** Where a block of a track is drawn: its start as a share of the track it sits in. */
const leftIn = (el: HTMLElement, start: number) => {
  const box = el.closest<HTMLElement>("[data-track]");
  const [trackStart, trackSeconds] = [Number(box?.dataset.start || "0"), Number(box?.dataset.seconds || "1")];
  return `${((start - trackStart) / trackSeconds) * 100}%`;
};

/** Wire every draggable line (`[data-drag]`), sound (`[data-drag-sound]`) and ↺ (`[data-unnudge]`, `[data-unnudge-cue]`) under `root`; `say`
 * shows a line of status. */
export function wireLineDrags(root: HTMLElement, items: Record<string, DragItem>, say: (text: string) => void): void {
  restoreScroll(root);
  const saving = async (what: string, write: () => Promise<string>, done: (title: string) => string) => {
    say(`Saving the ${what}…`);
    try {
      say(`${done(await write())} Timing the beats again…`);
      reloadInPlace(root);
      return true;
    } catch (e) {
      say(`Could not save the ${what}: ${e instanceof Error ? e.message : "nothing changed"}`);
      return false;
    }
  };
  const saveLine = (id: string, field: string, nudge: number) =>
    saving(
      "nudge",
      () => saveNudge(id, field, nudge),
      (title) => `${title}: ${words(nudge)}.`,
    );
  for (const button of root.querySelectorAll<HTMLButtonElement>("[data-unnudge]")) {
    button.addEventListener("click", async () => {
      const { id, field } = JSON.parse(button.dataset.unnudge || "{}") as { id: string; field: string };
      button.disabled = true;
      if (!(await saveLine(id, field, 0))) button.disabled = false;
    });
  }
  for (const button of root.querySelectorAll<HTMLButtonElement>("[data-unnudge-cue]")) {
    button.addEventListener("click", async () => {
      const d = JSON.parse(button.dataset.unnudgeCue || "{}") as SoundDrag;
      button.disabled = true;
      if (
        !(await saving(
          "nudge",
          () => saveListEntry(d, undefined),
          (title) => `${title}: the cue's sound is back on its word.`,
        ))
      )
        button.disabled = false;
    });
  }
  for (const el of root.querySelectorAll<HTMLElement>("[data-drag]")) {
    const of = JSON.parse(el.dataset.drag || "{}") as DragOf;
    const item = items[of.item];
    const index = item?.lines.findIndex((l) => l.id === el.dataset.piece) ?? -1;
    if (!item || index < 0) continue;
    const line = item.lines[index];
    let nudge = line.nudge;
    const place = (starts: number[]) =>
      item.lines.forEach((l, i) => {
        const e = root.querySelector<HTMLElement>(`[data-piece="${CSS.escape(l.id)}"]`);
        if (e) e.style.left = leftIn(e, starts[i]);
      });
    dragGesture(
      el,
      (seconds, free) => {
        nudge = nudgeAfterDrag(line.natural, line.start + seconds, free);
        place(relaid(item.lines, item.timing, item.clock, index, nudge));
        return words(nudge);
      },
      async () => Math.abs(nudge - line.nudge) > 1e-9 && saveLine(line.id, of.field, nudge),
      () => {
        nudge = line.nudge;
        place(item.lines.map((l) => l.start));
      },
    );
  }
  for (const el of root.querySelectorAll<HTMLElement>("[data-drag-sound]")) {
    const d = JSON.parse(el.dataset.dragSound || "{}") as SoundDrag;
    let value = d.kind === "at" ? d.at : d.nudge;
    dragGesture(
      el,
      (seconds, free) => {
        if (d.kind === "at") {
          value = atAfterDrag(d.at, seconds, free, -d.clock); // before its beat, as far back as the film's start
          el.style.left = leftIn(el, d.clock + value);
          return `at ${value.toFixed(3).replace(/0$/, "")} s`;
        }
        value = nudgeAfterDrag(d.natural, d.start + seconds, free);
        el.style.left = leftIn(el, Math.max(d.natural + value, d.clock));
        return words(value);
      },
      async () => {
        if (Math.abs(value - (d.kind === "at" ? d.at : d.nudge)) <= 1e-9) return false;
        const written = d.kind === "nudge" && value === 0 ? undefined : value;
        return saving(
          d.kind === "at" ? "sound's place" : "nudge",
          () => saveListEntry(d, written),
          (title) => `${title}: ${d.kind === "at" ? `at ${value} s` : words(value)}.`,
        );
      },
      () => {
        value = d.kind === "at" ? d.at : d.nudge;
        el.style.left = leftIn(el, d.start);
      },
    );
  }
}
