/**
 * Bridges `<input type="datetime-local">` and the API's UTC timestamps.
 *
 * A datetime-local value has no zone: the browser shows and returns wall-clock time in the
 * viewer's zone, and the server receiving the form can't know which zone that was. So the page
 * converts in the browser, where the zone is known — UTC → local to fill the picker, local → UTC
 * ISO into a hidden input that the form actually posts. Kept free of the DOM so it runs under
 * `node --test` (localDatetime.test.mjs).
 */

const pad = (n: number): string => String(n).padStart(2, "0");

/** A UTC timestamp as a datetime-local value ("YYYY-MM-DDTHH:mm") in the viewer's zone; "" if unset/invalid. */
export function toDatetimeLocalValue(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** A datetime-local value (the viewer's wall-clock time) as a UTC ISO string; "" when cleared/invalid. */
export function fromDatetimeLocalValue(value: string | null | undefined): string {
  if (!value) return "";
  // A date-time string without an offset is parsed as local time (ECMA-262 Date.parse).
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "" : d.toISOString();
}

/** A UTC timestamp for display in the viewer's locale and zone, e.g. "Oct 3, 2026, 2:30 PM"; "" if unset/invalid. */
export function formatLocalDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** Whether a UTC timestamp is at or before `now` — e.g. an expiration date that blocks publishing. False if unset/invalid. */
export function hasPassed(iso: string | null | undefined, now: Date = new Date()): boolean {
  if (!iso) return false;
  const d = new Date(iso);
  return !Number.isNaN(d.getTime()) && d.getTime() <= now.getTime();
}

/** How a timestamp is shown: a date and time (default), the date, a short "Oct 3", or the time. */
export type TimestampFormat = "datetime" | "date" | "short-date" | "time";

const FORMATS: Record<TimestampFormat, Intl.DateTimeFormatOptions> = {
  datetime: { dateStyle: "medium", timeStyle: "short" },
  date: { dateStyle: "medium" },
  "short-date": { month: "short", day: "numeric" },
  time: { timeStyle: "short" },
};

/**
 * A UTC timestamp in a time zone — the viewer's when `timeZone` is left out. A server-rendered page passes "UTC" (it
 * can't know the viewer's zone) and the layout's script rewrites each `<time data-local-time>` in the browser.
 */
export function formatTimestamp(iso: string | null | undefined, format: TimestampFormat = "datetime", timeZone?: string): string {
  const d = parseUtc(iso);
  if (!d) return "";
  return d.toLocaleString(undefined, { ...(FORMATS[format] ?? FORMATS.datetime), ...(timeZone ? { timeZone } : {}) });
}

/**
 * A server timestamp as a Date. The API writes UTC without a zone ("2026-10-12T18:45:17.247863"), which a browser would
 * read as local time — so a zone-less date-time is taken as UTC, and microseconds are cut to what Date reads.
 */
export function parseUtc(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  let text = String(iso).trim().replace(/(\.\d{3})\d+/, "$1");
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(text)) text += "Z";
  const d = new Date(text);
  return Number.isNaN(d.getTime()) ? null : d;
}
