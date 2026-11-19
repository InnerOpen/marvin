/**
 * How a `timeline` view writes time in its unit (services/blueprints/views.py `unit`): the ruler's steps, a position, a length, the playhead clock
 * and what may be typed into it. Seconds hands back the very functions the Timeline has always used, so a view that names no unit draws exactly
 * what it drew before; minutes, hours and days write plain words ("1 h 30 min", "Day 3", "2 weeks"). A view placed by date (`spine.start`)
 * writes a place as its date instead (`dateWords`). Pure.
 */

import { timecode } from "./audioTimeline.ts";
import { TICK_STEPS, type TimeUnit, clockText, parseClock } from "./timeline.ts";
import { DAY_MS, type DateUnit, formats, isMidnight, momentOf, placeOf, wallAt, wallNow } from "./timelineDates.ts";

export interface TimeWords {
  unit: TimeUnit;
  /** The ruler's steps, smallest first (`ticks` picks one). */
  steps: readonly number[];
  /** A place on the timeline: a ruler tick, where a piece starts. */
  position: (t: number) => string;
  /** How long something lasts, in a tooltip or a title. */
  length: (t: number) => string;
  /** A length in a card's corner, as short as it goes. */
  short: (t: number) => string;
  /** The whole timeline's length, in the header. */
  total: (t: number) => string;
  /** How far into an item the playhead is, beside the clock. */
  offset: (t: number) => string;
  /** The playhead clock, and what is typed into it read back (null: not a time). */
  clock: (t: number) => string;
  parse: (text: string) => number | null;
  /** How far `,` and `.` move the playhead, and with Shift. */
  nudge: readonly [number, number];
}

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const WEEK = 7 * DAY;
const SECONDS_IN: Record<TimeUnit, number> = { seconds: 1, minutes: MINUTE, hours: HOUR, days: DAY };

/** The most parts a length is written with: "1 h 30 min", never "1 h 30 min 12 s". */
const MAX_PARTS = 2;

interface Part {
  seconds: number;
  one: string;
  many: string;
}
const short = (seconds: number, label: string): Part => ({ seconds, one: label, many: label });
const SHORT_PARTS = { d: short(DAY, "d"), h: short(HOUR, "h"), min: short(MINUTE, "min"), s: short(1, "s") };

/** What a length in each unit is written with, largest first; the last is the finest it is rounded to (one below the unit). Days write words,
 * and weeks once a length reaches one. */
const PARTS: Record<Exclude<TimeUnit, "seconds">, Part[]> = {
  minutes: [SHORT_PARTS.d, SHORT_PARTS.h, SHORT_PARTS.min, SHORT_PARTS.s],
  hours: [SHORT_PARTS.d, SHORT_PARTS.h, SHORT_PARTS.min],
  days: [
    { seconds: WEEK, one: "week", many: "weeks" },
    { seconds: DAY, one: "day", many: "days" },
    short(HOUR, "h"),
  ],
};

/** The ruler's steps in each unit: round numbers of the unit (a quarter hour, a week, four weeks). */
export const UNIT_STEPS: Record<TimeUnit, readonly number[]> = {
  seconds: TICK_STEPS,
  minutes: [1, 5, 10, 15, 30, 60, 120, 240, 360, 720, 1440, 2880, 10080],
  hours: [0.25, 0.5, 1, 2, 3, 6, 12, 24, 48, 168, 336],
  days: [1, 2, 7, 14, 28, 56, 91, 182, 364],
};

/** `,` and `.` move the playhead by the first, with Shift the second: a minute or a quarter hour, a quarter hour or an hour, a day or a week. */
const NUDGES: Record<TimeUnit, readonly [number, number]> = { seconds: [0.1, 1], minutes: [1, 15], hours: [0.25, 1], days: [1, 7] };

const plural = (n: number, part: Part) => (n === 1 ? `${n} ${part.one}` : `${n} ${part.many}`);

/** A length in a unit other than seconds, in at most two parts: 90 minutes is "1 h 30 min", 1.25 days "1 day 6 h", 17 days "2 weeks 3 days". */
export function lengthText(value: number, unit: Exclude<TimeUnit, "seconds">): string {
  const parts = PARTS[unit];
  const finest = parts[parts.length - 1].seconds;
  const v = Number.isFinite(value) ? value : 0;
  let left = Math.round((Math.abs(v) * SECONDS_IN[unit]) / finest) * finest;
  const said: string[] = [];
  for (const part of parts) {
    const n = Math.floor(left / part.seconds + 1e-9);
    if (n > 0 && said.length < MAX_PARTS) said.push(plural(n, part));
    if (n > 0) left -= n * part.seconds;
    else if (said.length) break; // "1 h 5 min", never "1 d 5 min": a part is never skipped between two that are said
  }
  const own = parts.find((p) => p.seconds === SECONDS_IN[unit]) ?? parts[0];
  const text = said.length ? said.join(" ") : plural(0, own);
  return v < 0 && said.length ? `−${text}` : text;
}

/** A place on the timeline: the length from its start ("0 min", "1 h 30 min"), or in days the day it falls on, counted from Day 1. */
export function positionText(value: number, unit: Exclude<TimeUnit, "seconds">): string {
  if (unit !== "days") return lengthText(value, unit);
  const hours = Math.round(Math.max(0, Number.isFinite(value) ? value : 0) * 24);
  const day = Math.floor(hours / 24) + 1;
  return hours % 24 ? `Day ${day}, ${hours % 24} h` : `Day ${day}`;
}

const NAMED: [RegExp, number][] = [
  [/^(weeks?|w)$/, WEEK],
  [/^(days?|d)$/, DAY],
  [/^(hours?|hrs?|h)$/, HOUR],
  [/^(minutes?|mins?|m)$/, MINUTE],
  [/^(seconds?|secs?|s)$/, 1],
];

/**
 * What is typed into the clock of a view in another unit, in that unit, or null when it is not a time: a plain number ("90"), parts with their
 * names ("1 h 30 min", "2 weeks 3 days", "45m"), hours and minutes ("1:30", in minutes or hours) or a day ("Day 3", "day 3 6 h"). A comma works as
 * the decimal point.
 */
export function parseLength(text: string, unit: Exclude<TimeUnit, "seconds">): number | null {
  let raw = text.trim().toLowerCase().replace(/(\d),(\d)/g, "$1.$2");
  if (!raw) return null;
  if (/^\d+(\.\d+)?$/.test(raw)) return Number(raw);
  const clock = /^(\d+):([0-5]\d)$/.exec(raw);
  if (clock) return unit === "days" ? null : (Number(clock[1]) * HOUR + Number(clock[2]) * MINUTE) / SECONDS_IN[unit];
  let seconds = 0;
  const day = /^day\s*(\d+)\s*,?\s*/.exec(raw);
  if (day) {
    if (Number(day[1]) < 1) return null;
    seconds = (Number(day[1]) - 1) * DAY;
    raw = raw.slice(day[0].length);
  }
  const token = /(\d+(?:\.\d+)?)\s*([a-z]+)\s*,?\s*/y;
  while (raw.length > token.lastIndex) {
    const found = token.exec(raw);
    const size = found && NAMED.find(([name]) => name.test(found[2]))?.[1];
    if (!found || !size) return null;
    seconds += Number(found[1]) * size;
  }
  return seconds / SECONDS_IN[unit];
}

/** How a view in `unit` writes time. Seconds is the Timeline as it always was: timecodes, "4.0 s", "4.0s" and the h:mm:ss.mmm clock. */
export function timeWords(unit: TimeUnit): TimeWords {
  if (unit === "seconds") {
    return {
      unit,
      steps: UNIT_STEPS.seconds,
      position: timecode,
      length: (t) => `${t.toFixed(1)} s`,
      short: (t) => `${t.toFixed(1)}s`,
      total: timecode,
      offset: (t) => `${t.toFixed(3)} s`,
      clock: clockText,
      parse: parseClock,
      nudge: NUDGES.seconds,
    };
  }
  const length = (t: number) => lengthText(t, unit);
  const position = (t: number) => positionText(t, unit);
  return { unit, steps: UNIT_STEPS[unit], position, length, short: length, total: length, offset: length, clock: position, parse: (text) => parseLength(text, unit), nudge: NUDGES[unit] };
}

/**
 * How a view placed by date writes a place: the date, and the time when it is not the start of a day ("Mon 16 Nov", "Mon 16 Nov, 14:00").
 * Where something ends (`until`) in days is the last day it covers, so three days from Monday read "→ Wed 18 Nov". Lengths are written as in
 * any view in the unit; the clock takes a date ("2026-11-19", "2026-11-19 14:00"), "today" or "now", or a length from the start.
 */
export function dateWords(unit: DateUnit, origin: number, locale?: string): TimeWords & { until: (t: number) => string; range: (end: number) => string } {
  const f = formats(locale);
  const place = (w: number) => (isMidnight(w) ? f.day.format(w) : `${f.day.format(w)}, ${f.time.format(w)}`);
  const position = (t: number) => place(wallAt(t, origin, unit));
  const until = (t: number) => {
    const w = wallAt(t, origin, unit);
    return unit === "days" && isMidnight(w) && t > 0 ? f.day.format(w - DAY_MS) : place(w);
  };
  const parse = (text: string): number | null => {
    const typed = text.trim().toLowerCase();
    if (typed === "today" || typed === "now") return placeOf(typed === "today" ? Math.floor(wallNow() / DAY_MS) * DAY_MS : wallNow(), origin, unit);
    const at = momentOf(typed.replace(" ", "T"), undefined, "UTC");
    return at ? placeOf(at.wall, origin, unit) : parseLength(text, unit);
  };
  const length = (t: number) => lengthText(t, unit);
  // the first and the last day, or the moment when the range does not start or end at a midnight
  const range = (end: number) => {
    const [from, to] = [origin, wallAt(end, origin, unit)];
    const said = (w: number) => (isMidnight(w) ? f.dayYear.format(w) : `${f.dayYear.format(w)}, ${f.time.format(w)}`);
    return `${said(from)} – ${isMidnight(to) ? f.dayYear.format(to - DAY_MS) : said(to)}`;
  };
  return { unit, steps: [], position, until, length, short: length, total: length, offset: length, clock: position, parse, nudge: NUDGES[unit], range };
}
