/**
 * A `timeline` view, laid out: the entries a package's view definition names (services/blueprints/views.py), as positions in time.
 *
 * The spine (a story's beats) runs end to end; each item lasts as long as the renderer will cut it: an item with timed pieces in its lanes
 * (lines) lasts `lead + Σ piece seconds + gap × (pieces − 1) + tail`, an item with none lasts `hold`. A piece with no recording yet is
 * *estimated* from its text at a reading pace, so the timeline is useful before anything is recorded and firms up as takes land. Pure:
 * nothing here fetches; the page hands in rows and gets back what to draw.
 */

export interface SecondsSpec {
  hold?: string;
  lead?: string;
  gap?: string;
  tail?: string;
  defaults?: Partial<Record<"hold" | "lead" | "gap" | "tail", number>>;
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
  /** A bed that layers, as the render plays ambience: `item_field` on each spine item names its own sound (it wins over the `via` entry's
   * `field`: a beat's own over its scene's), and `entry_field` on the view's entry names a sound under the whole film (the story's), which
   * plays together with those, its level in `entry_volume`. */
  item_field?: string;
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
  assets?: { role?: string | null; name?: string | null; publicUrl?: string | null; mimeType?: string | null }[];
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
}

export interface BedStep {
  start: number;
  seconds: number;
  volume: number;
  /** For the story's bed: who set this stretch's level (the story itself, a scene or a beat), the title of that scene or beat, and whether it is heard from inside. */
  source?: BedSource;
  by?: string;
  muffled?: boolean;
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
  start: number;
  seconds: number;
  /** True when any timed piece in it is estimated (so its length may change). */
  estimated: boolean;
  lanes: Record<string, Piece[]>;
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

/** The seconds an item's own fields set, each falling back to the view's default, then to the renderer's. */
export function secondsOf(row: Row, spec: SecondsSpec | undefined): typeof DEFAULT_SECONDS {
  const out = { ...DEFAULT_SECONDS, ...(spec?.defaults ?? {}) };
  for (const key of ["hold", "lead", "gap", "tail"] as const) {
    const own = num(field(row, spec?.[key]));
    if (own !== null && own >= 0) out[key] = own;
  }
  return out;
}

/**
 * The renderer's rule: timed pieces one after another with silences around them; nothing timed, and the item holds (its own hold, else the view's
 * default). An item that sets its own hold lasts at least that long even with timed pieces: the picture stays up after the last line, so a beat
 * that would be too quick for a viewer to take in can be given the time. The view's default hold is only for an item with nothing in it.
 */
export function itemSeconds(row: Row, timed: { seconds: number }[], spec: SecondsSpec | undefined): number {
  const s = secondsOf(row, spec);
  if (timed.length === 0) return s.hold;
  const spoken = s.lead + timed.reduce((sum, p) => sum + p.seconds, 0) + s.gap * (timed.length - 1) + s.tail;
  const own = num(field(row, spec?.hold));
  return own !== null && own > spoken ? own : spoken;
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
  const laneRows = (lane: LaneSpec) => [...(rows.lanes[lane.id] ?? [])].filter((r) => !isOff(r, lane)).sort(byOrder(lane.order));
  const bySlug = (lane: LaneSpec) => new Map(laneRows(lane).map((r) => [r.slug, r] as const));

  const items: Item[] = [];
  let clock = 0;
  const groups = groupRows(spec.spine, rows);
  const out: Group[] = [];
  // A title or end card is an item of its own, so everything laid out after it starts when the render starts it.
  const addCard = (kind: "intro" | "outro") => {
    const card = cardOf(spec.spine.cards?.[kind], rows.entry, kind);
    if (!card) return;
    const item: Item = { id: `card:${kind}`, slug: kind, key: "", title: card.label, number: null, text: card.title, picture: null, status: "", start: clock, seconds: card.seconds, estimated: false, lanes: {}, card: kind };
    items.push(item);
    out.push({ card: kind, id: null, slug: null, title: card.label, start: clock, seconds: card.seconds, items: [item] });
    clock += card.seconds;
  };
  addCard("intro");
  // The pause where a scene ends: after an item whose next item is in another scene. The rows come in the order the render plays them.
  const flat = groups.flatMap((g) => g.rows);
  const nextOf = new Map(flat.map((r, i) => [r.id, flat[i + 1]] as const));
  const pauseSeconds = spec.spine.scene_break && rows.entry ? num(field(rows.entry, spec.spine.scene_break.seconds)) : null;
  const pauseAfter = (row: Row): number => {
    const next = nextOf.get(row.id);
    const field_ = spec.spine.scene_break?.field;
    if (!next || !field_ || pauseSeconds === null || pauseSeconds <= 0) return 0;
    const [here, there] = [str(field(row, field_)).trim(), str(field(next, field_)).trim()];
    return here && there && here !== there ? pauseSeconds : 0;
  };
  for (const g of groups) {
    const groupStart = clock;
    const made: Item[] = [];
    for (const row of g.rows) {
      const s = secondsOf(row, spec.spine.seconds);
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
        estimated: false,
        lanes: {},
      };
      // Timed pieces run across the `in` lanes in declared order, one after another from the lead.
      let cursor = clock + s.lead;
      const timed: Piece[] = [];
      for (const lane of inLanes) {
        const pieces: Piece[] = [];
        for (const r of laneRows(lane).filter((r) => str(field(r, lane.in)) === row.slug)) {
          const length = pieceSeconds(r, lane);
          const piece = pieceOf(r, lane, length?.seconds ?? 0, length?.estimated ?? false, cursor, null);
          if (length) {
            if (timed.length) cursor += s.gap;
            piece.start = cursor;
            cursor += length.seconds;
            timed.push(piece);
          }
          pieces.push(piece);
        }
        item.lanes[lane.id] = pieces;
      }
      item.seconds = itemSeconds(row, timed, spec.spine.seconds);
      item.pause = pauseAfter(row);
      item.seconds += item.pause;
      item.estimated = timed.some((p) => p.estimated);
      let reach = 0; // how far into the item its last placed sound runs: the render lets a beat last until that sound has finished
      for (const lane of placedLanes) {
        const known = bySlug(lane);
        const placed = field(row, lane.placed!.field);
        const pieces: Piece[] = [];
        for (const ref of Array.isArray(placed) ? placed : []) {
          if (typeof ref !== "object" || ref === null) continue;
          const target = known.get(str((ref as Record<string, unknown>)[lane.placed!.ref]));
          if (!target) continue;
          const at = Math.max(0, num((ref as Record<string, unknown>)[lane.placed!.at]) ?? 0);
          const length = pieceSeconds(target, lane);
          const piece = pieceOf(target, lane, length?.seconds ?? 0, length?.estimated ?? false, clock + at, at);
          const own = lane.placed!.volume ? level((ref as Record<string, unknown>)[lane.placed!.volume]) : null;
          if (own !== null) piece.volume = own; // the cue's own loudness replaces the sound's, as in the render
          pieces.push(piece);
          // A sound with no take yet has a width to show it needs filling in (its text, as a line has), but nothing plays, so it never lengthens its item.
          const plays = !!length && (!length.estimated || !!assetUrl(target, lane.audio, "audio/"));
          reach = Math.max(reach, at + (plays ? length!.seconds : 0));
        }
        item.lanes[lane.id] = pieces;
      }
      if (reach > item.seconds - item.pause) item.seconds = reach + item.pause; // the render: max(hold, speech, the end of the last sound) and then the pause
      clock += item.seconds;
      made.push(item);
      items.push(item);
    }
    out.push({ id: g.id, slug: g.slug, title: g.title, start: groupStart, seconds: clock - groupStart, items: made });
  }
  addCard("outro");
  const beds: Record<string, Bed[]> = {};
  for (const lane of bedLanes) beds[lane.id] = bedsOf(lane, items, rows, clock, bySlug(lane));
  const covers: Record<string, Cover[]> = {};
  for (const lane of lanes.filter((l) => l.cover)) covers[lane.id] = coversOf(lane.cover!, spec, items, rows, lane.id);
  const marks: Record<string, Mark[]> = {};
  for (const lane of lanes.filter((l) => l.marks)) marks[lane.id] = marksOf(lane.marks!, spec, items, rows, lane.id);
  const bands: Record<string, Band[]> = {};
  for (const band of spec.spine.bands ?? []) bands[band.id ?? band.field] = bandsOf(band, items, rows, band.id ?? band.field);
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
  const out: Bed[] = [];
  // The story's own bed under the whole film, which plays together with the beds of items and scenes (the render layers them).
  const storySound = spec.entry_field && rows.entry ? sounds.get(str(field(rows.entry, spec.entry_field))) : undefined;
  const everywhere = storySound && total > 0 ? [make(storySound, 0, total, level(field(rows.entry!, spec.entry_volume)), false, items.map((i) => i.id))] : [];
  if (everywhere[0]) everywhere[0].steps = storyBedSteps(spec, items, spine, via, everywhere[0].volume);
  for (const item of items) {
    const row = spine.get(item.id);
    if (!row) continue;
    const named = spec.via ? via.get(str(field(row, spec.via))) : row;
    // a beat's own sound wins over its scene's; each is a bed of its own level
    const own = spec.item_field ? sounds.get(str(field(row, spec.item_field))) : undefined;
    const sound = own ?? (named ? sounds.get(str(field(named, spec.field))) : undefined);
    if (!sound) continue;
    const at = level(field(row, spec.item_volume)) ?? (own ? null : level(named ? field(named, spec.volume) : null));
    const muffled = !own && !!(named && spec.muffled && field(named, spec.muffled) === true);
    const last = out[out.length - 1];
    if (last && last.slug === sound.slug && last.volume === bedLevel(lane, sound, at) && last.muffled === muffled && last.start + last.seconds >= item.start - 1e-6) {
      last.seconds = item.start + item.seconds - last.start;
      last.items.push(item.id);
    } else {
      out.push(make(sound, item.start, item.seconds, at, muffled, [item.id]));
    }
  }
  for (const b of out) {
    const sound = sounds.get(b.slug);
    if (sound) Object.assign(b, bedFades(spec, sound, b.start, b.seconds, total, rows.entry, spine.get(b.items[0]), spine.get(b.items[b.items.length - 1])));
  }
  return [...everywhere, ...out];
}

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
  for (const item of items) {
    const row = spine.get(item.id);
    const volume = (row ? level(field(row, spec.item_volume)) : null) ?? base;
    const last = runs[runs.length - 1];
    if (last && Math.abs(last.volume - volume) < 1e-9) last.seconds = item.start + item.seconds - last.start;
    else runs.push({ start: item.start, seconds: item.seconds, volume });
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
  };
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
    timed.slice(1).forEach((p, i) => add(`${item.id}:gap${i}`, "gap", timed[i].start + timed[i].seconds, p.start - (timed[i].start + timed[i].seconds)));
    const end = timed[timed.length - 1].start + timed[timed.length - 1].seconds;
    add(`${item.id}:tail`, "tail", end, item.start + item.seconds - end);
  }
  return out;
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
  const timedLanes = lanes.filter((l) => l.in && (l.seconds || l.estimate_from)).map((l) => l.id);
  const out: Cue[] = [];
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
      if (p.start > at) out.push({ item: item.id, piece: null, lane: null, start: at, seconds: p.start - at, audio: null });
      out.push({ item: item.id, piece: p.id, lane, start: p.start, seconds: p.seconds, audio: p.audio });
      at = p.start + p.seconds;
    }
    const end = item.start + item.seconds;
    if (end > at) out.push({ item: item.id, piece: null, lane: null, start: at, seconds: end - at, audio: null });
  }
  return out;
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

