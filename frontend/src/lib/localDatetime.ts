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
