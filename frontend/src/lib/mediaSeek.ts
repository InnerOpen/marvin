// An asset page's player and the times that move it (browser only; the arithmetic is in mediaTime.ts). The page marks its <audio> or
// <video> `data-seek-player`. Opened with `?t=65` (or `#t=1:05`), the player is scrolled into view and cued there once it knows its
// length, but left paused: a browser refuses to start sound nobody asked for. A `data-seek-to` button (a transcript's `[0:01:05]`)
// cues it there and plays, since a click is the asking.

import { clampTime, startTimeFrom } from "./mediaTime.ts";

/** Move `player` to `seconds` now if it knows its length, else as soon as it does (the event may already have fired by now). */
function cue(player: HTMLMediaElement, seconds: number): void {
  const go = () => {
    player.currentTime = clampTime(seconds, player.duration);
  };
  if (player.readyState >= HTMLMediaElement.HAVE_METADATA) go();
  else player.addEventListener("loadedmetadata", go, { once: true });
}

export function wireMediaSeek(doc: Document = document): void {
  const player = doc.querySelector<HTMLMediaElement>("[data-seek-player]");
  if (!player) return;

  const start = startTimeFrom(location);
  if (start !== null) {
    if (player.preload === "none") player.preload = "metadata";
    cue(player, start);
    player.scrollIntoView({ block: "center" });
  }

  doc.addEventListener("click", (event) => {
    const button = (event.target as Element | null)?.closest<HTMLElement>("[data-seek-to]");
    if (!button) return;
    const seconds = Number(button.dataset.seekTo);
    if (!Number.isFinite(seconds)) return;
    cue(player, seconds);
    player.scrollIntoView({ block: "nearest" });
    void player.play().catch(() => {});
  });
}
