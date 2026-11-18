/**
 * A `timeline` view, laid out: the entries a package's view definition names (services/blueprints/views.py), as positions in time.
 *
 * The spine (a story's beats) runs end to end; each item lasts as long as the renderer will cut it: an item with timed pieces in its lanes
 * (lines) lasts `lead + Σ piece seconds + gap × (pieces − 1) + tail`, an item with none lasts `hold`. A piece with no recording yet is
 * *estimated* from its text at a reading pace, so the timeline is useful before anything is recorded and firms up as takes land. Pure:
 * nothing here fetches; the page hands in rows and gets back what to draw.
 */

import { type Effect, effectChip, effectWords, kindOf, mixSeconds } from "./cueKinds.ts";
import { type StoredCue, cuesByHolder } from "./cueHomes.ts";
import { chipsOf } from "./wordCues.ts";

export interface SecondsSpec {
  hold?: string;
  lead?: string;
  gap?: string;
  tail?: string;
  /** A field on each item: how many seconds before its first word its picture comes in (a silent item's, before it starts), over the end of the
   * item before, while the sound stays where it is. Empty: the picture comes where the item's sound starts; 0: at its first word. */
  picture_lead?: string;
  defaults?: Partial<Record<"hold" | "lead" | "gap" | "tail", number>>;
  /** Fields on the view's entry (a story's `line_lead`...) that set these for every item that does not set its own: the item's field wins, then
   * the entry's, then `defaults`. As the render reads them (ScreenplayStudio marvin_pull: timing_of). */
  entry?: Partial<Record<"hold" | "lead" | "gap" | "tail" | "picture_lead", string>>;
}

export interface SpineSpec {
  entry_type: string;
  of: string;
  order?: string;
  group?: { entry_type: string; field: string; order?: string };
  picture?: string;
  text?: string;
  status?: string;
  title?: string;
  seconds?: SecondsSpec;
  /** A title card before the beats and an end card after them, from fields on the view's entry (a story's `intro_title`...). A card exists when
   * its `title` field has text, lasts the `seconds` field (else `default_seconds`) and is laid out as a real item, so every beat after it starts
   * when the render starts it. These must match what the render does (ScreenplayStudio render: pull `cards_of`). */
  cards?: { intro?: CardSpec; outro?: CardSpec };
  /** A pause where a scene ends: after an item whose next item holds a different value in `field` (both non-empty) the render adds the entry's
   * `seconds` field (when above 0) of quiet. Must match the render (ScreenplayStudio render: pull `scene_breaks`). */
  scene_break?: { field: string; seconds: string };
  /** Extra bands over the strip, each wrapping the consecutive items that share a value in `field` (the beats of one scene), titled by the
   * entry of `entry_type` that value names. They do not reorder anything. */
  bands?: { id?: string; entry_type: string; field: string; title?: string }[];
  /** A button on each item that runs a workflow for just that item (a quick draft of one beat): `entry` is the workflow input that gets the
   * entry's slug, `item` the input that gets this item's `field` value, `inputs` fixed values. */
  run?: { workflow: string; entry: string; item: string; field: string; label?: string; inputs?: Record<string, string | number | boolean> };
  /** Keep and Redo buttons on the items whose status is one of `ready`: they write `keep` or `redo` into the item's status field. */
  review?: { ready: string[]; keep: string; redo: string };
  /** A field on each item holding `{line, word}`: the item is an overlay whose picture comes in at that word of a piece laid before it (a line of
   * the beat before), at the start of the word after `word` words, and adds no time of its own; its own hold keeps it up that long from the word.
   * Must match the render (ScreenplayStudio render: manifest `starts_during`). */
  starts_during?: string;
  /** A JSON list on each item of cues on words (`[{line, word, sound?, volume?, camera?, look?, mix?, emphasis?, pic?, nudge?}]`, lib/wordCues.ts): each sits at a word of a piece
   * of the `in` lane `lane`; a cue's sound (an entry of the placed lane `sounds`) plays in that lane at the end of the word before it, as the render
   * plays it (marvin_pull `_cue_sounds`), and lengthens the item as a placed sound does. The entry page edits the field as rows. */
  word_cues?: { field: string; lane: string; sounds?: string };
}

export interface CardSpec {
  title: string;
  seconds?: string;
  default_seconds?: number;
  /** What the card is called on the timeline. */
  label?: string;
}

export interface BedSpec {
  /** The field naming the lane entry's slug: on the view's entry (default), on each spine item (`on: "spine"`), or on the entry a spine
   * item's `via` field names (`via` + `entry_type`: a beat's scene names its ambience). */
  field: string;
  on?: "entry" | "spine";
  via?: string;
  entry_type?: string;
  /** The level (0 to 1) on the entry that names the bed, and an override on the spine item. On a bed that runs under the whole story (no
   * `via`) the override *replaces* the level while that item plays (a beat's music_volume, 0 = silence) and shows as steps in the block. */
  volume?: string;
  item_volume?: string;
  muffled?: string;
  /** The level when neither the item, the entry that names the bed nor the sound itself sets one: what the render falls back to (0.12 for
   * music, 0.5 for ambience). Without it, 1. */
  default_volume?: number;
  /** The sound's own fade fields (seconds), what the render uses when they are empty (`default_fade_*`: ambience crossfades over 0.6, music
   * fades out over 2), and the field on the view's entry that sets how long every bed fades out at the end of the film (it wins there). */
  fade_in?: string;
  fade_out?: string;
  default_fade_in?: number;
  default_fade_out?: number;
  /** Fields on the view's entry for how every bed fades in at the start / out at the end of the film (they replace the sound's own there). */
  start_fade?: string;
  end_fade?: string;
  /** The cascade for a lane's own fades: the sound's, then the entry's (the story's), then the spine item's (a beat's), each replacing the one
   * before: `entry_fade_in` / `_out` are fields on the view's entry, `item_fade_in` / `_out` on each spine item. */
  entry_fade_in?: string;
  entry_fade_out?: string;
  item_fade_in?: string;
  item_fade_out?: string;
  /** How a story-wide bed's level eases from one step to the next (a beat's music_volume): `ramp` seconds by default (0: a hard edge), else the later
   * step's first item's `item_ramp_in`, else the earlier step's last item's `item_ramp_out`, centred on the cut and never longer than the shorter step. */
  ramp?: number;
  item_ramp_in?: string;
  item_ramp_out?: string;
  /** A bed that layers, as the render plays ambience: `item_field` on each spine item names its own sound, a second bed laid over the `via`
   * entry's (a beat's cheer over its scene's tavern, which runs on unbroken under it), and `entry_field` on the view's entry names a sound under
   * the whole film (the story's), which plays together with those, its level in `entry_volume`. `item_heard` on the spine item says how its own
   * bed is heard (`muffled` or `clear`); empty follows the `via` entry's muffling. */
  item_field?: string;
  item_heard?: string;
  entry_field?: string;
  entry_volume?: string;
  /** Where the story's bed is turned down or muffled (`entry_field` above): a field on each spine item (a beat's level for the story's bed), and fields
   * on the entry the item's `via` names (a scene's level, and whether it is heard from inside). The item's wins over the entry's over the story's:
   * each stretch is a step in the block that says who set it. */
  entry_item_volume?: string;
  entry_via_volume?: string;
  entry_via_muffled?: string;
  /** A field on the view's entry holding `none`, `light` or `strong`: how far the bed goes down under each spoken line (Play follows it). */
  duck?: string;
}

/** A video laid over each spine item's picture. The item's own field wins, then the entry `via` names (a beat's scene), then the view's entry
 * itself (the story); a blend of `none` at any of them switches the overlay off from there up. */
export interface CoverSpec {
  /** The asset field (its attached asset carries the field key as its role). */
  field: string;
  blend?: string;
  opacity?: string;
  via?: string;
  entry_type?: string;
  /** A card the item itself writes (an info card: a title and a sentence laid over its picture). It is drawn in this lane as its own block, after `delay`
   * seconds into the item (the item's field, else `default_delay`), and, as the render does, it takes the place of any overlay file for that item. */
  card?: { title: string; text?: string; delay?: string; default_delay?: number; name?: string };
}

/** One choice per spine item, written in its block: something about the shot that is not sound or picture (the camera's move). `other` wins (what an item
 * shows when a different field of its own is filled in: an exact camera move, written on purpose, so it beats a choice the item also holds), then
 * the item's own field, then the entry `via` names (a beat's scene), then the view's entry itself (the story). */
export interface MarksSpec {
  field: string;
  via?: string;
  entry_type?: string;
  /** How a value reads (else the value itself, spaced and capitalised) and the symbol drawn before it. */
  labels?: Record<string, string>;
  icons?: Record<string, string>;
  other?: { field: string; label: string };
  /** Values whose effect carries on across a cut (a ship's rocking runs on the film's clock), so consecutive items with the same one set by the same
   * scene or story are drawn as one block instead of one chip each. A value that starts afresh at every item (a push in) is not listed. */
  merge?: string[];
}

export interface LaneSpec {
  id: string;
  title: string;
  entry_type: string;
  /** The field on a lane entry that holds the view's entry's slug; required for `in` lanes, optional otherwise. */
  of?: string;
  in?: string;
  /** `volume`: the key inside each cue holding its own level (0 to 1), which replaces the sound's own for that cue. */
  placed?: { field: string; ref: string; at: string; volume?: string };
  bed?: BedSpec;
  cover?: CoverSpec;
  marks?: MarksSpec;
  order?: string;
  /** A boolean field on a lane entry that leaves it out when it is on: not timed, not drawn, not played (a line tried out and set aside, not deleted). */
  off?: string;
  text?: string;
  who?: string;
  audio?: string;
  /** The field holding the recording's peaks, to draw its waveform in the block: an array of peaks (0 to 1) or audiowaveform JSON ({bits, data: [min, max, …]}). */
  waveform?: string;
  seconds?: string;
  /** The lane entry's own level (0 to 1) and whether it repeats. */
  volume?: string;
  loop?: string;
  estimate_from?: string;
  status?: string;
  /** On an `in` lane: a field holding seconds the piece starts later (+) or earlier (-) than it falls (two voices overlap), the pieces after it
   * following it, and a boolean field that starts it with the piece before (dual dialogue). As the render lays lines (manifest `plan`). */
  nudge?: string;
  simultaneous?: string;
  /** The key in the recording's asset metadata holding its word timings ([{text, start, end}], seconds), to place a word in it. */
  words?: string;
  /** A guided setup (of the same package) a piece of this lane opens on, with the piece chosen, instead of its own page: a line opens its takes. */
  open?: { wizard: string };
}

export interface ActionSpec {
  label: string;
  wizard?: string;
  workflow?: string;
  /** With `workflow`: the button runs it at once instead of opening its page. `entry` names the workflow input that gets this entry's slug;
   * `inputs` are fixed values for the others (a render's quality). The page then follows the job the workflow makes. */
  run?: { entry: string; inputs?: Record<string, string | number | boolean> };
}

export interface TimelineSpec {
  kind: "timeline";
  title: string;
  description?: string;
  entry_type: string;
  /** The entry's field holding the picture's shape, by its trailing WxH (a story's `format`: short-9x16, square-1x1, wide-16x9). */
  aspect?: string;
  spine: SpineSpec;
  lanes?: LaneSpec[];
  actions?: ActionSpec[];
}

/** An entry as the entries query returns it: the fields in dataJson, the attached assets with the field key as their role. */
export interface Row {
  id: string;
  slug: string;
  title: string;
  dataJson?: Record<string, unknown> | null;
  assets?: { role?: string | null; name?: string | null; publicUrl?: string | null; mimeType?: string | null; metadataJson?: Record<string, unknown> | null }[];
}

/** A word of a recording, as the voice service times it (seconds into the take). */
export interface Word {
  text: string;
  start: number;
  end: number;
}

export interface Piece {
  id: string;
  slug: string;
  title: string;
  text: string;
  who: string;
  status: string;
  /** Seconds from the start of the whole timeline. */
  start: number;
  seconds: number;
  /** True when `seconds` came from the text, not a recording. */
  estimated: boolean;
  /** True when there is a take but its length was never stored (an upload), so `seconds` is still the text's estimate. */
  unmeasured: boolean;
  audio: string | null;
  /** The recording's peaks (0 to 1, a few hundred at most) for its waveform, when the entry holds them. */
  wave: number[] | null;
  /** The entry's own level, 0 to 1, when it declares one. */
  volume: number | null;
  /** For a placed piece: its offset inside the item, as declared. */
  at: number | null;
  /** For a timed piece: its own nudge (seconds later, or earlier when below 0, than it falls; 0 for none) and whether it starts with the piece
   * before (dual dialogue). */
  nudge: number;
  together: boolean;
  /** Where a timed piece would start without its own nudge (the start for any other piece). */
  natural: number;
  /** The take's word timings, when the lane names them and the take has them (delivery tags such as `[sighs]` left out). */
  words: Word[] | null;
  /** For a sound played by a cue on a word: the line (its title) and the word it plays after. */
  cue?: { line: string; word: number; text: string };
  /** For a piece an item's JSON list places (a beat's `sounds`, or a sound of its `cues`): that item, the list field, the entry's position in it and
   * the slug it names, so the page can move it and write back just that entry. */
  slot?: { item: string; field: string; index: number; ref: string };
}

/** A unique key for a piece on the page: a placed piece by its item and list position (one sound can be placed twice), any other by its id. */
export const pieceKey = (p: Pick<Piece, "id" | "slot">): string => (p.slot ? `${p.slot.item}:${p.slot.field}:${p.slot.index}` : p.id);

/** Where a placed sound dragged by `seconds` lands: its `at` in the item moved and snapped to NUDGE_SNAP (thousandths when `free`). It may be
 * negative, starting before its item over the one before, as the render plays it, but never before the film starts: `earliest` is minus the
 * item's start (0 for the first item, and by default). */
export function atAfterDrag(at: number, seconds: number, free = false, earliest = 0): number {
  const step = free ? 0.001 : NUDGE_SNAP;
  return Math.max(Math.min(earliest, 0), Math.round(Math.round((at + seconds) / step) * step * 1000) / 1000) + 0; // + 0: never -0
}

/**
 * An item's record with one key of one entry of a JSON list field set (or removed, with `undefined`), everything else as it was: what a page sends
 * back, because saving an entry replaces all its fields. Null when the list no longer holds an object at `index` naming `ref` in `refKey` (the
 * item was changed since the page was drawn), so nothing is written to the wrong entry.
 */
export function withListEntry(data: Record<string, unknown>, field: string, index: number, refKey: string, ref: string, key: string, value: number | undefined): Record<string, unknown> | null {
  const raw = data[field];
  let list: unknown = raw;
  if (typeof raw === "string") {
    try {
      list = JSON.parse(raw);
    } catch {
      return null;
    }
  }
  if (!Array.isArray(list)) return null;
  const entry = list[index];
  if (!entry || typeof entry !== "object" || Array.isArray(entry) || (entry as Record<string, unknown>)[refKey] !== ref) return null;
  const { [key]: _, ...rest } = entry as Record<string, unknown>;
  const changed = value === undefined ? rest : { ...rest, [key]: value };
  return { ...data, [field]: list.map((e, i) => (i === index ? changed : e)) };
}

/** A cue on a word, where it falls: on the piece (its id), at the end of the word before it (`at`, where its sound and camera move start) and the
 * start of the word after it (`picAt`, where a picture comes in); `estimated` when those come from the text, not the take's timings. */
export interface CueMark {
  piece: string;
  word: number;
  /** The word the cue comes after ("" before the first). */
  text: string;
  at: number;
  picAt: number;
  estimated: boolean;
  sound: { slug: string; title: string; heard: boolean } | null;
  camera: { kind: string; amount?: number; x?: number; y?: number } | null;
  pic: string | null;
  /** Seconds its sound, camera move, look, mix and emphasis come after (or before) the word; 0 for none. */
  nudge: number;
  /** How the picture looks from it (a flash, a tint): drawn on its flag, it changes no timing. Missing for none. */
  look?: Effect;
  /** A change to what is heard under the voice (dead air, a duck), and the stretch of the film it lasts, from its word plus its nudge (before its
   * item when nudged that far, never before the film starts, as a cue's sound): drawn over the bed lanes, it changes no timing. Missing for none; a kind the render does
   * not know has no stretch. */
  mix?: Effect;
  mixSpan?: { start: number; seconds: number };
  /** The word after it stands out in the captions. Missing for none. */
  emphasis?: true | Record<string, unknown>;
  /** Set when its row is stored on another beat than the one that holds its line now (the line was moved): that beat, its number as `title`. */
  stored?: { id: string; slug: string; title: string };
}

/** A change to the mix over a stretch of the film (lib/cueKinds.ts `MIX`), to draw over the lanes it changes (the beds: ambience, music). */
export interface MixStretch {
  item: string;
  kind: string;
  start: number;
  seconds: number;
  /** "dead air 1.5 s", for the block. */
  chip: string;
  /** "Dead air 1.5 s", for its tooltip. */
  words: string;
}

/** The changes to the mix the cues of these items make, in the order laid. */
export function mixStretches(items: readonly Item[]): MixStretch[] {
  return items.flatMap((item) =>
    (item.cues ?? []).flatMap((c) =>
      c.mix && c.mixSpan ? [{ item: item.id, kind: c.mix.kind, ...c.mixSpan, chip: effectChip("mix", c.mix) ?? c.mix.kind, words: effectWords("mix", c.mix) }] : [],
    ),
  );
}

/** A sound running under a stretch of the timeline: a scene's ambience across its beats, a story's music under everything. */
export interface Bed {
  id: string;
  slug: string;
  title: string;
  start: number;
  seconds: number;
  audio: string | null;
  /** The effective level: the sound's own × the level where it is named (× the spine item's override). */
  volume: number;
  loop: boolean;
  muffled: boolean;
  /** The spine items it runs under. */
  items: string[];
  /** When items set a level of their own: the whole block as runs at one level each (an item's level replaces the block's). Else empty. */
  steps: BedStep[];
  /** Seconds the block rises from silence at its start and falls to it at its end, as the render fades it (0 for none). */
  fadeIn: number;
  fadeOut: number;
  /** How far the bed goes down under speech, as a share of its level (0.12: down to an eighth), or null for none. */
  duck: number | null;
  /** A spine item's own bed, laid over the bed of the entry it names (a beat's over its scene's). Missing on every other bed. */
  over?: true;
  /** The bed under the whole film that the view's entry names (the story's own), laid under the scenes'. Missing on every other bed. */
  whole?: true;
}

export interface BedStep {
  start: number;
  seconds: number;
  volume: number;
  /** For the story's bed: who set this stretch's level (the story itself, a scene or a beat), the title of that scene or beat, and whether it is heard from inside. */
  source?: BedSource;
  by?: string;
  muffled?: boolean;
  /** Seconds the level eases into this step, centred on its start (0 or missing for the first step or a hard edge). */
  ramp?: number;
}

export type BedSource = "story" | "scene" | "beat";

/** A video over a stretch of pictures, merged across consecutive items that get the same one. */
export interface Cover {
  /** The video's address, which tells two overlays apart. */
  url: string;
  /** Its title in the library (its file name when it has none), for the label. */
  name: string;
  /** The entry type it was set on: the spine's, the `via`'s or the view's own. */
  from: string;
  blend: string;
  /** 0 to 1; 1 when none is set. */
  opacity: number;
  start: number;
  seconds: number;
  items: string[];
  /** True for a card the item writes itself (it has no file, so no address). */
  card?: boolean;
}

export interface Item {
  id: string;
  slug: string;
  /** Seconds of quiet added after this item where its scene ends (already part of `seconds`). */
  pause?: number;
  /** Set on a title or end card: not a beat, so it has no entry, no lanes and is not counted as one. */
  card?: "intro" | "outro";
  /** The value the item's run button hands the workflow (a beat's number as written: "04a"), when the spine declares one. */
  key: string;
  title: string;
  number: number | null;
  text: string;
  picture: string | null;
  status: string;
  /** Where the item's sound starts and how long it lasts: the items' sounds run end to end (its pieces are timed from here). */
  start: number;
  seconds: number;
  /** Where its picture is up: the same as its sound unless a picture lead, a nudge or an overlay moved a cut (the render cuts the pictures from
   * the sound, so the film is as long either way). The strip, the beds, overlays, marks, bands and chapters go by this, as the render does. */
  onScreen: { start: number; seconds: number };
  /** True when any timed piece in it is estimated (so its length may change). */
  estimated: boolean;
  lanes: Record<string, Piece[]>;
  /** Its cues on words (`spine.word_cues`) whose piece is laid, in the order written. */
  cues?: CueMark[];
  /** The silences its timed pieces were laid with (missing on a card), to lay them again while one is dragged. */
  timing?: { lead: number; gap: number; tail: number };
  /** Set on an item whose picture comes in at a word of a piece laid before it (`spine.starts_during`): that piece, the word, and where on the
   * film the picture comes in (`onScreen.start` unless the least picture length moved it); `estimated` when the place came from the text. */
  overlay?: { piece: string; title: string; word: number; text: string; at: number; estimated: boolean };
}

export interface Group {
  /** Set on the group a title or end card sits in. */
  card?: "intro" | "outro";
  id: string | null;
  slug: string | null;
  title: string;
  start: number;
  seconds: number;
  items: Item[];
}

/** A stretch of consecutive items that share a value (the beats of one scene), drawn as a band over them. */
export interface Band {
  /** The entry the value names (to open it), when it was found. */
  id: string | null;
  slug: string;
  title: string;
  start: number;
  seconds: number;
  items: string[];
}

export interface Layout {
  total: number;
  groups: Group[];
  items: Item[];
  /** Per band (its `id`, else its `field`), its stretches in time order. */
  bands: Record<string, Band[]>;
  /** Per bed lane, its blocks in time order. */
  beds: Record<string, Bed[]>;
  /** Per cover lane, its blocks in time order. */
  covers: Record<string, Cover[]>;
  /** Per marks lane, one mark for each item that has a choice, in time order. */
  marks: Record<string, Mark[]>;
}

export const DEFAULT_SECONDS = { hold: 4, lead: 0.3, gap: 0.25, tail: 0.35 };
export const WORDS_PER_MINUTE = 150;
export const MIN_ESTIMATE_SECONDS = 1;
/** The narrowest card: a 0.3 s item is still something to click. */
export const MIN_ITEM_PX = 72;

const num = (v: unknown): number | null => {
  const n = typeof v === "string" && v.trim() !== "" ? Number(v) : v;
  return typeof n === "number" && Number.isFinite(n) ? n : null;
};
const str = (v: unknown): string => (v === null || v === undefined ? "" : String(v));
const field = (row: Row, key: string | undefined): unknown => (key ? row.dataJson?.[key] : undefined);

/** How long reading `text` aloud takes, at a steady pace; never under a second, so an unrecorded line still has a width. */
export function estimateSeconds(text: string): number {
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  return Math.max(MIN_ESTIMATE_SECONDS, (words / WORDS_PER_MINUTE) * 60);
}

/** The picture an item shows: the asset attached in the picture field's role (a linked asset field syncs its role to its key). */
export function assetUrl(row: Row, key: string | undefined, kind: "image/" | "audio/" | "video/"): string | null {
  return assetOf(row, key, kind)?.publicUrl ?? null;
}

/** The asset attached in the field's role, with the title it was given in the library. */
export function assetOf(row: Row, key: string | undefined, kind: "image/" | "audio/" | "video/"): { publicUrl: string; name: string | null } | null {
  if (!key) return null;
  const hit = (row.assets ?? []).find((a) => a.role === key && a.publicUrl && (a.mimeType ?? "").startsWith(kind));
  return hit?.publicUrl ? { publicUrl: hit.publicUrl, name: hit.name?.trim() || null } : null;
}

/** A lane piece's seconds: the recording's duration when it has one, else an estimate from its text, else nothing (a sound with no file). */
export function pieceSeconds(row: Row, lane: LaneSpec): { seconds: number; estimated: boolean } | null {
  const recorded = num(field(row, lane.seconds));
  if (recorded !== null && recorded > 0) return { seconds: recorded, estimated: false };
  const text = str(field(row, lane.estimate_from));
  if (lane.estimate_from && text.trim()) return { seconds: estimateSeconds(text), estimated: true };
  return null;
}

/** The most a silence set on the view's entry may be, and a picture lead, as the render holds them (ScreenplayStudio marvin_pull: timing_of). */
export const MAX_ENTRY_SILENCE = 30;
export const MAX_PICTURE_LEAD = 5;
/** The most a nudge moves a piece, either way (marvin_pull: nudge). */
export const MAX_NUDGE = 10;
/** The least a picture stays up when the next one is brought forward by a picture lead (ScreenplayStudio render: manifest MIN_PICTURE). */
export const MIN_PICTURE = 0.5;

const within = (v: number | null, low: number, high: number): number | null => (v === null ? null : Math.min(Math.max(v, low), high));

/** The seconds an item's own fields set, each falling back to what the view's entry (a story) sets for every item, then the view's default, then
 * the renderer's. */
export function secondsOf(row: Row, spec: SecondsSpec | undefined, entry?: Row): typeof DEFAULT_SECONDS {
  const out = { ...DEFAULT_SECONDS, ...(spec?.defaults ?? {}) };
  for (const key of ["hold", "lead", "gap", "tail"] as const) {
    const shared = entry ? within(num(field(entry, spec?.entry?.[key])), 0, MAX_ENTRY_SILENCE) : null;
    if (shared !== null) out[key] = shared;
    const own = num(field(row, spec?.[key]));
    if (own !== null && own >= 0) out[key] = own;
  }
  return out;
}

/** How many seconds before its first word an item's picture comes in: its own field, else the view's entry's, held to 0 to 5; null when neither
 * is set (the picture comes where the item's sound starts). 0 is a value: at the first word. */
export function pictureLeadOf(row: Row, spec: SecondsSpec | undefined, entry?: Row): number | null {
  const own = num(field(row, spec?.picture_lead));
  const shared = entry ? num(field(entry, spec?.entry?.picture_lead)) : null;
  return within(own ?? shared, 0, MAX_PICTURE_LEAD);
}

/**
 * The renderer's rule: timed pieces one after another with silences around them; nothing timed, and the item holds (its own hold, else the view's
 * default). An item that sets its own hold lasts at least that long even with timed pieces: the picture stays up after the last line, so a beat
 * that would be too quick for a viewer to take in can be given the time. The view's default hold is only for an item with nothing in it.
 * `spoken`, when given, is how long the pieces take with their silences (`placeLines`, once a nudge has moved one) instead of end to end.
 */
export function itemSeconds(row: Row, timed: { seconds: number }[], spec: SecondsSpec | undefined, entry?: Row, spoken?: number): number {
  const s = secondsOf(row, spec, entry);
  if (timed.length === 0) return s.hold;
  const laid = spoken ?? s.lead + timed.reduce((sum, p) => sum + p.seconds, 0) + s.gap * (timed.length - 1) + s.tail;
  const own = num(field(row, spec?.hold));
  return own !== null && own > laid ? own : laid;
}

/** A timed piece as `placeLines` lays it: its length, its nudge and whether it starts with the piece before. */
export interface LineTiming {
  seconds: number;
  nudge: number;
  together: boolean;
}

/**
 * Where an item's timed pieces start on the film, as the render lays a beat's lines (ScreenplayStudio render: manifest `plan`): one after another
 * from the lead with a gap between; a nudged piece starts that much later or earlier (never before the film starts) and the pieces after it follow
 * where it now ends; a piece `together` with the one before starts when that one starts (then its own nudge applies) and the next follows the later
 * of the two. `spoken` is how long the item's sound lasts: until its latest piece ends, then the tail; null when nothing moved a piece, so the
 * caller keeps the plain sum (the same number, without a rounding difference). `clock` is where the item's sound starts.
 */
export function placeLines(lines: LineTiming[], s: { lead: number; gap: number; tail: number }, clock: number): { starts: number[]; naturals: number[]; spoken: number | null } {
  let cursor = clock + s.lead;
  let lastEnd = clock;
  let moved = false;
  const starts: number[] = [];
  const naturals: number[] = []; // where each would start without its own nudge (the lines before it as they are): what a drag measures from
  lines.forEach((line, i) => {
    const together = line.together && i > 0;
    if (line.nudge || line.together) moved = true;
    if (together) cursor = starts[i - 1];
    naturals.push(cursor);
    if (line.nudge) cursor = Math.max(cursor + line.nudge, 0);
    starts.push(cursor);
    if (together) {
      cursor = Math.max(starts[i - 1] + lines[i - 1].seconds, cursor + line.seconds) + s.gap;
      lastEnd = Math.max(lastEnd, cursor - s.gap);
      return;
    }
    lastEnd = Math.max(lastEnd, cursor + line.seconds);
    cursor += line.seconds;
    cursor += s.gap;
  });
  return { starts, naturals, spoken: moved && lines.length ? Math.max(cursor - s.gap, lastEnd) - clock + s.tail : null };
}

/** How fine a dragged piece's nudge snaps (seconds); shift drags it free, to the thousandth. */
export const NUDGE_SNAP = 0.05;

/**
 * The nudge a piece dragged to start at `start` gets: its offset from where it would start without one (`natural`), snapped to NUDGE_SNAP (or to
 * the thousandth when `free`), held to the render's -10..10 and never earlier than the film's start (the render would start it at 0 anyway).
 * 0 means no nudge: the piece is back where it falls.
 */
export function nudgeAfterDrag(natural: number, start: number, free = false): number {
  const raw = start - natural;
  const step = free ? 0.001 : NUDGE_SNAP;
  const snapped = Math.round(raw / step) * step;
  const held = Math.min(Math.max(snapped, -natural, -MAX_NUDGE), MAX_NUDGE);
  const out = Math.round(held * 1000) / 1000;
  return Math.abs(out) < 1e-9 ? 0 : out;
}

/** Where an item's timed pieces start when one of them (`index`) gets `nudge` instead of its own: the drawing while a piece is dragged, the pieces
 * after it following it as they will once it is saved. */
export function relaid(lines: LineTiming[], s: { lead: number; gap: number; tail: number }, clock: number, index: number, nudge: number): number[] {
  return placeLines(
    lines.map((line, i) => (i === index ? { ...line, nudge } : line)),
    s,
    clock,
  ).starts;
}

/** A piece's word timings from its take's asset metadata, as the render reads them (marvin_pull: spoken_words): a delivery tag such as `[sighs]`
 * is not a word. Null when the lane names none or the take has none. */
export function wordTimings(row: Row, lane: LaneSpec): Word[] | null {
  if (!lane.words || !lane.audio) return null;
  const take = (row.assets ?? []).find((a) => a.role === lane.audio && (a.mimeType ?? "").startsWith("audio/"));
  const raw = take?.metadataJson?.[lane.words];
  if (!Array.isArray(raw)) return null;
  const words = raw
    .filter((w): w is Record<string, unknown> => !!w && typeof w === "object" && (w as Record<string, unknown>).text != null)
    .map((w) => ({ text: String(w.text), start: num(w.start) ?? 0, end: num(w.end) ?? 0 }))
    .filter((w) => !(w.text.startsWith("[") && w.text.endsWith("]")));
  return words.length ? words : null;
}

/**
 * Where a place among a piece's words falls, in seconds into the piece, as the render places a cue (marvin_pull: word_place): `word` is how many
 * words are spoken before it. `after` is the end of the word before it (a sound plays when "strikes" is said); else the start of the word after it
 * (a picture comes in on the next word). From the take's word timings when there are any, else from where the word stands in the text as a share of
 * the piece's length (`estimated`). Before the first word is the piece's start, past the last its end; never past the piece's end.
 */
export function wordAt(piece: { text: string; seconds: number; words: Word[] | null }, word: number, after: boolean): { at: number; estimated: boolean } {
  const n = Math.max(0, Math.floor(word));
  const held = (at: number) => Math.min(Math.max(at, 0), piece.seconds);
  const words = piece.words ?? [];
  if (words.length) {
    if (after) return { at: held(n ? words[Math.min(n, words.length) - 1].end : 0), estimated: false };
    return { at: held(n < words.length ? words[n].start : words[words.length - 1].end), estimated: false };
  }
  const spans = [...piece.text.matchAll(/\S+/g)].map((m) => [m.index ?? 0, (m.index ?? 0) + m[0].length]);
  if (!spans.length) return { at: 0, estimated: true };
  const chars = after ? (n ? spans[Math.min(n, spans.length) - 1][1] : 0) : n < spans.length ? spans[n][0] : piece.text.length;
  const share = Math.round((chars / Math.max(piece.text.length, 1)) * 10000) / 10000;
  return { at: held(share * piece.seconds), estimated: true };
}

/** A shot as `picturesOf` cuts it: where its sound starts and how long it lasts, where its first word starts without a nudge of its own (null with none), its picture lead and,
 * for an overlay, where on the film its picture comes in. */
export interface PictureCut {
  start: number;
  seconds: number;
  firstWord: number | null;
  lead: number | null;
  anchor: number | null;
}

/**
 * Where each picture is up, cut from the sound as the render cuts it (ScreenplayStudio render: manifest `_pictures`). With no lead a picture starts
 * where its sound starts, or at its first word when that comes earlier (a nudge moves the voice, never the picture); with one, that long before its first word (a silent item's, before
 * its own start); an overlay's at its word. A picture brought forward never comes before the one before it plus MIN_PICTURE, never before 0, and
 * never later than its sound starts unless its lead asks for that. When nothing moved, the pictures are the sound's windows exactly.
 */
export function picturesOf(shots: PictureCut[], total: number): { start: number; seconds: number }[] {
  const starts: number[] = [];
  shots.forEach((shot, k) => {
    const here = shot.start;
    const first = shot.firstWord ?? here;
    const wanted = shot.anchor ?? (shot.lead !== null ? first - shot.lead : Math.min(here, first));
    if (k === 0) starts.push(0);
    else if (wanted === here) starts.push(here);
    else {
      const before = starts[k - 1];
      starts.push(Math.max(before, Math.min(Math.max(wanted, before + MIN_PICTURE), Math.max(wanted, here), total)));
    }
  });
  if (starts.every((at, k) => at === shots[k].start)) return shots.map((s) => ({ start: s.start, seconds: s.seconds }));
  return starts.map((at, k) => ({ start: at, seconds: (k + 1 < starts.length ? starts[k + 1] : total) - at }));
}

/** A number as a person writes beats: 4, "04" or "04a" (a beat inserted after 04), as its digits and its letters. Null for anything else. */
const sequence = (v: unknown): [number, string] | null => {
  const m = /^\s*0*(\d+)\s*([a-z]*)\s*$/i.exec(typeof v === "number" ? String(v) : typeof v === "string" ? v : "");
  return m ? [Number(m[1]), m[2].toLowerCase()] : null;
};

const byOrder = (key: string | undefined) => (a: Row, b: Row) => {
  const [p, q] = [sequence(field(a, key)), sequence(field(b, key))];
  if (p && q && (p[0] !== q[0] || p[1] !== q[1])) return p[0] !== q[0] ? p[0] - q[0] : p[1].length - q[1].length || p[1].localeCompare(q[1]); // 04, 04a ... 04z, 04aa, 05: as the render orders them (letters by length, then alphabet)
  const [x, y] = [num(field(a, key)), num(field(b, key))];
  if (x !== null && y !== null && x !== y) return x - y;
  if (x === null && y !== null) return 1;
  if (x !== null && y === null) return -1;
  return a.slug.localeCompare(b.slug); // the renderer's own fallback: slugs are numbered (story-line-007)
};

interface Rows {
  /** The view's entry itself (a bed lane may name its sound on it). */
  entry?: Row;
  spine: Row[];
  groups?: Row[];
  /** Per lane id, its entries: the children of an `in` lane, the referenced entries of a `placed` or `bed` lane. */
  lanes: Record<string, Row[]>;
  /** Per bed lane with `via`, the entries the spine items name (the scenes). */
  via?: Record<string, Row[]>;
  /** Per band, the entries its field names (the scenes), to title the band. */
  bands?: Record<string, Row[]>;
}

const level = (v: unknown): number | null => {
  const n = num(v);
  return n === null ? null : Math.max(0, Math.min(1, n));
};

/**
 * Lay the view out. Spine rows are sorted by the spine's order field and gathered under their group (chapters in their own order; items
 * whose group is unknown come last, under no title). Each `in` lane's rows are the pieces of the item their `in` field names, timed one after
 * another from the item's lead; each `placed` lane's pieces sit where the item's JSON list puts them. Unknown references are ignored.
 */
export function layout(spec: TimelineSpec, rows: Rows): Layout {
  const lanes = spec.lanes ?? [];
  const inLanes = lanes.filter((l) => l.in);
  const placedLanes = lanes.filter((l) => l.placed);
  const bedLanes = lanes.filter((l) => l.bed);
  const laneOf = (id: string | undefined) => (id ? placedLanes.find((l) => l.id === id) : undefined);
  const laneRows = (lane: LaneSpec) => [...(rows.lanes[lane.id] ?? [])].filter((r) => !isOff(r, lane)).sort(byOrder(lane.order));
  const bySlug = (lane: LaneSpec) => new Map(laneRows(lane).map((r) => [r.slug, r] as const));

  const items: Item[] = [];
  let clock = 0;
  const groups = groupRows(spec.spine, rows);
  const out: Group[] = [];
  const said = new Map<string, Piece>(); // every timed piece laid so far, by slug: an overlay comes in at a word of one of them
  const cuts: PictureCut[] = []; // each item's sound and what moves its picture, to cut the pictures from once everything is laid
  // A title or end card is an item of its own, so everything laid out after it starts when the render starts it.
  const addCard = (kind: "intro" | "outro") => {
    const card = cardOf(spec.spine.cards?.[kind], rows.entry, kind);
    if (!card) return;
    const item: Item = { id: `card:${kind}`, slug: kind, key: "", title: card.label, number: null, text: card.title, picture: null, status: "", start: clock, seconds: card.seconds, onScreen: { start: clock, seconds: card.seconds }, estimated: false, lanes: {}, card: kind };
    items.push(item);
    cuts.push({ start: clock, seconds: card.seconds, firstWord: null, lead: null, anchor: null });
    out.push({ card: kind, id: null, slug: null, title: card.label, start: clock, seconds: card.seconds, items: [item] });
    clock += card.seconds;
  };
  addCard("intro");
  // The pause where a scene ends: after an item whose next item is in another scene. The rows come in the order the render plays them.
  const flat = groups.flatMap((g) => g.rows);
  const nextOf = new Map(flat.map((r, i) => [r.id, flat[i + 1]] as const));
  // Cues on words play in the beat that holds their line now, wherever their row is stored (a line moved to another beat leaves its cue behind).
  const wordCueLane = spec.spine.word_cues ? inLanes.find((l) => l.id === spec.spine.word_cues!.lane) : undefined;
  const beatOfLine = new Map(wordCueLane ? laneRows(wordCueLane).map((r) => [r.slug, str(field(r, wordCueLane.in))] as const) : []);
  const cuesHeld = spec.spine.word_cues ? cuesByHolder(flat.map((r) => ({ slug: r.slug, cues: field(r, spec.spine.word_cues!.field) })), beatOfLine) : new Map<string, StoredCue[]>();
  const rowBySlug = new Map(flat.map((r) => [r.slug, r] as const));
  const pauseSeconds = spec.spine.scene_break && rows.entry ? num(field(rows.entry, spec.spine.scene_break.seconds)) : null;
  const pauseAfter = (row: Row): number => {
    const next = nextOf.get(row.id);
    const field_ = spec.spine.scene_break?.field;
    if (!next || !field_ || pauseSeconds === null || pauseSeconds <= 0) return 0;
    const [here, there] = [str(field(row, field_)).trim(), str(field(next, field_)).trim()];
    return here && there && here !== there ? pauseSeconds : 0;
  };
  for (const g of groups) {
    const made: Item[] = [];
    for (const row of g.rows) {
      const s = secondsOf(row, spec.spine.seconds, rows.entry);
      const item: Item = {
        id: row.id,
        slug: row.slug,
        key: str(field(row, spec.spine.run?.field)),
        title: str(field(row, spec.spine.title)) || row.title,
        number: num(field(row, spec.spine.order)),
        text: str(field(row, spec.spine.text)),
        picture: assetUrl(row, spec.spine.picture, "image/"),
        status: str(field(row, spec.spine.status)),
        start: clock,
        seconds: 0,
        onScreen: { start: clock, seconds: 0 },
        estimated: false,
        lanes: {},
      };
      // Timed pieces run across the `in` lanes in declared order, one after another from the lead (a nudge or dual dialogue moves them).
      const timed: Piece[] = [];
      for (const lane of inLanes) {
        const pieces: Piece[] = [];
        for (const r of laneRows(lane).filter((r) => str(field(r, lane.in)) === row.slug)) {
          const length = pieceSeconds(r, lane);
          const piece = pieceOf(r, lane, length?.seconds ?? 0, length?.estimated ?? false, clock + s.lead, null);
          if (length) timed.push(piece);
          pieces.push(piece);
        }
        item.lanes[lane.id] = pieces;
      }
      const placedLines = placeLines(timed, s, clock);
      item.timing = { lead: s.lead, gap: s.gap, tail: s.tail };
      timed.forEach((p, i) => {
        p.start = placedLines.starts[i];
        p.natural = placedLines.naturals[i];
        said.set(p.slug, p);
      });
      let end = clock + s.lead; // a piece with no length sits where the piece before it ends
      for (const lane of inLanes) {
        for (const p of item.lanes[lane.id]) {
          if (timed.includes(p)) end = p.start + p.seconds;
          else p.start = p.natural = end;
        }
      }
      const overlay = overlayOf(row, spec.spine, said);
      const ownHold = num(field(row, spec.spine.seconds?.hold));
      // An overlay adds no time of its own; its hold keeps it up that long from its word, so only what runs past the item before counts.
      const spoken = timed.length ? itemSeconds(row, timed, spec.spine.seconds, rows.entry, placedLines.spoken ?? undefined) : 0;
      item.seconds = overlay ? Math.max(ownHold !== null && ownHold > 0 ? Math.max(0, overlay.at + ownHold - clock) : 0, spoken) : itemSeconds(row, timed, spec.spine.seconds, rows.entry, placedLines.spoken ?? undefined);
      if (overlay) item.overlay = overlay;
      item.pause = pauseAfter(row);
      item.seconds += item.pause;
      item.estimated = timed.some((p) => p.estimated);
      let reach = 0; // how far into the item its last placed sound runs: the render lets a beat last until that sound has finished
      for (const lane of placedLanes) {
        const known = bySlug(lane);
        const placed = field(row, lane.placed!.field);
        const pieces: Piece[] = [];
        for (const [index, ref] of (Array.isArray(placed) ? placed : []).entries()) {
          if (typeof ref !== "object" || ref === null) continue;
          const target = known.get(str((ref as Record<string, unknown>)[lane.placed!.ref]));
          if (!target) continue;
          // before its item when negative, reaching back over the one before, as the render plays it; never before the film starts
          const at = Math.max(-clock, num((ref as Record<string, unknown>)[lane.placed!.at]) ?? 0) + 0; // + 0: never -0
          const length = pieceSeconds(target, lane);
          const piece = pieceOf(target, lane, length?.seconds ?? 0, length?.estimated ?? false, clock + at, at);
          const own = lane.placed!.volume ? level((ref as Record<string, unknown>)[lane.placed!.volume]) : null;
          if (own !== null) piece.volume = own; // the cue's own loudness replaces the sound's, as in the render
          piece.slot = { item: row.id, field: lane.placed!.field, index, ref: piece.slug };
          pieces.push(piece);
          // A sound with no take yet has a width to show it needs filling in (its text, as a line has), but nothing plays, so it never lengthens its item.
          const plays = !!length && (!length.estimated || !!assetUrl(target, lane.audio, "audio/"));
          reach = Math.max(reach, at + (plays ? length!.seconds : 0));
        }
        item.lanes[lane.id] = pieces;
      }
      reach = Math.max(reach, wordCuesOf(item, cuesHeld.get(row.slug) ?? [], rowBySlug, spec, said, laneOf(spec.spine.word_cues?.sounds), bySlug, clock));
      if (reach > item.seconds - item.pause) item.seconds = reach + item.pause; // the render: max(hold, speech, the end of the last sound) and then the pause
      cuts.push({ start: clock, seconds: item.seconds, firstWord: timed[0] ? timed[0].natural : null, lead: pictureLeadOf(row, spec.spine.seconds, rows.entry), anchor: overlay?.at ?? null });
      clock += item.seconds;
      made.push(item);
      items.push(item);
    }
    out.push({ id: g.id, slug: g.slug, title: g.title, start: 0, seconds: 0, items: made });
  }
  addCard("outro");
  // The pictures are cut from the sound (a picture lead brings one in before its words); the chapters, beds, overlays, marks and bands follow them.
  picturesOf(cuts, clock).forEach((cut, k) => {
    items[k].onScreen = cut;
  });
  for (const g of out) {
    const [first, last] = [g.items[0], g.items[g.items.length - 1]];
    g.start = first.onScreen.start;
    g.seconds = last.onScreen.start + last.onScreen.seconds - g.start;
  }
  const shown = items.map((i) => ({ ...i, start: i.onScreen.start, seconds: i.onScreen.seconds }));
  const beds: Record<string, Bed[]> = {};
  for (const lane of bedLanes) beds[lane.id] = bedsOf(lane, shown, rows, clock, bySlug(lane));
  const covers: Record<string, Cover[]> = {};
  for (const lane of lanes.filter((l) => l.cover)) covers[lane.id] = coversOf(lane.cover!, spec, shown, rows, lane.id);
  const marks: Record<string, Mark[]> = {};
  for (const lane of lanes.filter((l) => l.marks)) marks[lane.id] = marksOf(lane.marks!, spec, shown, rows, lane.id);
  const bands: Record<string, Band[]> = {};
  for (const band of spec.spine.bands ?? []) bands[band.id ?? band.field] = bandsOf(band, shown, rows, band.id ?? band.field);
  return { total: clock, groups: out, items, bands, beds, covers, marks };
}

/** A bed's level as the render plays it: the level set where the sound is named (a beat's, else its scene's or the story's) *replaces* the
 * sound's own, which replaces the lane's default. Not a product: a scene at 0.5 over a sound at 0.8 plays at 0.5. */
function bedLevel(lane: LaneSpec, sound: Row, named: number | null): number {
  return named ?? level(field(sound, lane.volume)) ?? lane.bed?.default_volume ?? 1;
}

/** How far the music goes down under a spoken line, set by the story: the same amounts as the render (about -9 dB and -18 dB), which this
 * must keep in step with (ScreenplayStudio render/storyrender/build.py: DUCK_DEPTH, DUCK_ATTACK, DUCK_RELEASE). */
export const DUCK_DEPTH = { light: 0.35, strong: 0.12 } as const;
export const DUCK_ATTACK = 0.2;
export const DUCK_RELEASE = 0.5;
const duckDepth = (value: unknown): number | null => (value === "light" || value === "strong" ? DUCK_DEPTH[value] : null);

/** How a bed block fades as the render plays it, each setting replacing the one before it. In: the sound's own `fade_in`, else the lane's
 * default; replaced by the film's start fade when the block starts the film; replaced by the entry's (story's) setting for the lane; replaced
 * by the first spine item's (the beat's) own. Out the same, with the end of the film and the last item. Neither is longer than half the block. */
function bedFades(spec: BedSpec, sound: Row, start: number, seconds: number, total: number, entry: Row | undefined, first?: Row, last?: Row): { fadeIn: number; fadeOut: number } {
  const set = (row: Row | undefined, key: string | undefined): number | null => {
    const v = row && key ? num(field(row, key)) : null;
    return v !== null && v > 0 ? v : null;
  };
  const sounds = (key: string | undefined, fallback: number | undefined) => Math.max(0, num(field(sound, key)) ?? fallback ?? 0);
  const atStart = start <= 1e-6;
  const atEnd = start + seconds >= total - 1e-6;
  const fadeIn = set(first, spec.item_fade_in) ?? set(entry, spec.entry_fade_in) ?? (atStart ? set(entry, spec.start_fade) : null) ?? sounds(spec.fade_in, spec.default_fade_in);
  const fadeOut = set(last, spec.item_fade_out) ?? set(entry, spec.entry_fade_out) ?? (atEnd ? set(entry, spec.end_fade) : null) ?? sounds(spec.fade_out, spec.default_fade_out);
  const half = seconds / 2;
  return { fadeIn: Math.min(fadeIn, half), fadeOut: Math.min(fadeOut, half) };
}

/** Peaks as many as a block can show: the most a waveform keeps (more is only a heavier page). */
export const WAVE_POINTS = 240;

/**
 * A recording's waveform from what a record holds: an array of peaks (0 to 1; larger numbers are taken relative to the largest), or the audiowaveform
 * JSON format ({bits, data: [min, max, min, max, …]}, as a tool like BBC's audiowaveform writes), either also as JSON text. Peaks are the loudest
 * of each stretch, cut down to at most `points` by taking the loudest of each group. Null when it is none of these, so a bad value draws nothing.
 */
export function wavePeaks(value: unknown, points: number = WAVE_POINTS): number[] | null {
  let v = value;
  if (typeof v === "string") {
    try {
      v = JSON.parse(v);
    } catch {
      return null;
    }
  }
  let peaks: number[];
  if (Array.isArray(v)) {
    if (!v.every((n) => typeof n === "number" && Number.isFinite(n))) return null;
    const top = Math.max(1, ...v.map((n) => Math.abs(n as number)));
    peaks = v.map((n) => Math.abs(n as number) / top);
  } else if (v && typeof v === "object" && Array.isArray((v as { data?: unknown }).data)) {
    const { data, bits } = v as { data: unknown[]; bits?: number };
    if (data.length < 2 || !data.every((n) => typeof n === "number" && Number.isFinite(n))) return null;
    const full = 2 ** ((Number.isInteger(bits) && (bits as number) > 1 ? (bits as number) : 8) - 1);
    peaks = [];
    for (let i = 0; i + 1 < data.length; i += 2) peaks.push(Math.min(1, Math.max(Math.abs(data[i] as number), Math.abs(data[i + 1] as number)) / full));
  } else {
    return null;
  }
  if (peaks.length < 2) return null;
  if (peaks.length <= points) return peaks.map((p) => Math.round(p * 1000) / 1000);
  const out: number[] = [];
  for (let i = 0; i < points; i++) {
    const from = Math.floor((i * peaks.length) / points);
    const to = Math.max(from + 1, Math.floor(((i + 1) * peaks.length) / points));
    out.push(Math.round(Math.max(...peaks.slice(from, to)) * 1000) / 1000);
  }
  return out;
}

/** The outline of a waveform as an SVG polygon's points in a 100-high box: the peaks above the middle line and the same below, so it is one shape. */
export function wavePolygon(peaks: number[]): string {
  const x = (i: number) => (i + 0.5).toFixed(2);
  const half = (p: number) => Math.max(0.6, p * 48); // a quiet stretch is still a line
  const top = peaks.map((p, i) => `${x(i)},${(50 - half(p)).toFixed(1)}`);
  const bottom = peaks.map((p, i) => `${x(i)},${(50 + half(p)).toFixed(1)}`).reverse();
  return [...top, ...bottom].join(" ");
}

/** The blocks of a bed lane: which sound runs under each item, merged across consecutive items that share one, at what level. */
function bedsOf(lane: LaneSpec, items: Item[], rows: Rows, total: number, sounds: Map<string, Row>): Bed[] {
  const spec = lane.bed!;
  const via = new Map((rows.via?.[lane.id] ?? []).map((r) => [r.slug, r] as const));
  const spine = new Map(rows.spine.map((r) => [r.id, r] as const));
  const make = (sound: Row, start: number, seconds: number, at: number | null, muffled: boolean, ids: string[]): Bed => ({
    id: sound.id,
    slug: sound.slug,
    title: sound.title,
    start,
    seconds,
    audio: assetUrl(sound, lane.audio, "audio/"),
    volume: bedLevel(lane, sound, at),
    loop: lane.loop ? field(sound, lane.loop) !== false : true,
    muffled,
    items: ids,
    steps: [],
    ...bedFades(spec, sound, start, seconds, total, rows.entry),  // a block's fades are worked out again when it is final (its first and last items)
    duck: rows.entry && !spec.via && spec.on !== "spine" ? duckDepth(field(rows.entry, spec.duck)) : null,
  });
  if (!spec.via && spec.on !== "spine") {
    const sound = rows.entry ? sounds.get(str(field(rows.entry, spec.field))) : undefined;
    if (!sound || total <= 0) return [];
    const whole = make(sound, 0, total, level(field(rows.entry!, spec.volume)), false, items.map((i) => i.id));
    whole.steps = stepsOf(spec, items, rows, whole.volume);
    return [whole];
  }
  // The story's own bed under the whole film, which plays together with the beds of items and scenes (the render layers them).
  const storySound = spec.entry_field && rows.entry ? sounds.get(str(field(rows.entry, spec.entry_field))) : undefined;
  const everywhere = storySound && total > 0 ? [make(storySound, 0, total, level(field(rows.entry!, spec.entry_volume)), false, items.map((i) => i.id))] : [];
  if (everywhere[0]) {
    everywhere[0].steps = storyBedSteps(spec, items, spine, via, everywhere[0].volume);
    everywhere[0].whole = true;
  }
  // The render's two layers: the scene's bed under every beat of the scene, and a beat's own sound as a second bed over it for that beat.
  const out: Bed[] = [];
  const over: Bed[] = [];
  const lay = (list: Bed[], item: Item, sound: Row, at: number | null, muffled: boolean) => {
    const last = list[list.length - 1];
    if (last && last.slug === sound.slug && last.volume === bedLevel(lane, sound, at) && last.muffled === muffled && last.start + last.seconds >= item.start - 1e-6) {
      last.seconds = item.start + item.seconds - last.start;
      last.items.push(item.id);
    } else {
      list.push(make(sound, item.start, item.seconds, at, muffled, [item.id]));
    }
  };
  const namedOf = (row: Row) => (spec.via ? via.get(str(field(row, spec.via))) : row);
  const sceneSound = (row: Row) => str(field(namedOf(row) ?? ({} as Row), spec.field));
  // The beat's own sound when it names one other than its scene's (naming the scene's own is the scene's bed, never the same sound twice).
  const ownSound = (row: Row) => {
    const own = spec.item_field ? str(field(row, spec.item_field)) : "";
    return own && own !== sceneSound(row) ? own : "";
  };
  for (const item of items) {
    const row = spine.get(item.id);
    if (!row) continue;
    const named = namedOf(row);
    const own = ownSound(row);
    const muffled = !!(named && spec.muffled && field(named, spec.muffled) === true);
    const scene = named ? sounds.get(sceneSound(row)) : undefined;
    // The beat's level is the scene bed's for that beat only when the beat has no sound of its own; else the scene's bed runs on at the scene's.
    if (scene) lay(out, item, scene, (own ? null : level(field(row, spec.item_volume))) ?? level(field(named!, spec.volume)), muffled);
    const mine = own ? sounds.get(own) : undefined;
    const at = level(field(row, spec.item_volume));
    const heard = HEARD.get(str(field(row, spec.item_heard)).trim().toLowerCase()) ?? muffled;
    if (mine && bedLevel(lane, mine, at) > 0) lay(over, item, mine, at, heard); // a beat's bed at level 0 is not played
  }
  for (const b of over) b.over = true;
  const ends = (b: Bed, under: boolean) => [b.items[0], b.items[b.items.length - 1]].map((id) => spine.get(id)).map((r) => (under && r && ownSound(r) ? undefined : r));
  for (const b of [...out, ...over]) {
    const sound = sounds.get(b.slug);
    // A beat's own fades are its own bed's: the scene's bed fades by the scene's sound and the story where the beat lays a sound over it.
    const [first, last] = ends(b, !b.over);
    if (sound) Object.assign(b, bedFades(spec, sound, b.start, b.seconds, total, rows.entry, first, last));
  }
  return [...everywhere, ...out, ...over];
}

/** How a beat's own bed is heard, from its `item_heard` field, as the render reads it (ScreenplayStudio marvin_pull.py: HEARD); empty follows its scene's. */
const HEARD = new Map([["muffled", true], ["clear", false]]);

/** The bands of one band spec: runs of consecutive items whose row holds the same non-empty value. */
function bandsOf(spec: NonNullable<SpineSpec["bands"]>[number], items: Item[], rows: Rows, key: string): Band[] {
  const spine = new Map(rows.spine.map((r) => [r.id, r] as const));
  const named = new Map((rows.bands?.[key] ?? []).map((r) => [r.slug, r] as const));
  const out: Band[] = [];
  let before: string | null = null; // the item just before, so a stretch only continues across neighbours
  for (const item of items) {
    if (item.card) {
      before = item.id; // a card is no beat: it ends a stretch
      continue;
    }
    const value = str(field(spine.get(item.id) ?? ({} as Row), spec.field)).trim();
    const last = out[out.length - 1];
    if (value && last && last.slug === value && last.items[last.items.length - 1] === before) {
      last.seconds = item.start + item.seconds - last.start;
      last.items.push(item.id);
    } else if (value) {
      const entry = named.get(value);
      out.push({ id: entry?.id ?? null, slug: value, title: entry?.title || value, start: item.start, seconds: item.seconds, items: [item.id] });
    }
    before = item.id;
  }
  return out;
}

/** A card the entry asks for: its title (a card with no title does not exist) and how long it lasts. */
function cardOf(spec: CardSpec | undefined, entry: Row | undefined, kind: "intro" | "outro"): { title: string; seconds: number; label: string } | null {
  if (!spec || !entry) return null;
  const title = str(field(entry, spec.title)).trim();
  if (!title) return null;
  const set = num(field(entry, spec.seconds));
  return { title, seconds: set !== null && set > 0 ? set : (spec.default_seconds ?? 2.5), label: spec.label ?? (kind === "intro" ? "Title card" : "End card") };
}

/**
 * The story's own bed turned down, or heard from inside, where the story is: for each item its level is the item's own (a beat's), else the entry
 * the item names' (a scene's), else the story's (`base`); it is muffled when that entry says so. Consecutive items alike are one step, and each step
 * says who set its level. Nothing (no steps) when no item or scene changes either, so a bed nobody adjusts is drawn as before.
 */
function storyBedSteps(spec: BedSpec, items: Item[], spine: Map<string, Row>, via: Map<string, Row>, base: number): BedStep[] {
  if (!spec.entry_item_volume && !spec.entry_via_volume && !spec.entry_via_muffled) return [];
  const runs: BedStep[] = [];
  for (const item of items) {
    const row = spine.get(item.id);
    const named = row && spec.via ? via.get(str(field(row, spec.via))) : undefined;
    const own = row && spec.entry_item_volume ? level(field(row, spec.entry_item_volume)) : null;
    const scene = named && spec.entry_via_volume ? level(field(named, spec.entry_via_volume)) : null;
    const volume = own ?? scene ?? base;
    const source: BedSource = own !== null ? "beat" : scene !== null ? "scene" : "story";
    const by = own !== null ? row?.title || item.title : scene !== null && named ? named.title : undefined;
    const muffled = !!(named && spec.entry_via_muffled && field(named, spec.entry_via_muffled) === true);
    const last = runs[runs.length - 1];
    if (last && Math.abs(last.volume - volume) < 1e-9 && last.source === source && last.muffled === muffled && last.by === by) last.seconds = item.start + item.seconds - last.start;
    else runs.push({ start: item.start, seconds: item.seconds, volume, source, by, muffled });
  }
  const changed = runs.some((r) => r.source !== "story" || r.muffled);
  return changed ? runs : [];
}

/** A story-wide bed's level over time when spine items set one of their own: runs at one level each, or none when no item changes it. */
function stepsOf(spec: BedSpec, items: Item[], rows: Rows, base: number): BedStep[] {
  if (!spec.item_volume) return [];
  const spine = new Map(rows.spine.map((r) => [r.id, r] as const));
  const runs: BedStep[] = [];
  const ends: { first: Row | undefined; last: Row | undefined }[] = []; // the first and last item of each run, whose own ramp seconds say how its edges ease
  for (const item of items) {
    const row = spine.get(item.id);
    const volume = (row ? level(field(row, spec.item_volume)) : null) ?? base;
    const last = runs[runs.length - 1];
    if (last && Math.abs(last.volume - volume) < 1e-9) {
      last.seconds = item.start + item.seconds - last.start;
      ends[ends.length - 1].last = row;
    } else {
      runs.push({ start: item.start, seconds: item.seconds, volume });
      ends.push({ first: row, last: row });
    }
  }
  const set = (row: Row | undefined, key: string | undefined) => {
    const v = row && key ? Number(field(row, key)) : NaN;
    return Number.isFinite(v) && v > 0 ? v : null;
  };
  for (let i = 1; i < runs.length; i++) {
    const wanted = set(ends[i].first, spec.item_ramp_in) ?? set(ends[i - 1].last, spec.item_ramp_out) ?? spec.ramp ?? 0;
    const ramp = wanted > 0 ? Math.max(0.05, Math.min(wanted, runs[i - 1].seconds, runs[i].seconds)) : 0; // as the render: never longer than the shorter run beside it
    if (ramp > 0) runs[i].ramp = ramp;
  }
  return runs.length > 1 || (runs.length === 1 && Math.abs(runs[0].volume - base) > 1e-9) ? runs : [];
}

/** One item's choice in a marks lane, drawn across the item's width. */
export interface Mark {
  /** The value chosen (a select's value), or "" for an item's own exact setting (`custom`). */
  value: string;
  label: string;
  icon: string;
  /** The entry type it was set on: the spine's, the `via`'s or the view's own; "" for a custom one. */
  from: string;
  /** True for what the lane's `other` field says: the item has its own exact setting, which wins over the choice. */
  custom: boolean;
  start: number;
  seconds: number;
  item: string;
  /** The entry the choice came from (its slug: the scene's or the story's, "" for the item's own), so two scenes that both choose it stay two blocks. */
  source: string;
  /** How many consecutive items this block covers (1 unless merged). */
  count: number;
}

/** The file name of a published address, without its query: only for an asset with no title, since a published name is often just an id. */
const fileName = (url: string): string => decodeURIComponent(url.split("?")[0].split("/").pop() ?? url);

/** The cover blocks of a cover lane: for each item the video its own field, else its `via` entry's, else the view's entry's names. */
function coversOf(spec: CoverSpec, view: TimelineSpec, items: Item[], rows: Rows, laneId: string): Cover[] {
  const via = new Map((rows.via?.[laneId] ?? []).map((r) => [r.slug, r] as const));
  const spine = new Map(rows.spine.map((r) => [r.id, r] as const));
  const out: Cover[] = [];
  for (const item of items) {
    if (item.card) continue; // a card has no overlay of its own: the render gives it none
    const row = spine.get(item.id);
    const named = row && spec.via ? via.get(str(field(row, spec.via))) : undefined;
    if (row && spec.card) {
      const said = str(field(row, spec.card.title)).trim() || str(field(row, spec.card.text)).trim();
      if (said) {
        // The card comes in after its delay and takes the place of any overlay file for this item (the render hands it on as the item's overlay).
        const set = spec.card.delay ? Number(field(row, spec.card.delay)) : NaN;
        const delay = Math.min(Math.max(Number.isFinite(set) && set > 0 ? set : (spec.card.default_delay ?? 0), 0), Math.max(item.seconds - 0.1, 0));
        out.push({ url: "", name: `${spec.card.name ?? "Card"}: ${said}`, from: view.spine.entry_type, blend: "normal", opacity: 1, start: item.start + delay, seconds: item.seconds - delay, items: [item.id], card: true });
        continue;
      }
    }
    const tiers: [Row | undefined, string][] = [
      [row, view.spine.entry_type],
      [named, spec.entry_type ?? ""],
      [rows.entry, view.entry_type],
    ];
    let found: Cover | null = null;
    for (const [owner, from] of tiers) {
      if (!owner) continue;
      const blend = str(field(owner, spec.blend));
      if (blend === "none") break;
      const asset = assetOf(owner, spec.field, "video/") ?? assetOf(owner, spec.field, "image/"); // a video, or a picture or GIF
      if (!asset) continue;
      const url = asset.publicUrl;
      found = { url, name: asset.name ?? fileName(url), from, blend: blend || "normal", opacity: level(field(owner, spec.opacity)) ?? 1, start: item.start, seconds: item.seconds, items: [item.id] };
      break;
    }
    if (!found) continue;
    const last = out[out.length - 1];
    if (last && last.url === found.url && last.blend === found.blend && last.opacity === found.opacity && last.from === found.from && last.start + last.seconds >= item.start - 1e-6) {
      last.seconds = item.start + item.seconds - last.start;
      last.items.push(item.id);
    } else out.push(found);
  }
  return out;
}

/** Whether a lane entry is set aside by the lane's `off` field (a checked box; "true" and "yes" read the same, as a form may store them). */
const isOff = (row: Row, lane: LaneSpec): boolean => {
  const v = lane.off ? field(row, lane.off) : null;
  return v === true || v === "true" || v === "yes";
};

const filled = (value: unknown): boolean => value !== null && value !== undefined && value !== "" && !(typeof value === "object" && Object.keys(value as object).length === 0);

/** A value as words: its label when the lane names one, else the value with its dashes and underscores spaced and its first letter a capital. */
const wordsOf = (value: string, labels: Record<string, string> | undefined): string => labels?.[value] ?? (value.replace(/[-_]+/g, " ").trim().replace(/^./, (c) => c.toUpperCase()) || value);

/** The marks of a marks lane: for each item its own choice, else its own `other` setting (shown as custom), else the choice its `via` entry's or the view's
 * entry names. What an item chose by name beats numbers it also holds; its own numbers beat what its scene or the story chose. */
function marksOf(spec: MarksSpec, view: TimelineSpec, items: Item[], rows: Rows, laneId: string): Mark[] {
  const via = new Map((rows.via?.[laneId] ?? []).map((r) => [r.slug, r] as const));
  const spine = new Map(rows.spine.map((r) => [r.id, r] as const));
  const out: Mark[] = [];
  for (const item of items) {
    if (item.card) continue; // a card is a title, not a shot: it has no camera
    const row = spine.get(item.id);
    const own = { start: item.start, seconds: item.seconds, item: item.id };
    const named = row && spec.via ? via.get(str(field(row, spec.via))) : undefined;
    const choice = (owner: Row | undefined, from: string, inherited: boolean): Mark | null => {
      const value = owner ? str(field(owner, spec.field)).trim() : "";
      return value ? { value, label: wordsOf(value, spec.labels), icon: spec.icons?.[value] ?? "", from, custom: false, source: inherited && owner ? owner.slug : "", count: 1, ...own } : null;
    };
    const written: Mark | null = row && spec.other && filled(field(row, spec.other.field)) ? { value: "", label: spec.other.label, icon: "", from: "", custom: true, source: "", count: 1, ...own } : null;
    const found = written ?? choice(row, view.spine.entry_type, false) ?? choice(named, spec.entry_type ?? "", true) ?? choice(rows.entry, view.entry_type, true);
    if (!found) continue;
    const last = out[out.length - 1];
    const runs = !found.custom && spec.merge?.includes(found.value);
    if (runs && last && !last.custom && last.value === found.value && last.from === found.from && last.source === found.source && last.start + last.seconds >= found.start - 1e-6) {
      last.seconds = found.start + found.seconds - last.start; // the same choice, from the same place, on the next item: one block
      last.count += 1;
    } else out.push(found);
  }
  return out;
}

function pieceOf(row: Row, lane: LaneSpec, seconds: number, estimated: boolean, start: number, at: number | null): Piece {
  return {
    id: row.id,
    slug: row.slug,
    title: row.title,
    text: str(field(row, lane.text)),
    who: str(field(row, lane.who)),
    status: str(field(row, lane.status)),
    start,
    seconds,
    estimated,
    unmeasured: estimated && !!assetUrl(row, lane.audio, "audio/"),
    audio: assetUrl(row, lane.audio, "audio/"),
    wave: wavePeaks(field(row, lane.waveform)),
    volume: level(field(row, lane.volume)),
    at,
    nudge: within(num(field(row, lane.nudge)), -MAX_NUDGE, MAX_NUDGE) ?? 0,
    natural: start,
    together: lane.simultaneous ? field(row, lane.simultaneous) === true : false,
    words: wordTimings(row, lane),
  };
}

/**
 * An item's cues on words (`spine.word_cues`), as the render places them (marvin_pull `_cues`, `word_place`): each on a piece laid so far, at the
 * end of the word before it. A cue's sound joins the sounds lane at that time (its own level replacing the sound's, as a placed cue's does) and
 * counts toward the item's length when it has a take; one with none is drawn as needing one. A cue on a piece that is not laid is left out, as the
 * render leaves out a cue on a line with no take. A look, a change to the mix or emphasis rides on the mark and lengthens nothing. `held` are
 * the cues whose line this item holds, wherever their row is stored (lib/cueHomes.ts `cuesByHolder`, as the render applies them from Studio
 * v221): one stored on another beat is marked with it. Returns how far into the item its last cue sound runs.
 */
function wordCuesOf(item: Item, held: readonly StoredCue[], rowBySlug: ReadonlyMap<string, Row>, spec: TimelineSpec, said: Map<string, Piece>, sounds: LaneSpec | undefined, bySlug: (lane: LaneSpec) => Map<string, Row>, clock: number): number {
  const wc = spec.spine.word_cues;
  if (!wc) return 0;
  const known = sounds ? bySlug(sounds) : new Map<string, Row>();
  const marks: CueMark[] = [];
  let reach = 0;
  for (const { cue, stored } of held) {
    const piece = said.get(cue.line);
    const store = rowBySlug.get(stored);
    if (!piece || !store) continue;
    const after = wordAt(piece, cue.word, true);
    const next = wordAt(piece, cue.word, false);
    const chips = chipsOf(piece.text, piece.words);
    const target = cue.sound ? known.get(cue.sound) : undefined;
    const at = piece.start + after.at;
    const heard = !!target && !!assetUrl(target, sounds?.audio, "audio/");
    marks.push({
      piece: piece.id,
      word: cue.word,
      text: cue.word > 0 ? (chips[Math.min(cue.word, chips.length) - 1] ?? "") : "",
      at,
      picAt: piece.start + next.at,
      estimated: after.estimated || piece.estimated,
      sound: cue.sound ? { slug: cue.sound, title: target?.title ?? cue.sound, heard } : null,
      camera: cue.camera ?? null,
      pic: cue.pic ?? null,
      nudge: cue.nudge ?? 0,
      ...(cue.look ? { look: cue.look } : {}),
      ...(cue.mix ? { mix: cue.mix } : {}),
      ...(cue.mix && kindOf("mix", cue.mix.kind) ? { mixSpan: { start: Math.max(at + (cue.nudge ?? 0), 0) + 0, seconds: mixSeconds(cue.mix) } } : {}),
      ...(cue.emphasis ? { emphasis: cue.emphasis } : {}),
      ...(stored !== item.slug ? { stored: { id: store.id, slug: store.slug, title: str(field(store, spec.spine.order)) || store.title } } : {}),
    });
    if (!sounds || !target) continue;
    const length = pieceSeconds(target, sounds);
    const nudge = cue.nudge ?? 0; // this much later (or earlier) than its word: the render plays the cue's sound there
    const natural = at;
    // Before its beat when nudged that far, over the beat before; never before the film starts (Studio manifest.plan: max(word + nudge, 0)).
    const offset = Math.max(at + nudge - clock, -clock) + 0;
    const sound = pieceOf(target, sounds, length?.seconds ?? 0, length?.estimated ?? false, clock + offset, Number(offset.toFixed(3)));
    sound.nudge = nudge;
    sound.natural = natural;
    sound.slot = { item: store.id, field: wc.field, index: cue.position ?? 0, ref: cue.line }; // a drag writes to the beat that stores it
    if (cue.volume !== undefined) sound.volume = cue.volume;
    sound.cue = { line: piece.title, word: cue.word, text: marks[marks.length - 1].text };
    item.lanes[sounds.id] = [...(item.lanes[sounds.id] ?? []), sound];
    if (heard && length) reach = Math.max(reach, offset + length.seconds);
  }
  if (marks.length) item.cues = marks;
  return reach;
}

/** An item that comes in at a word of a piece already laid (`spine.starts_during`), as the render places it (marvin_pull: _starts_during): at the
 * start of the word after `word` words. Undefined for any other item, and for one whose piece is not laid before it (left out, or not there): that
 * one is an ordinary item. A piece with no take is placed by its text, where the render would play the item as one of its own. */
function overlayOf(row: Row, spine: SpineSpec, said: Map<string, Piece>): Item["overlay"] {
  const during = field(row, spine.starts_during);
  if (!during || typeof during !== "object") return undefined;
  const piece = said.get(str((during as Record<string, unknown>).line));
  if (!piece) return undefined;
  const word = Math.max(0, Math.floor(num((during as Record<string, unknown>).word) ?? 0));
  const place = wordAt(piece, word, false);
  const said_ = piece.words?.map((w) => w.text) ?? piece.text.split(/\s+/).filter(Boolean);
  return { piece: piece.slug, title: piece.title, word, text: said_[word] ?? "", at: piece.start + place.at, estimated: place.estimated || piece.estimated };
}

function groupRows(spine: SpineSpec, rows: Rows): { id: string | null; slug: string | null; title: string; rows: Row[] }[] {
  const sorted = [...rows.spine].sort(byOrder(spine.order));
  if (!spine.group) return [{ id: null, slug: null, title: "", rows: sorted }];
  const groups = [...(rows.groups ?? [])].sort(byOrder(spine.group.order)).map((g) => ({ id: g.id as string | null, slug: g.slug as string | null, title: g.title, rows: [] as Row[] }));
  const known = new Map(groups.map((g) => [g.slug, g]));
  const stray: Row[] = [];
  for (const row of sorted) (known.get(str(field(row, spine.group.field))) ?? { rows: stray }).rows.push(row);
  const out = groups.filter((g) => g.rows.length);
  if (stray.length) out.push({ id: null, slug: null, title: "", rows: stray });
  return out;
}

/** Pixels per second so the whole timeline fills `width`, never so few that an item falls under its minimum card. */
/** A stretch of an item where its lane is quiet: what the renderer adds around the pieces, or the whole item when nothing is timed. */
export interface Quiet {
  id: string;
  kind: "lead" | "gap" | "tail" | "hold";
  start: number;
  seconds: number;
}

const QUIET_WORDS: Record<Quiet["kind"], string> = {
  lead: "lead-in: quiet before the first line",
  gap: "gap: the pause between two lines",
  tail: "tail: room after the last line, before the next beat",
  hold: "hold: nothing is timed, so the beat holds",
};
export const quietWords = (kind: Quiet["kind"]): string => QUIET_WORDS[kind];

/** The silences the renderer adds in a lane that sits inside the spine items (lines): lead before the first piece, gap between pieces, tail after the last, or the item's whole hold when no piece is timed. Placed and bed lanes have none. */
export function quiets(allItems: Item[], lane: LaneSpec): Quiet[] {
  if (!lane.in || lane.placed || lane.bed) return [];
  const items = allItems.filter((i) => !i.card); // a title or end card has no lines to leave room around
  const out: Quiet[] = [];
  const add = (id: string, kind: Quiet["kind"], start: number, seconds: number) => {
    if (seconds > 0.005) out.push({ id, kind, start, seconds });
  };
  for (const item of items) {
    const timed = (item.lanes[lane.id] ?? []).filter((p) => p.seconds > 0).sort((a, b) => a.start - b.start);
    if (!timed.length) {
      add(`${item.id}:hold`, "hold", item.start, item.seconds);
      continue;
    }
    add(`${item.id}:lead`, "lead", item.start, timed[0].start - item.start);
    // From where the pieces so far end: a nudge can lay one over another, or make an earlier one end last, and that is no quiet.
    let end = timed[0].start + timed[0].seconds;
    timed.slice(1).forEach((p, i) => {
      add(`${item.id}:gap${i}`, "gap", end, p.start - end);
      end = Math.max(end, p.start + p.seconds);
    });
    add(`${item.id}:tail`, "tail", end, item.start + item.seconds - end);
  }
  return out;
}

/** The outline of a nudged piece where it would play without its nudge, and the arrow from there to where it plays now. */
export interface Ghost {
  piece: string;
  /** Where it would start with no nudge of its own, and its length. */
  start: number;
  seconds: number;
  nudge: number;
  /** Where it starts now (the arrow's end) and the row it is drawn on. */
  to: number;
  toRow: number;
  /** The row the outline goes on: the first row its slot is clear on, else row 0 (`free` false: it is drawn behind what is there). */
  row: number;
  free: boolean;
}

const EPS = 1e-6;
const clash = (a: { start: number; seconds: number }, start: number, seconds: number) => a.start < start + seconds - EPS && start < a.start + a.seconds - EPS;

/**
 * Where each nudged piece of a lane would have played (its natural start, for its length) so the drawing can show where it moved from. Pure
 * drawing: the rows are the lane's own (`stackRows`), and nothing here changes them. A piece with no nudge, no length, or one spoken together with
 * the piece before (dual dialogue: no slot of its own) has none.
 */
export function nudgeGhosts(pieces: readonly Piece[], rows: readonly number[]): Ghost[] {
  const height = Math.max(-1, ...rows) + 1;
  const out: Ghost[] = [];
  pieces.forEach((p, i) => {
    if (!p.nudge || p.together || p.seconds <= 0) return;
    const taken = (r: number) => pieces.some((q, j) => rows[j] === r && q.seconds > 0 && clash(q, p.natural, p.seconds)); // its own block counts: the outline never sits on it
    const row = [...Array(height).keys()].find((r) => !taken(r));
    out.push({ piece: p.id, start: p.natural, seconds: p.seconds, nudge: p.nudge, to: p.start, toRow: rows[i] ?? 0, row: row ?? 0, free: row !== undefined });
  });
  return out;
}

/** A stretch where two pieces of a lane play at once: from the later one's start to where the first of the two ends. */
export interface Overlap {
  start: number;
  seconds: number;
  /** The piece that started first and the one laid over it. */
  earlier: string;
  later: string;
  /** The rows the two are drawn on, the higher (smaller) first. */
  rows: [number, number];
}

/** Every pair of pieces of a lane that play at once (a nudge laid one over another, or two spoken together); pieces that only touch do not count.
 * In time order of where each overlap starts. */
export function overlapsIn(pieces: readonly Piece[], rows: readonly number[]): Overlap[] {
  const timed = [...pieces.keys()].filter((i) => pieces[i].seconds > 0).sort((a, b) => pieces[a].start - pieces[b].start || a - b);
  const out: Overlap[] = [];
  timed.forEach((b, n) => {
    for (const a of timed.slice(0, n)) {
      const [p, q] = [pieces[a], pieces[b]];
      const end = Math.min(p.start + p.seconds, q.start + q.seconds);
      if (end - q.start <= EPS) continue;
      const [r1, r2] = [rows[a] ?? 0, rows[b] ?? 0];
      out.push({ start: q.start, seconds: end - q.start, earlier: p.id, later: q.id, rows: [Math.min(r1, r2), Math.max(r1, r2)] });
    }
  });
  return out.sort((x, y) => x.start - y.start);
}

/**
 * The row each piece of a lane goes on, so overlapping pieces (two sound effects at the same moment) stack instead of sitting on top of each
 * other: in time order, each takes the first row that is free by its start. `minSeconds` stops a very short piece from sharing a row with a
 * neighbour whose label it would hide. The rows come back in the order the pieces were given.
 */
export function stackRows(pieces: { start: number; seconds: number }[], minSeconds = 0.8): number[] {
  const rows: number[] = [];
  const free: number[] = []; // for each row, when it is free again
  [...pieces.keys()]
    .sort((a, b) => pieces[a].start - pieces[b].start || b - a)
    .forEach((i) => {
      const p = pieces[i];
      let r = free.findIndex((end) => end <= p.start + 1e-6);
      if (r < 0) r = free.length;
      free[r] = p.start + Math.max(p.seconds, minSeconds);
      rows[i] = r;
    });
  return rows;
}

/** The rows of a bed lane's blocks, layered like a mixer when a beat lays its own bed over its scene's: the most specific on top, the beats'
 * own beds (`over`) on the top rows, the scenes' beds below them, the story's bed under the whole film (`whole`) at the bottom, each layer
 * stacked in itself as `stackRows` does. A lane with no beat bed is laid out exactly as before: `stackRows(beds, 0)`. */
export function stackBeds(beds: { start: number; seconds: number; over?: boolean; whole?: boolean }[]): number[] {
  if (!beds.some((b) => b.over)) return stackRows(beds, 0);
  const all = [...beds.keys()];
  const layers = [all.filter((i) => beds[i].over), all.filter((i) => !beds[i].over && !beds[i].whole), all.filter((i) => beds[i].whole)];
  const rows: number[] = [];
  let top = 0;
  for (const layer of layers) {
    const inLayer = stackRows(layer.map((i) => beds[i]), 0);
    for (const [n, i] of layer.entries()) rows[i] = top + inLayer[n];
    top += layer.length ? Math.max(...inLayer) + 1 : 0;
  }
  return rows;
}

export function scale(items: { seconds: number }[], total: number, width: number): number {
  if (total <= 0 || width <= 0) return 0;
  const fit = width / total;
  const shortest = Math.min(...items.map((i) => i.seconds).filter((s) => s > 0), Infinity);
  return shortest === Infinity ? fit : Math.max(fit, MIN_ITEM_PX / shortest);
}

/** The narrowest the strip may be (px) so the shortest item still gets its minimum card; wider than this it fills whatever room there is. */
export function minInnerWidth(items: { seconds: number }[], total: number, minPx: number = MIN_ITEM_PX): number {
  const shortest = Math.min(...items.map((i) => i.seconds).filter((s) => s > 0), Infinity);
  return shortest === Infinity || total <= 0 ? 0 : Math.ceil((minPx / shortest) * total);
}

/** The heights (px) a person can give the strip's pictures: the picture takes the height and, when the story names its shape, the width that shape needs. */
export const PICTURE_SIZES: Record<string, number> = { s: 120, m: 180, l: 260 };

/** The narrowest a beat's card may be at a picture height: the room one frame in the story's shape needs (a tall Short is narrow, a wide video is wide), never under the usual minimum. */
export const cardMinPx = (height: number, shape: number | null): number => Math.max(MIN_ITEM_PX, shape ? Math.round(height * shape) : 0);

/** A position or length in seconds as a CSS percentage of the whole timeline (the strip is laid out in percent, so it fills its container). */
export const percent = (seconds: number, total: number): string => `${total > 0 ? Number(((seconds / total) * 100).toFixed(4)) : 0}%`;

export const widthOf = (seconds: number, pxPerSecond: number): number => Math.max(MIN_ITEM_PX, Math.round(seconds * pxPerSecond));

const TICK_STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300];

/** Ruler ticks: a step chosen so there are about `want` of them, from the first to just past the end. */
export function ticks(total: number, want = 10): number[] {
  if (total <= 0) return [0];
  const step = TICK_STEPS.find((s) => total / s <= want) ?? TICK_STEPS[TICK_STEPS.length - 1];
  const out: number[] = [];
  for (let t = 0; t <= total + 1e-9; t += step) out.push(Number(t.toFixed(3)));
  return out;
}

export const ZOOM_LEVELS = [1, 2, 4, 8] as const;

/** Ruler ticks for every zoom level at once: each tick says at which levels it shows (a finer step at a higher zoom), so the page can
 * render them all and switch with CSS. Level 1 is the strip fitted to the page; level n is n pages wide. */
export function tickLevels(total: number, want = 10): { t: number; levels: number[] }[] {
  const byLevel = new Map<number, Set<number>>();
  for (const level of ZOOM_LEVELS) for (const t of ticks(total, want * level)) byLevel.set(t, (byLevel.get(t) ?? new Set()).add(level));
  return [...byLevel.entries()].sort((a, b) => a[0] - b[0]).map(([t, levels]) => ({ t, levels: [...levels].sort((a, b) => a - b) }));
}

/** Unlabelled marks between the ruler's numbered ticks (whole seconds when there is room), for every zoom level at once, as `tickLevels` does: each says at
 * which levels it shows. A mark that is a numbered tick at a level is left out of that level. The step is the smallest that divides the numbered step evenly
 * and keeps the marks under about six per numbered tick, so a 60 s story shows a mark every second and a long film every few. */
export function minorTickLevels(total: number, want = 10): { t: number; levels: number[] }[] {
  const byT = new Map<number, number[]>();
  if (total <= 0) return [];
  for (const level of ZOOM_LEVELS) {
    const target = want * level;
    const major = TICK_STEPS.find((s) => total / s <= target) ?? TICK_STEPS[TICK_STEPS.length - 1];
    const minor = TICK_STEPS.find((m) => m < major && Math.abs(major / m - Math.round(major / m)) < 1e-9 && total / m <= target * 6);
    if (minor === undefined) continue;
    const isMajor = new Set(ticks(total, target));
    for (let t = 0; t <= total + 1e-9; t += minor) {
      const at = Number(t.toFixed(3));
      if (!isMajor.has(at)) byT.set(at, [...(byT.get(at) ?? []), level]);
    }
  }
  return [...byT.entries()].sort((a, b) => a[0] - b[0]).map(([t, levels]) => ({ t, levels }));
}

export interface Progress {
  label: string;
  done: number;
  total: number;
}

/** What is in place: items with a picture (when the spine has one), each lane's pieces with a recording (when the lane has audio). */
export function progress(spec: TimelineSpec, laid: Layout, noun = { item: "beat", items: "beats" }): Progress[] {
  const out: Progress[] = [];
  if (spec.spine.picture) {
    const beats = laid.items.filter((i) => !i.card); // a title or end card is not a beat
    out.push({ label: `${beats.length === 1 ? noun.item : noun.items} with a picture`, done: beats.filter((i) => i.picture).length, total: beats.length });
  }
  for (const lane of (spec.lanes ?? []).filter((l) => l.audio)) {
    // A bed lane counts its blocks with a take; the others their pieces. A lane with nothing in it says nothing.
    const sounds: { audio: string | null }[] = lane.bed ? (laid.beds[lane.id] ?? []) : laid.items.flatMap((i) => i.lanes[lane.id] ?? []);
    if (sounds.length === 0) continue;
    out.push({ label: lane.bed ? `${lane.title.toLowerCase()} with a take` : `${lane.title.toLowerCase()} recorded`, done: sounds.filter((p) => p.audio).length, total: sounds.length });
  }
  return out;
}

export const progressLine = (steps: Progress[]): string => steps.map((p) => `${p.done} of ${p.total} ${p.label}`).join(" · ");

/** What the player walks: each item, then each timed piece in it, in order, with where it starts and what (if anything) plays. */
export interface Cue {
  item: string;
  piece: string | null;
  /** The lane the piece is in (so its lane's mute applies); null for a silence. */
  lane: string | null;
  start: number;
  seconds: number;
  audio: string | null;
}

/** What plays *over* the cues: each placed sound at its offset and each bed under its stretch, with its level; `seconds` 0 means "to the end
 * of the file" (a sound with no declared length). */
export interface Overlay {
  id: string;
  lane: string;
  start: number;
  seconds: number;
  audio: string;
  volume: number;
  loop: boolean;
  /** Where the file's own start falls on the timeline, when that is earlier than `start` (a bed cut into steps keeps playing through them). */
  origin?: number;
  /** The bed's whole block and its fades: rising from nothing over `in` at `from`, falling to nothing over `out` before `to`. */
  fade?: { from: number; to: number; in: number; out: number };
  /** Going down to `depth` of its level under each speech window (start, end), easing as the render does. */
  duck?: { depth: number; windows: [number, number][] };
}

/** When someone is heard speaking: the spans of the timed lanes' pieces that have a take, joined when closer than one ramp down and up (so the
 * music does not pump in a short pause). Pieces with no take are silent in Play, so nothing ducks for them. */
export function speechWindows(laid: Layout, lanes: LaneSpec[]): [number, number][] {
  const timed = lanes.filter((l) => l.in && (l.seconds || l.estimate_from)).map((l) => l.id);
  const spans = laid.items
    .flatMap((i) => timed.flatMap((id) => i.lanes[id] ?? []))
    .filter((p) => p.audio && p.seconds > 0)
    .map((p): [number, number] => [p.start, p.start + p.seconds])
    .sort((a, b) => a[0] - b[0]);
  const joined: [number, number][] = [];
  for (const [begin, end] of spans) {
    const last = joined[joined.length - 1];
    if (last && begin - last[1] < DUCK_ATTACK + DUCK_RELEASE) last[1] = Math.max(last[1], end);
    else joined.push([begin, end]);
  }
  return joined;
}

const clip01 = (x: number): number => Math.max(0, Math.min(1, x));

/** The share of its level an overlay plays at, at time `t`: 1, less its fade at either end of its block and its dip under speech. */
export function gainAt(o: Overlay, t: number): number {
  let gain = 1;
  if (o.fade) {
    if (o.fade.in > 0) gain = Math.min(gain, clip01((t - o.fade.from) / o.fade.in));
    if (o.fade.out > 0) gain = Math.min(gain, clip01((o.fade.to - t) / o.fade.out));
  }
  if (o.duck) {
    let down = 0;
    for (const [begin, end] of o.duck.windows) down += Math.min(clip01((t - (begin - DUCK_ATTACK)) / DUCK_ATTACK), clip01((end + DUCK_RELEASE - t) / DUCK_RELEASE));
    gain *= 1 - (1 - o.duck.depth) * Math.min(1, down);
  }
  return gain;
}

export function overlays(laid: Layout, lanes: LaneSpec[]): Overlay[] {
  const out: Overlay[] = [];
  // A piece laid over one that is still playing (a nudge, dual dialogue) plays over it, as a placed sound does: the cues walk one at a time.
  for (const { p, lane } of walk(laid, lanes).layered) {
    if (p.audio) out.push({ id: p.id, lane, start: p.start, seconds: p.seconds, audio: p.audio, volume: p.volume ?? 1, loop: false });
  }
  let windows: [number, number][] | undefined; // the speech windows, found once and only when a bed ducks
  for (const lane of lanes.filter((l) => l.placed)) {
    for (const p of laid.items.flatMap((i) => i.lanes[lane.id] ?? [])) {
      if (p.audio) out.push({ id: p.id, lane: lane.id, start: p.start, seconds: p.seconds, audio: p.audio, volume: p.volume ?? 1, loop: false });
    }
  }
  for (const lane of lanes.filter((l) => l.bed)) {
    for (const b of laid.beds[lane.id] ?? []) {
      if (!b.audio) continue;
      const shape: Partial<Overlay> = {
        ...(b.fadeIn > 0 || b.fadeOut > 0 ? { fade: { from: b.start, to: b.start + b.seconds, in: b.fadeIn, out: b.fadeOut } } : {}),
        ...(b.duck !== null ? { duck: { depth: b.duck, windows: windows ??= speechWindows(laid, lanes) } } : {}),
      };
      if (b.steps.length === 0) out.push({ id: b.id, lane: lane.id, start: b.start, seconds: b.seconds, audio: b.audio, volume: b.volume, loop: b.loop, ...shape });
      else for (const step of b.steps) if (step.volume > 0) out.push({ id: b.id, lane: lane.id, start: step.start, seconds: step.seconds, audio: b.audio, volume: step.volume, loop: b.loop, origin: b.start, ...shape });
    }
  }
  return out.sort((a, b) => a.start - b.start);
}

export function cues(laid: Layout, lanes: LaneSpec[]): Cue[] {
  return walk(laid, lanes).cues;
}

/** The player's walk: each item's timed pieces one at a time with the silences between, and the pieces that start before the one playing has ended
 * (`layered`: a nudge or dual dialogue laid them over it), which `overlays` plays over the walk instead. */
function walk(laid: Layout, lanes: LaneSpec[]): { cues: Cue[]; layered: { p: Piece; lane: string }[] } {
  const timedLanes = lanes.filter((l) => l.in && (l.seconds || l.estimate_from)).map((l) => l.id);
  const out: Cue[] = [];
  const layered: { p: Piece; lane: string }[] = [];
  let heard = 0; // where the last piece played in turn ends
  for (const item of laid.items) {
    const timed = timedLanes
      .flatMap((id) => (item.lanes[id] ?? []).map((p) => ({ p, lane: id })))
      .filter(({ p }) => p.seconds > 0)
      .sort((a, b) => a.p.start - b.p.start);
    if (timed.length === 0) {
      out.push({ item: item.id, piece: null, lane: null, start: item.start, seconds: item.seconds, audio: null });
      continue;
    }
    let at = item.start;
    for (const { p, lane } of timed) {
      if (p.start < Math.max(at, heard) - 1e-6) {
        layered.push({ p, lane });
        continue;
      }
      if (p.start > at) out.push({ item: item.id, piece: null, lane: null, start: at, seconds: p.start - at, audio: null });
      out.push({ item: item.id, piece: p.id, lane, start: p.start, seconds: p.seconds, audio: p.audio });
      at = heard = p.start + p.seconds;
    }
    const end = item.start + item.seconds;
    if (end > at) out.push({ item: item.id, piece: null, lane: null, start: at, seconds: end - at, audio: null });
  }
  return { cues: out, layered };
}

/**
 * The picture's shape as width over height, from the trailing `WxH` of a value such as `short-9x16`, `square-1x1` or `wide-16x9`; null for anything
 * else, which leaves the strip as it was. The strip draws each beat's picture in this shape, as the render will cut it.
 */
export function aspectOf(value: unknown): number | null {
  const m = typeof value === "string" ? /(?:^|[^0-9])(\d{1,2})x(\d{1,2})\s*$/i.exec(value.trim()) : null;
  const ratio = m ? Number(m[1]) / Number(m[2]) : NaN;
  return Number.isFinite(ratio) && ratio > 0 ? ratio : null;
}

/** Whether an item shows the Keep and Redo buttons: its status is one of the ones the view says are waiting to be looked at. */
export function canReview(status: string, review: { ready: string[] } | undefined | null): boolean {
  return !!review && !!status && review.ready.includes(status);
}

/** What the transport buttons do: `start` (|<), `back` (<<), `next` (>>) and `end` (>|). */
export type Jump = "start" | "back" | "next" | "end";

/** Further into an item than this, "back" goes to the item's own start first, as a player's previous button does; within it, to the one before. */
const RESTART_AFTER = 1;
/** A start this close to where the playhead is counts as being at it. */
const SAME_PLACE = 0.05;

/**
 * Where the playhead goes: `start` the very beginning, `end` the very end, `next` the start of the next item (the end when there is none),
 * and `back` the start of the item being played, or of the one before when the playhead is within a second of its start.
 * `starts` are the items' start times in seconds.
 */
export function jumpTo(starts: readonly number[], total: number, now: number, action: Jump): number {
  const sorted = [...new Set(starts)].sort((a, b) => a - b);
  if (action === "start") return 0;
  if (action === "end") return total;
  if (action === "next") return sorted.find((s) => s > now + SAME_PLACE) ?? total;
  const current = [...sorted].reverse().find((s) => s <= now + SAME_PLACE);
  if (current === undefined) return 0;
  if (now - current > RESTART_AFTER) return current;
  const before = [...sorted].reverse().find((s) => s < current - SAME_PLACE);
  return before ?? 0;
}

/** A time as the playhead clock shows it: hours, minutes, seconds and thousandths, `0:01:23.456`. */
export function clockText(seconds: number): string {
  const total = Math.max(0, Math.round((Number.isFinite(seconds) ? seconds : 0) * 1000));
  const h = Math.floor(total / 3_600_000);
  const m = Math.floor((total % 3_600_000) / 60_000);
  const sec = Math.floor((total % 60_000) / 1000);
  const ms = total % 1000;
  return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}.${String(ms).padStart(3, "0")}`;
}

/**
 * A time typed into the playhead clock, in seconds, or null when it is not one: plain seconds (`83.5`), minutes and seconds (`1:23.5`), hours, minutes and
 * seconds (`0:01:23.456`), or those with the thousandths after a fourth colon (`0:01:23:456`). A comma works as the decimal point.
 */
export function parseClock(text: string): number | null {
  const raw = text.trim().replace(",", ".");
  if (!raw) return null;
  const parts = raw.split(":");
  if (parts.length > 4 || parts.some((p) => !/^\d+(\.\d+)?$/.test(p))) return null;
  const nums = parts.map(Number);
  if (nums.some((n) => !Number.isFinite(n))) return null;
  if (parts.length === 4) {
    if (parts[3].includes(".") || parts[2].includes(".")) return null; // the fourth part is whole thousandths
    return nums[0] * 3600 + nums[1] * 60 + nums[2] + nums[3] / 1000;
  }
  return nums.reduce((total, n) => total * 60 + n, 0);
}

/** Which item the playhead is in (the last whose start is not after it) and how far into it: the offset is the "at" a sound cue in that item needs. */
export function placeIn(starts: readonly number[], now: number): { index: number; offset: number } | null {
  let index = -1;
  starts.forEach((start, i) => {
    if (start <= now + 1e-9 && (index < 0 || start >= starts[index])) index = i;
  });
  return index < 0 ? null : { index, offset: Math.max(0, now - starts[index]) };
}

