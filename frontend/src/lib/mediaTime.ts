// Moments in a sound or video: the time an asset page is opened at (`?t=65`, `#t=1:05`), the `[h:mm:ss]` markers a timestamped
// transcript leads each line with (Marvin Media writes `[0:01:05] words`), and a transcript's text as HTML whose markers are buttons
// that play from there. The backend twin is src/marvin/services/media_time.py. Pure, so `npm test` covers it (mediaTime.test.mjs).

import { formatLength } from "./assetRecording.ts";

/** A transcript's time marker, `[h:mm:ss]` (hours may be 0 or run past 9). */
const MARKER = /\[(\d+):([0-5]\d):([0-5]\d)\]/g;

/** A time as someone types it: `65`, `65.5`, `65s`, `1:05`, `0:01:05`, `1m5s`, `1h2m3s`. Seconds, or null for anything else (a
 * negative number, minutes or seconds of 60 or more after a colon, words). */
export function parseMediaTime(raw: string | null | undefined): number | null {
  const s = (raw ?? "").trim().toLowerCase();
  if (!s) return null;
  let seconds: number | null = null;
  const plain = s.match(/^(\d+(?:\.\d+)?)s?$/);
  const clock = s.match(/^(?:(\d+):)?(\d+):(\d{1,2}(?:\.\d+)?)$/);
  const units = s.match(/^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?$/);
  if (plain) seconds = Number(plain[1]);
  else if (clock) {
    const [h, m, sec] = [Number(clock[1] ?? 0), Number(clock[2]), Number(clock[3])];
    if (sec >= 60 || (clock[1] !== undefined && m >= 60)) return null;
    seconds = h * 3600 + m * 60 + sec;
  } else if (units && (units[1] || units[2] || units[3])) {
    seconds = Number(units[1] ?? 0) * 3600 + Number(units[2] ?? 0) * 60 + Number(units[3] ?? 0);
  }
  return seconds !== null && Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

/** The time a page was opened at: its `t` query parameter, else a `#t=` in its hash; null when neither holds a time. */
export function startTimeFrom(where: { search?: string; hash?: string }): number | null {
  const fromQuery = parseMediaTime(new URLSearchParams(where.search ?? "").get("t"));
  if (fromQuery !== null) return fromQuery;
  return parseMediaTime(new URLSearchParams((where.hash ?? "").replace(/^#/, "")).get("t"));
}

/** `seconds` kept inside the media: never below 0, and not past its end when its length is known (a browser recording may report
 * Infinity or NaN until it has played through, and then it is left to the browser). */
export function clampTime(seconds: number, duration: number): number {
  const t = Math.max(0, seconds);
  return Number.isFinite(duration) && duration > 0 ? Math.min(t, duration) : t;
}

/** Seconds of a marker's parts. */
const markerSeconds = (h: string, m: string, s: string) => Number(h) * 3600 + Number(m) * 60 + Number(s);

/** Seconds of the first `[h:mm:ss]` in `text`, or null when it holds none. */
export function firstMarkerSeconds(text: string | null | undefined): number | null {
  const m = (text ?? "").match(new RegExp(MARKER.source));
  return m ? markerSeconds(m[1], m[2], m[3]) : null;
}

/** Whether `text` holds at least one `[h:mm:ss]` marker. */
export function hasTimeMarkers(text: string | null | undefined): boolean {
  return firstMarkerSeconds(text) !== null;
}

export type TimedPart = { text: string } | { marker: string; seconds: number };

/** `text` cut into its words and its markers, in order. */
export function timedParts(text: string): TimedPart[] {
  const out: TimedPart[] = [];
  let at = 0;
  for (const m of text.matchAll(MARKER)) {
    const start = m.index ?? 0;
    if (start > at) out.push({ text: text.slice(at, start) });
    out.push({ marker: m[0], seconds: markerSeconds(m[1], m[2], m[3]) });
    at = start + m[0].length;
  }
  if (at < text.length) out.push({ text: text.slice(at) });
  return out;
}

/** Text made safe to put in HTML, attribute values included. */
export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** `text` as HTML with each marker a button that plays from its time (`data-seek-to`, which mediaSeek.ts wires); everything else is
 * escaped, so a transcript can never put markup on the page. */
export function timedTextHtml(text: string): string {
  return timedParts(text)
    .map((p) =>
      "marker" in p
        ? `<button type="button" class="seek-mark" data-seek-to="${p.seconds}" aria-label="Play from ${formatLength(p.seconds)}">${escapeHtml(p.marker)}</button>`
        : escapeHtml(p.text),
    )
    .join("");
}

/** An asset's page: its view page opened at `seconds` when there is a time, else the page an asset link has always opened. */
export function assetHref(id: string, seconds?: number | null): string {
  const enc = encodeURIComponent(id);
  return typeof seconds === "number" && Number.isFinite(seconds) && seconds >= 0
    ? `/workspace/assets/${enc}/view?t=${Math.floor(seconds)}`
    : `/workspace/assets/${enc}`;
}
