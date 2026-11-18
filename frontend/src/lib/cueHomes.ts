/**
 * Where a cue on a word belongs when its line has moved. A cue row is stored in a beat's `cues` list and names a line (`line`, its slug); when the
 * line is moved to another beat the row stays behind. The render applies a cue to the beat that holds its line now (Screenplay Studio v221), so
 * the Timeline places it there; the beat page shows such a row with where its line went, a button that moves it, and the rows other beats store
 * for its own lines. Pure: no fetching.
 */

import { effectWords, emphasisWords } from "./cueKinds.ts";
import { type WordCue, cameraWords, parseWordCues } from "./wordCues.ts";

/** A cue and the beat whose list stores it (its slug). */
export interface StoredCue {
  cue: WordCue;
  stored: string;
}

/**
 * Every beat's cues, by the beat they play in: the beat that holds the cue's line now (`beatOfLine`: a line's slug to its beat's slug), else the
 * beat that stores it (a line that is gone or in no beat: the render leaves such a cue out, and so does the Timeline). In the beats' order, each
 * beat's in the order written.
 */
export function cuesByHolder(beats: readonly { slug: string; cues: unknown }[], beatOfLine: ReadonlyMap<string, string>): Map<string, StoredCue[]> {
  const out = new Map<string, StoredCue[]>();
  for (const beat of beats) {
    for (const cue of parseWordCues(beat.cues)) {
      const holder = beatOfLine.get(cue.line) || beat.slug;
      out.set(holder, [...(out.get(holder) ?? []), { cue, stored: beat.slug }]);
    }
  }
  return out;
}

/** Where a row stored on beat `here` belongs: here (its line is one of this beat's), on another beat (`beat`: the slug of the beat that holds its
 * line now), `gone` (no such line) or `unplaced` (the line is in no beat). `lines` maps every line looked up to its beat's slug ("" for none);
 * a line not looked up at all is taken to be here, so a failed lookup never shows a false notice. */
export type CueHome = { kind: "here" } | { kind: "moved"; beat: string } | { kind: "gone" } | { kind: "unplaced" };

export function homeOf(cue: Pick<WordCue, "line">, here: string, lines: ReadonlyMap<string, string> | null): CueHome {
  if (!lines) return { kind: "here" };
  if (!lines.has(cue.line)) return { kind: "gone" };
  const beat = lines.get(cue.line) ?? "";
  if (!beat) return { kind: "unplaced" };
  return beat === here ? { kind: "here" } : { kind: "moved", beat };
}

type Data = Record<string, unknown>;

/** A JSON list field as a list (stored as a list or as JSON text); null when it holds something else, so nothing is overwritten by mistake. */
function listOf(value: unknown): unknown[] | null {
  if (value === undefined || value === null || value === "") return [];
  if (Array.isArray(value)) return value;
  if (typeof value !== "string") return null;
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/** The list back in the form the field held it: JSON text stays text. */
const asStored = (before: unknown, list: unknown[]) => (typeof before === "string" ? JSON.stringify(list, null, 2) : list);

/** Two JSON values alike, whatever the order of their keys. */
function same(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (!a || !b || typeof a !== "object" || typeof b !== "object" || Array.isArray(a) !== Array.isArray(b)) return false;
  const [ka, kb] = [Object.keys(a), Object.keys(b)];
  return ka.length === kb.length && ka.every((k) => same((a as Data)[k], (b as Data)[k]));
}

const isRow = (v: unknown, line: string, word: number): boolean =>
  !!v && typeof v === "object" && !Array.isArray(v) && (v as Data).line === line && Math.floor(Number((v as Data).word ?? 0)) === word;

/**
 * A cue row moved from one beat's whole data to another's: found in `source[field]` at its stored `position` (when the row there is still that
 * line and word, else the first that is), taken out there and added at the end of `target[field]`. `row` is what to write on the target (the row
 * as the editor holds it); the stored one when left out. Every other key of both records is left as it was. Null when the row is not in the
 * source any more or either field holds something that is not a list.
 */
export function moveCueRow(source: Data, target: Data, field: string, at: { position?: number; line: string; word: number }, row?: unknown): { source: Data; target: Data } | null {
  const from = listOf(source[field]);
  const to = listOf(target[field]);
  if (!from || !to) return null;
  const index = at.position !== undefined && isRow(from[at.position], at.line, at.word) ? at.position : from.findIndex((v) => isRow(v, at.line, at.word));
  if (index < 0) return null;
  const moved = row ?? from[index];
  const already = to.some((v) => same(v, moved)); // a move tried before that reached the target but not the source: not added twice
  return {
    source: { ...source, [field]: asStored(source[field], from.filter((_, i) => i !== index)) },
    target: already ? target : { ...target, [field]: asStored(target[field], [...to, moved]) },
  };
}

/** A whole entry as the entries API reads and writes it: its title and slug go back with every PATCH, which replaces dataJson. */
export interface WholeEntry {
  title: string;
  slug: string;
  dataJson?: Data | null;
}

/** The two calls a move makes, so the order and the bodies can be checked without a server. */
export interface EntryApi {
  get(id: string): Promise<WholeEntry>;
  patch(id: string, body: { title: string; slug: string; dataJson: Data }): Promise<unknown>;
}

/**
 * Moves a cue row from beat `from` to beat `to` (ids, and `to`'s label for messages): both whole records are read, the row (`row`: as the
 * editor holds it) is added to `to` first and then taken out of `from`, each PATCH carrying the whole record and each read back and checked
 * (lib `patchedAsSent`). So a failure half way leaves the row on both beats, never on neither; a second try after one finds it already on `to`
 * and does not add it again. Throws with what to do when a step fails.
 */
export async function moveCue(api: EntryApi, field: string, from: string, to: { id: string; label: string }, at: { position?: number; line: string; word: number }, row: unknown): Promise<void> {
  const [here, there] = await Promise.all([api.get(from), api.get(to.id)]);
  const moved = moveCueRow(here.dataJson ?? {}, there.dataJson ?? {}, field, at, row);
  if (!moved) throw new Error("this cue is not saved on this beat yet (save the page first), or a cues list is not a list");
  const write = async (id: string, entry: WholeEntry, dataJson: Data) => {
    await api.patch(id, { title: entry.title, slug: entry.slug, dataJson });
    return patchedAsSent(dataJson, (await api.get(id)).dataJson ?? null, field);
  };
  const added = await write(to.id, there, moved.target);
  if (added) throw new Error(`${to.label} may not have taken it (${added}): check ${to.label} before trying again`);
  const removed = await write(from, here, moved.source);
  if (removed) throw new Error(`it is on ${to.label} now, but this beat did not let it go (${removed}): delete it here`);
}

/** Whether a record came back as written: as many keys as sent and the field's list as long. A reason when not, null when it did. */
export function patchedAsSent(sent: Data, back: Data | null | undefined, field: string): string | null {
  if (!back) return "the entry did not come back";
  const [want, got] = [Object.keys(sent).length, Object.keys(back).length];
  if (want !== got) return `it came back with ${got} fields instead of ${want}`;
  const [a, b] = [listOf(sent[field])?.length, listOf(back[field])?.length];
  return a === b ? null : `its ${field} came back with ${b ?? "no"} rows instead of ${a}`;
}

/** An entry as the entries query returns it (what this needs of one). */
export interface FoundRow {
  id: string;
  slug: string;
  title: string;
  dataJson?: Record<string, unknown> | null;
}

/** Where a row's line is now, as the beat page shows it: on another beat (with what the page needs to move the row there), gone, or in no beat. */
export type CueHomeView = { kind: "moved"; id: string; slug: string; label: string } | { kind: "gone" } | { kind: "unplaced" };

/** A row another beat stores for one of this beat's lines: shown here, read only, with where it is stored. */
export interface AdoptedCue {
  from: { id: string; slug: string; label: string };
  /** The line it sits on (who: its words) and where among them, and what it does. */
  line: string;
  text: string;
}

/** What the beat page adds to its cue rows for lines that moved: this beat (to move a row from), each stray row's line's home (missing when
 * the lookup failed: then no notice is shown), and the rows other beats of the story store for this beat's lines. */
export interface StrayData {
  self: { id: string; slug: string; label: string };
  homes?: Record<string, CueHomeView>;
  adopted: AdoptedCue[];
}

/** "beat 1004": a beat by its number (the view's spine order field), else its title. */
export const beatLabel = (row: FoundRow, order: string | undefined) => `beat ${String(row.dataJson?.[order ?? ""] ?? "").trim() || row.title}`;

/**
 * The beat page's view of rows whose line moved: for each line its own rows name that is not one of its lines, the beat that holds it now (looked
 * up by slug, the beat by the line's `in` field: from the story's beats, else by its slug); and every row another beat of the story stores for one
 * of its lines. `query` runs an entries query and gives null when it failed.
 */
export async function strayHomes(
  spec: { field: string; order?: string; beatType: string; lines: { entryType: string; in: string } },
  here: FoundRow,
  lines: readonly { slug: string; title: string; who: string; chips: string[] }[],
  storyBeats: readonly FoundRow[],
  sounds: readonly { slug: string; name: string }[],
  query: (spec: Record<string, unknown>) => Promise<FoundRow[] | null>,
): Promise<StrayData> {
  const self = { id: here.id, slug: here.slug, label: beatLabel(here, spec.order) };
  const mine = new Map(lines.map((l) => [l.slug, l] as const));
  const strays = [...new Set(parseWordCues(here.dataJson?.[spec.field]).map((c) => c.line))].filter((s) => !mine.has(s));
  const soundName = (slug: string) => sounds.find((s) => s.slug === slug)?.name ?? slug;
  const adopted = storyBeats
    .filter((b) => b.slug !== here.slug)
    .flatMap((b) =>
      parseWordCues(b.dataJson?.[spec.field])
        .filter((c) => mine.has(c.line))
        .map((c) => {
          const line = mine.get(c.line)!;
          const before = c.word > 0 ? line.chips[Math.min(c.word, line.chips.length) - 1] : "";
          return { from: { id: b.id, slug: b.slug, label: beatLabel(b, spec.order) }, line: `${line.who ? `${line.who}: ` : ""}${line.title}`, text: `${before ? `after “${before}”` : "before the first word"} · ${cueWords(c, soundName) || "nothing set"}` };
        }),
    );
  if (!strays.length) return { self, homes: {}, adopted };
  const found = await query({ entry_type: spec.lines.entryType, entries: strays });
  if (!found) return { self, adopted };
  const beatOf = new Map(found.map((r) => [r.slug, String(r.dataJson?.[spec.lines.in] ?? "")] as const));
  const known = new Map(storyBeats.map((b) => [b.slug, b] as const));
  const elsewhere = [...new Set([...beatOf.values()].filter((b) => b && b !== here.slug && !known.has(b)))];
  for (const b of elsewhere.length ? ((await query({ entry_type: spec.beatType, entries: elsewhere })) ?? []) : []) known.set(b.slug, b);
  const homes: Record<string, CueHomeView> = {};
  for (const slug of strays) {
    const home = homeOf({ line: slug }, here.slug, beatOf);
    if (home.kind === "here") continue; // a line of this beat set aside: not one to move
    if (home.kind !== "moved") {
      homes[slug] = home;
      continue;
    }
    const beat = known.get(home.beat);
    homes[slug] = beat ? { kind: "moved", id: beat.id, slug: beat.slug, label: beatLabel(beat, spec.order) } : { kind: "unplaced" };
  }
  return { self, homes, adopted };
}

/** What a cue does, in a line: "Sound clang · Camera: Punch 1.06 · Look: Flash white, 0.9, 0.25 s · Picture b04a". */
export function cueWords(cue: WordCue, soundName: (slug: string) => string = (s) => s): string {
  return [
    cue.sound && `Sound ${soundName(cue.sound)}${cue.ring ? " (rings over the next beats)" : ""}`,
    cue.camera && `Camera: ${cameraWords(cue.camera)}`,
    cue.look && `Look: ${effectWords("look", cue.look)}`,
    cue.mix && `Mix: ${effectWords("mix", cue.mix)}`,
    cue.emphasis && emphasisWords(cue.emphasis),
    cue.pic && `Picture ${cue.pic}`,
  ]
    .filter(Boolean)
    .join(" · ");
}
