// A finished audio job (the stitched cut of a story) leaves its result on the job's entry: the audio's URL and a timeline of
// where each spoken line and sound sits, named by the record it came from. This finds that shape in an entry's fields (any json field
// holding `{ url, timeline }`, so it is not tied to one entry type) and flattens it to rows a page can list and seek by.

export interface TimelineRow {
  kind: "line" | "sound";
  start: number;
  end: number | null;
  id: string | null; // the record's slug, to link to it
  speaker: string | null;
  text: string;
  shot: string;
}

export interface AudioTimeline {
  url: string;
  seconds: number | null;
  rows: TimelineRow[];
}

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

function rowsOf(timeline: unknown[]): TimelineRow[] {
  const rows: TimelineRow[] = [];
  for (const shot of timeline) {
    if (!isRecord(shot)) continue;
    const name = String(shot.shot ?? "");
    for (const fx of Array.isArray(shot.sounds) ? shot.sounds : []) {
      if (!isRecord(fx) || num(fx.start) === null) continue;
      rows.push({ kind: "sound", start: fx.start as number, end: num(fx.end), id: typeof fx.id === "string" ? fx.id : null, speaker: null, text: "Sound", shot: name });
    }
    for (const line of Array.isArray(shot.lines) ? shot.lines : []) {
      if (!isRecord(line) || num(line.start) === null) continue;
      rows.push({
        kind: "line",
        start: line.start as number,
        end: num(line.end),
        id: typeof line.id === "string" ? line.id : null,
        speaker: typeof line.speaker === "string" ? line.speaker : null,
        text: String(line.text ?? ""),
        shot: name,
      });
    }
  }
  return rows.sort((a, b) => a.start - b.start);
}

/** The audio and timeline in an entry's fields, or null when it has none. */
export function findTimeline(data: Record<string, unknown> | null | undefined): AudioTimeline | null {
  for (const value of Object.values(data ?? {})) {
    if (!isRecord(value) || typeof value.url !== "string" || !value.url || !Array.isArray(value.timeline)) continue;
    const rows = rowsOf(value.timeline);
    if (rows.length) return { url: value.url, seconds: num(value.seconds), rows };
  }
  return null;
}

/** m:ss.s, as a player shows it, so a note like "at 0:41" matches the page. */
export function timecode(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${(seconds - minutes * 60).toFixed(1).padStart(4, "0")}`;
}

/** The row playing at `time`: the last one that has started and not yet ended (a line with no end counts until the next row). */
export function rowAt(rows: TimelineRow[], time: number): number {
  let found = -1;
  rows.forEach((row, i) => {
    if (row.start <= time && (row.end === null || time < row.end)) found = i;
  });
  return found;
}
