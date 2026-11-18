/**
 * Dragging a line on the Timeline to nudge it: the page's glue around the pure maths in timeline.ts (`nudgeAfterDrag`, `relaid`). A line block
 * in a lane that names a nudge field moves left or right under the mouse (snapping to NUDGE_SNAP, shift for free), the lines after it in its beat
 * follow, and on drop the line's nudge is saved: the entry is read and sent back whole, because saving an entry replaces its fields. The page
 * then reloads at the same place, so every beat is timed again. A small ↺ beside a nudged line puts it back where it falls.
 */
import { fetchApi } from "@/lib/api/client";
import { type LineTiming, nudgeAfterDrag, relaid } from "@/lib/timeline";

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

/** Wire every draggable line (`[data-drag]`) and every ↺ (`[data-unnudge]`) under `root`; `say` shows a line of status. */
export function wireLineDrags(root: HTMLElement, items: Record<string, DragItem>, say: (text: string) => void): void {
  restoreScroll(root);
  const save = async (id: string, field: string, nudge: number) => {
    say("Saving the nudge…");
    try {
      const title = await saveNudge(id, field, nudge);
      say(`${title}: ${words(nudge)}. Timing the beats again…`);
      reloadInPlace(root);
      return true;
    } catch (e) {
      say(`Could not save the nudge: ${e instanceof Error ? e.message : "the line did not change"}`);
      return false;
    }
  };
  for (const button of root.querySelectorAll<HTMLButtonElement>("[data-unnudge]")) {
    button.addEventListener("click", async () => {
      const { id, field } = JSON.parse(button.dataset.unnudge || "{}") as { id: string; field: string };
      button.disabled = true;
      if (!(await save(id, field, 0))) button.disabled = false;
    });
  }
  root.querySelectorAll<HTMLElement>("[data-drag]").forEach((el) => {
    const of = JSON.parse(el.dataset.drag || "{}") as DragOf;
    const item = items[of.item];
    const index = item?.lines.findIndex((l) => l.id === el.dataset.piece) ?? -1;
    if (!item || index < 0) return;
    const line = item.lines[index];
    el.draggable = false;
    let from: { x: number; perSecond: number; trackStart: number; trackSeconds: number } | null = null;
    let track = { start: 0, seconds: 1 }; // the track the line was last dragged in, to draw the lines back where they were
    let moved = false;
    let nudge = line.nudge;
    const els = () => item.lines.map((l) => root.querySelector<HTMLElement>(`[data-piece="${CSS.escape(l.id)}"]`));
    const place = (starts: number[]) =>
      els().forEach((e, i) => {
        if (e) e.style.left = `${((starts[i] - track.start) / track.seconds) * 100}%`;
      });
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || !from) return;
      el.addEventListener("click", (c) => c.preventDefault(), { once: true, capture: true }); // letting go after Escape does not open the line
      reset();
    };
    const reset = () => {
      place(item.lines.map((l) => l.start));
      el.classList.remove("is-dragging");
      delete el.dataset.nudgeTip;
      document.removeEventListener("keydown", onKey);
      from = null;
    };
    el.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || e.pointerType === "touch" || e.ctrlKey || e.metaKey) return; // a finger scrolls the box; a ctrl-click opens in a tab
      const box = el.closest<HTMLElement>("[data-track]");
      const inner = el.closest<HTMLElement>(".tl-inner");
      if (!box || !inner) return;
      const trackSeconds = Number(box.dataset.seconds || "0");
      if (!(trackSeconds > 0) || inner.clientWidth <= 0) return;
      from = {
        x: e.clientX,
        perSecond: inner.clientWidth / trackSeconds,
        trackStart: Number(box.dataset.start || "0"),
        trackSeconds,
      };
      track = { start: from.trackStart, seconds: trackSeconds };
      moved = false;
      nudge = line.nudge;
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
      nudge = nudgeAfterDrag(line.natural, line.start + dx / from.perSecond, e.shiftKey);
      place(relaid(item.lines, item.timing, item.clock, index, nudge));
      el.dataset.nudgeTip = words(nudge);
    });
    el.addEventListener("pointerup", async () => {
      if (!from) return;
      if (!moved) {
        from = null; // a click: it opens the line, as before
        return;
      }
      // the click that follows a drag must not open the line
      el.addEventListener("click", (c) => c.preventDefault(), { once: true, capture: true });
      const changed = Math.abs(nudge - line.nudge) > 1e-9;
      from = null;
      document.removeEventListener("keydown", onKey);
      if (!changed || !(await save(line.id, of.field, nudge))) reset();
    });
    el.addEventListener("pointercancel", () => from && reset());
  });
}
