/**
 * A `timeline` view placed by date (services/blueprints/views.py `spine.start`): what a date or datetime field says as a place on the
 * timeline, the view's range, its ruler, and how a place reads. Pure.
 *
 * Places are counted on the wall clock: a *wall* time is the date and time a calendar on the wall shows, kept as the milliseconds of that
 * date and time read as if they were UTC (`Date.UTC` of its parts). Every day is then 24 hours, so a day's column, a gap or a ruler never
 * moves with a zone or a change of the clocks. A plain date (`2026-11-19`) has no zone: it is that day, everywhere. A datetime written without
 * a zone (`2026-11-19T14:00`, what the entry form saves) is that time on the wall, as the form shows it back. A datetime with one (`…Z`,
 * `+01:00`) is a real moment, read in the viewer's zone; its length is real time, so a shift over the night the clocks change ends when the
 * clock says it does. Days are counted as days of the calendar.
 */

import type { TimeUnit } from "./timeline.ts";

/** The units a view placed by date counts in. */
export type DateUnit = Exclude<TimeUnit, "seconds">;
/** How an entry type's field holds a date (the entry type's `type`: services content_validator). */
export type DateKind = "date" | "datetime";

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
export const DAY_MS = 24 * HOUR_MS;
export const UNIT_MS: Record<DateUnit, number> = { minutes: MINUTE_MS, hours: HOUR_MS, days: DAY_MS };
/** What the range is rounded out to, so it starts and ends on a round time: whole days, whole hours, quarter hours. */
const RANGE_ROUND_MS: Record<DateUnit, number> = { days: DAY_MS, hours: HOUR_MS, minutes: 15 * MINUTE_MS };
/** 1 January 1970, the day `Date.UTC` counts from, was a Thursday: 4 days after a Sunday, 3 after a Monday. */
const EPOCH_AFTER_MONDAY = 3;
const WEEK_DAYS = 7;

/** A date or datetime as a place on the wall clock (`wall`), and whether it was a real moment (`zoned`) or a whole day (`day`). */
export interface Moment {
  wall: number;
  day: boolean;
  zoned: boolean;
  /** The real moment, for a zoned one (its length runs in real time). */
  real?: number;
}

const DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const DATETIME = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?\s*(Z|[+-]\d{2}:?\d{2})?$/i;

/** Date.UTC of the parts, or null when they are not a real date and time (30 February, 25:00). */
function wallOfParts(y: number, mo: number, d: number, h = 0, mi = 0, s = 0, ms = 0): number | null {
  const at = Date.UTC(y, mo - 1, d, h, mi, s, ms);
  const back = new Date(at);
  const real = back.getUTCFullYear() === y && back.getUTCMonth() === mo - 1 && back.getUTCDate() === d && back.getUTCHours() === h && back.getUTCMinutes() === mi;
  return real ? at : null;
}

const zoneParts = new Map<string, Intl.DateTimeFormat>();
/** The wall time a real moment shows in a zone (an IANA name; an unknown one reads as UTC). */
export function wallIn(real: number, timeZone: string): number {
  let format = zoneParts.get(timeZone);
  if (!format) {
    const options: Intl.DateTimeFormatOptions = { hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric", second: "numeric" };
    try {
      format = new Intl.DateTimeFormat("en-US", { ...options, timeZone });
    } catch {
      format = new Intl.DateTimeFormat("en-US", { ...options, timeZone: "UTC" });
    }
    zoneParts.set(timeZone, format);
  }
  const part = Object.fromEntries(format.formatToParts(new Date(real)).map((p) => [p.type, Number(p.value)]));
  return Date.UTC(part.year, part.month - 1, part.day, part.hour, part.minute, part.second, new Date(real).getUTCMilliseconds());
}

/** Whether a zone name is one this runtime knows (a cookie can hold anything). */
export function knownZone(timeZone: string | undefined | null): timeZone is string {
  if (!timeZone) return false;
  try {
    new Intl.DateTimeFormat("en-US", { timeZone });
    return true;
  } catch {
    return false;
  }
}

/** The viewer's language from a request's Accept-Language header (its first tag), when it is one this runtime can write dates in; undefined
 * (the runtime's own) for none, `*`, or a tag that is not one (`en_US`). */
export function localeOf(header: string | null | undefined): string | undefined {
  const tag = (header ?? "").split(",")[0]?.split(";")[0]?.trim();
  if (!tag) return undefined;
  try {
    return Intl.DateTimeFormat.supportedLocalesOf([tag]).length ? tag : undefined;
  } catch {
    return undefined;
  }
}

/**
 * What a field's value says as a place, or null when it is not a date. A `date` field is read by its day alone, so a value saved with a time
 * and a zone (`2026-11-19T00:00:00Z`) is still the 19th wherever it is looked at; any other field is a date, a datetime as on the wall, or a
 * datetime with a zone read in `timeZone`.
 */
export function momentOf(value: unknown, kind: DateKind | undefined, timeZone: string): Moment | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  const day = DATE.exec(kind === "date" ? text.slice(0, 10) : text);
  if (day) {
    const wall = wallOfParts(Number(day[1]), Number(day[2]), Number(day[3]));
    return wall === null ? null : { wall, day: true, zoned: false };
  }
  const m = DATETIME.exec(text);
  if (!m) return null;
  const [y, mo, d, h, mi, s] = m.slice(1, 7).map((x) => Number(x ?? 0));
  const ms = Number((m[7] ?? "0").slice(0, 3).padEnd(3, "0"));
  const wall = wallOfParts(y, mo, d, h, mi, s, ms);
  if (wall === null) return null;
  if (!m[8]) return { wall, day: false, zoned: false };
  const zone = m[8].toUpperCase();
  const offset = zone === "Z" ? 0 : (zone[0] === "-" ? -1 : 1) * (Number(zone.slice(1, 3)) * 60 + Number(zone.slice(-2))) * MINUTE_MS;
  const real = wall - offset;
  return { wall: wallIn(real, timeZone), day: false, zoned: true, real };
}

/** Where something that starts at `at` and lasts `length` of the unit ends, on the wall: a zoned moment's length runs in real time (except in
 * days, counted on the calendar), anything else's on the wall. */
export function wallEnd(at: Moment, length: number, unit: DateUnit, timeZone: string): number {
  const ms = length * UNIT_MS[unit];
  return at.zoned && at.real !== undefined && unit !== "days" ? wallIn(at.real + ms, timeZone) : at.wall + ms;
}

/** Where a range's `to` field ends: a plain date is the whole of that day (a week to Sunday includes Sunday). */
export const rangeEnd = (to: Moment): number => (to.day ? to.wall + DAY_MS : to.wall);

export interface DateRange {
  /** The wall time position 0 stands for, and the one the range ends at. */
  origin: number;
  end: number;
}

/**
 * The view's range: from the earliest start to the latest end of what is drawn, widened by the entry's own `from` and `to`, rounded out to
 * whole days (days), hours (hours) or quarter hours (minutes). Null when nothing has a date. At least one unit long.
 */
export function dateRange(spans: readonly { start: number; end: number }[], unit: DateUnit, widen: { from?: number | null; to?: number | null } = {}): DateRange | null {
  const starts = [...spans.map((s) => s.start), widen.from ?? Number.POSITIVE_INFINITY];
  const ends = [...spans.map((s) => s.end), widen.to ?? Number.NEGATIVE_INFINITY, widen.from ?? Number.NEGATIVE_INFINITY];
  const first = Math.min(...starts, widen.to ?? Number.POSITIVE_INFINITY);
  if (!Number.isFinite(first)) return null;
  const round = RANGE_ROUND_MS[unit];
  const origin = Math.floor(first / round) * round;
  const end = Math.max(Math.ceil(Math.max(...ends) / round) * round, origin + UNIT_MS[unit]);
  return { origin, end };
}

/** A wall time as a place in the view: units from its origin. */
export const placeOf = (wall: number, origin: number, unit: DateUnit): number => (wall - origin) / UNIT_MS[unit];
/** A place in the view as a wall time. */
export const wallAt = (t: number, origin: number, unit: DateUnit): number => origin + Math.round(t * UNIT_MS[unit]);

export const isMidnight = (wall: number): boolean => ((wall % DAY_MS) + DAY_MS) % DAY_MS === 0;
const dayIndex = (wall: number) => Math.floor(wall / DAY_MS);
const isMonday = (wall: number) => (((dayIndex(wall) + EPOCH_AFTER_MONDAY) % WEEK_DAYS) + WEEK_DAYS) % WEEK_DAYS === 0;
const isMonthStart = (wall: number) => isMidnight(wall) && new Date(wall).getUTCDate() === 1;

/** How each kind of place is written, in a locale, from a wall time (read as UTC, which it is). */
export function formats(locale: string | undefined) {
  const make = (options: Intl.DateTimeFormatOptions) => {
    try {
      return new Intl.DateTimeFormat(locale, { ...options, timeZone: "UTC" });
    } catch {
      return new Intl.DateTimeFormat(undefined, { ...options, timeZone: "UTC" });
    }
  };
  return {
    day: make({ weekday: "short", day: "numeric", month: "short" }),
    dayYear: make({ day: "numeric", month: "short", year: "numeric" }),
    time: make({ hour: "2-digit", minute: "2-digit" }),
    month: make({ month: "long", year: "numeric" }),
  };
}

/** A ruler step: a fixed length, or calendar weeks (from a Monday), months or quarters. */
type Step = number | "week" | "month" | "quarter";
const DATE_STEPS: Record<DateUnit, readonly Step[]> = {
  minutes: [5, 10, 15, 30, 60, 120, 180, 360, 720, 1440].map((m) => m * MINUTE_MS),
  hours: [...[1, 2, 3, 6, 12, 24].map((h) => h * HOUR_MS), "week"],
  days: [DAY_MS, "week", "month", "quarter"],
};
const ROUGH_MS: Record<Exclude<Step, number>, number> = { week: WEEK_DAYS * DAY_MS, month: 30 * DAY_MS, quarter: 91 * DAY_MS };

/** The wall times of a step's marks from `from` up to `to` (the range's end is the start of what is not shown, so it has no mark). */
function marksOf(step: Step, from: number, to: number): number[] {
  const out: number[] = [];
  if (typeof step === "number") {
    for (let w = Math.ceil(from / step) * step; w < to; w += step) out.push(w);
    return out;
  }
  if (step === "week") {
    for (let w = Math.ceil(from / DAY_MS) * DAY_MS; w < to; w += DAY_MS) if (isMonday(w)) out.push(w);
    return out;
  }
  const first = new Date(from);
  for (let y = first.getUTCFullYear(), m = first.getUTCMonth(); ; m++) {
    const w = Date.UTC(y, m, 1);
    if (w >= to) break;
    if (w >= from && (step === "month" || m % 3 === 0)) out.push(w);
  }
  return out;
}

export interface DateTick {
  /** Its place, in units from the origin, and the zoom levels it shows at (as `tickLevels`). */
  t: number;
  levels: number[];
  label: string;
  /** A midnight (a new day, in hours and minutes), the first of a month, a Monday: drawn stronger. */
  edge: "month" | "week" | "day" | null;
  /** Its label names the day that starts there (every mark in days, a midnight in hours and minutes), so it is written after the mark, over its
   * day, not across the line between two days. */
  day: boolean;
}

/**
 * The ruler of a view placed by date, for every zoom level at once (as `tickLevels`): at each level the smallest step of the unit that gives
 * about `want × level` marks. In days a mark reads its day ("Mon 16 Nov"); in hours and minutes a midnight reads its day and every other
 * mark its time ("06:00"), in `locale`. `minor` gives the marks of the step below, unnumbered, where there is no numbered one.
 */
export function dateTicks(range: DateRange, unit: DateUnit, want: number, zooms: readonly number[], locale?: string): { major: DateTick[]; minor: { t: number; levels: number[] }[] } {
  const steps = DATE_STEPS[unit];
  const span = range.end - range.origin;
  const f = formats(locale);
  const major = new Map<number, number[]>();
  const minor = new Map<number, number[]>();
  for (const z of zooms) {
    const fits = steps.findIndex((s) => span / (typeof s === "number" ? s : ROUGH_MS[s]) <= want * z);
    const at = fits < 0 ? steps.length - 1 : fits;
    for (const w of marksOf(steps[at], range.origin, range.end)) major.set(w, [...(major.get(w) ?? []), z]);
    if (at > 0) for (const w of marksOf(steps[at - 1], range.origin, range.end)) minor.set(w, [...(minor.get(w) ?? []), z]);
  }
  const edge = (w: number): DateTick["edge"] => (isMonthStart(w) ? "month" : isMidnight(w) && isMonday(w) ? "week" : isMidnight(w) && unit !== "days" ? "day" : null);
  const namesDay = (w: number) => unit === "days" || isMidnight(w);
  const label = (w: number) => (namesDay(w) ? f.day.format(w) : f.time.format(w));
  return {
    major: [...major].sort(([a], [b]) => a - b).map(([w, levels]) => ({ t: placeOf(w, range.origin, unit), levels, label: label(w), edge: edge(w), day: namesDay(w) })),
    minor: [...minor]
      .map(([w, levels]) => [w, levels.filter((z) => !major.get(w)?.includes(z))] as const)
      .filter(([, levels]) => levels.length > 0)
      .sort(([a], [b]) => a - b)
      .map(([w, levels]) => ({ t: placeOf(w, range.origin, unit), levels })),
  };
}

/** About how wide a day's label on the ruler is drawn (11px type) in a locale, with room around it: the longest of a two-digit day in each month
 * the range runs over ("Wed 30 Dec" needs less than "Wed, Dec 30", and British English writes "Sept"). */
const LABEL_CHAR_PX = 6.2;
const LABEL_GAP_PX = 10;
const LONG_DAY = 28;
export function dayLabelPx(range: DateRange, locale?: string): number {
  const f = formats(locale);
  const first = new Date(range.origin);
  const months: number[] = [];
  for (let m = first.getUTCMonth(), y = first.getUTCFullYear(); Date.UTC(y, m, 1) < range.end && months.length < 12; m++) months.push(Date.UTC(y, m, LONG_DAY));
  const longest = Math.max(...months.map((w) => f.day.format(w).length));
  return Math.ceil(longest * LABEL_CHAR_PX + LABEL_GAP_PX);
}

/** The months a view in days runs over, as stretches with their names ("November 2026"), for a band over the ruler. */
export function monthSpans(range: DateRange, unit: DateUnit, locale?: string): { start: number; seconds: number; label: string }[] {
  const f = formats(locale);
  const first = new Date(range.origin);
  const out: { start: number; seconds: number; label: string }[] = [];
  for (let m = first.getUTCMonth(), y = first.getUTCFullYear(); ; m++) {
    const from = Math.max(Date.UTC(y, m, 1), range.origin);
    if (from >= range.end) break;
    const to = Math.min(Date.UTC(y, m + 1, 1), range.end);
    out.push({ start: placeOf(from, range.origin, unit), seconds: placeOf(to, range.origin, unit) - placeOf(from, range.origin, unit), label: f.month.format(from) });
  }
  return out;
}

/** The lines down a view placed by date: where a month or a week (from a Monday) starts, and in hours and minutes every new day. The range's own
 * start has none (it is the edge of the box). */
export function edgesOf(range: DateRange, unit: DateUnit): { t: number; edge: "month" | "week" | "day" }[] {
  const out: { t: number; edge: "month" | "week" | "day" }[] = [];
  for (let w = Math.ceil(range.origin / DAY_MS) * DAY_MS; w < range.end; w += DAY_MS) {
    const edge = isMonthStart(w) ? "month" : isMonday(w) ? "week" : unit === "days" ? null : "day";
    if (edge && w > range.origin) out.push({ t: placeOf(w, range.origin, unit), edge });
  }
  return out;
}

/** Where today is (a view in days: the whole day) or now is (hours and minutes: the moment), from the viewer's wall clock; null outside the range. */
export function nowMark(range: DateRange, unit: DateUnit, nowWall: number): { start: number; seconds: number } | null {
  if (nowWall < range.origin || nowWall >= range.end) return null;
  if (unit !== "days") return { start: placeOf(nowWall, range.origin, unit), seconds: 0 };
  const day = Math.floor(nowWall / DAY_MS) * DAY_MS;
  return { start: placeOf(day, range.origin, unit), seconds: 1 };
}

/** The viewer's wall clock now, read in their own zone (the browser's). */
export function wallNow(now: Date = new Date()): number {
  return Date.UTC(now.getFullYear(), now.getMonth(), now.getDate(), now.getHours(), now.getMinutes(), now.getSeconds());
}
