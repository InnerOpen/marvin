/**
 * Cue lists: a JSON field on an entry that places other entries in time (a beat's `sounds`: `[{sound, at}]`). A package's timeline view
 * declares that shape (a `placed` lane: `{field, ref, at}` on the spine type), so an entry of the spine type can edit the field as a list
 * of cues (pick an entry, set the seconds) instead of raw JSON. Pure: the page fetches, this reads and writes the shape.
 */

export interface CueSpec {
  /** The JSON field on the entry being edited. */
  field: string;
  /** Keys inside each cue: the referenced entry's slug and its offset in seconds. */
  ref: string;
  at: string;
  /** The key inside each cue holding its own level, 0 to 1 (a sound effect louder or quieter than the sound's own); empty keeps the sound's own. */
  volume?: string;
  /** The referenced entries' type, and the lane's title (what the cues are called). */
  entryType: string;
  title: string;
  /** The referenced entry's asset field holding a sound to hear, and its length field, when the lane declares them. */
  audio?: string;
  seconds?: string;
  /** Only entries whose fields hold these values are offered (a beat's sound effects offer sounds of kind effect). */
  filter?: Record<string, string>;
}

interface LaneLike {
  id?: string;
  title?: string;
  entry_type?: string;
  in?: string;
  of?: string;
  placed?: { field: string; ref: string; at: string; volume?: string; filter?: Record<string, unknown> };
  audio?: string;
  seconds?: string;
  text?: string;
  who?: string;
  words?: string;
  order?: string;
  off?: string;
}

interface ViewLike {
  definition?: {
    kind?: string;
    spine?: { entry_type?: string; of?: string; order?: string; picture?: string; starts_during?: string; word_cues?: { field?: string; lane?: string; sounds?: string } };
    lanes?: LaneLike[];
  };
}

/** The well-formed part of a placed lane's `filter`: field keys with text values; nothing when there is none. */
function filterOf(raw: unknown): Record<string, string> | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return undefined;
  const entries = Object.entries(raw).filter(([k, v]) => k && typeof v === "string" && v);
  return entries.length ? Object.fromEntries(entries) : undefined;
}

/** The cue lists an entry of `typeSlug` carries, from the views whose spine is that type; one per field. */
export function cueSpecsFor(views: readonly ViewLike[], typeSlug: string): CueSpec[] {
  const out = new Map<string, CueSpec>();
  for (const view of views) {
    const def = view.definition;
    if (!def || def.kind !== "timeline" || def.spine?.entry_type !== typeSlug) continue;
    for (const lane of def.lanes ?? []) {
      if (!lane.placed || !lane.entry_type || out.has(lane.placed.field)) continue;
      out.set(lane.placed.field, {
        field: lane.placed.field,
        ref: lane.placed.ref,
        at: lane.placed.at,
        ...(typeof lane.placed.volume === "string" && lane.placed.volume ? { volume: lane.placed.volume } : {}),
        entryType: lane.entry_type,
        title: lane.title || lane.id || lane.entry_type,
        audio: lane.audio,
        seconds: lane.seconds,
        ...(filterOf(lane.placed.filter) ? { filter: filterOf(lane.placed.filter) } : {}),
      });
    }
  }
  return [...out.values()];
}

export interface Cue {
  ref: string;
  at: number;
  /** The cue's own level (0 to 1), or null for the sound's own. */
  level: number | null;
  /** Anything else the cue carried, kept as it was. */
  rest: Record<string, unknown>;
}

/** Seconds into the entry; negative is before it (a sound that starts over the beat before, as the render plays it). */
const num = (v: unknown): number => {
  const n = typeof v === "string" && v.trim() !== "" ? Number(v) : v;
  return typeof n === "number" && Number.isFinite(n) ? n : 0;
};

/** The field's value as cues: a JSON text or an already-parsed list; anything that is not a list of objects is no cues. */
export function parseCues(value: unknown, spec: Pick<CueSpec, "ref" | "at" | "volume">): Cue[] {
  let list: unknown = value;
  if (typeof value === "string") {
    try {
      list = value.trim() ? JSON.parse(value) : [];
    } catch {
      return [];
    }
  }
  if (!Array.isArray(list)) return [];
  const out: Cue[] = [];
  for (const item of list) {
    if (typeof item !== "object" || item === null || Array.isArray(item)) continue;
    const { [spec.ref]: ref, [spec.at]: at, ...rest } = item as Record<string, unknown>;
    let level: number | null = null;
    if (spec.volume && spec.volume in rest) {
      const own = rest[spec.volume];
      const n = typeof own === "string" && own.trim() !== "" ? Number(own) : own;
      if (typeof n === "number" && Number.isFinite(n) && n >= 0 && n <= 1) {
        level = n;
        delete rest[spec.volume]; // the editor owns it now; written back below when it is set
      }
    }
    out.push({ ref: typeof ref === "string" ? ref : "", at: num(at), level, rest });
  }
  return out;
}

/** The cues back as the field's JSON, in time order, cues naming nothing left out. */
export function serializeCues(cues: readonly Cue[], spec: Pick<CueSpec, "ref" | "at" | "volume">): string {
  const rows = cues
    .filter((c) => c.ref)
    .sort((a, b) => a.at - b.at)
    .map((c) => ({ ...c.rest, [spec.ref]: c.ref, [spec.at]: Number(c.at.toFixed(3)), ...(spec.volume && c.level !== null ? { [spec.volume]: Number(c.level.toFixed(3)) } : {}) }));
  return JSON.stringify(rows, null, 2);
}

/** A list of cues on words on an entry of the spine type (`spine.word_cues`, lib/wordCues.ts): what its page needs to edit it as rows. */
export interface WordCueSpec {
  /** The JSON field on the entry being edited. */
  field: string;
  /** The lines the cues sit on: their type, the field on a line holding this entry's slug, and their text, take, word timings and order. */
  lines: { entryType: string; in: string; text?: string; who?: string; audio?: string; words?: string; order?: string; off?: string };
  /** The sounds a cue may play (the placed lane's type, take, length and filter), as the sounds list offers them; missing when the view names none. */
  sounds?: CueSpec;
  /** The field on an entry of this type holding the view's entry's slug (a beat's story), its order and picture fields, and the field that makes one
   * an overlay (`starts_during`): the pictures a cue may bring in are the view's entry's items that have one. */
  of: string;
  order?: string;
  picture?: string;
  startsDuring?: string;
}

/** The cue-on-word lists an entry of `typeSlug` carries, from the views whose spine is that type and declares `word_cues`; one per field. */
export function wordCueSpecsFor(views: readonly ViewLike[], typeSlug: string): WordCueSpec[] {
  const out = new Map<string, WordCueSpec>();
  for (const view of views) {
    const def = view.definition;
    const wc = def?.spine?.word_cues;
    if (def?.kind !== "timeline" || def.spine?.entry_type !== typeSlug || !wc?.field || !def.spine.of || out.has(wc.field)) continue;
    const lane = (def.lanes ?? []).find((l) => l.id === wc.lane && l.in && l.entry_type);
    if (!lane) continue;
    const sounds = wc.sounds ? cueSpecsFor([{ definition: { ...def, lanes: (def.lanes ?? []).filter((l) => l.id === wc.sounds) } }], typeSlug)[0] : undefined;
    out.set(wc.field, {
      field: wc.field,
      lines: { entryType: lane.entry_type!, in: lane.in!, text: lane.text, who: lane.who, audio: lane.audio, words: lane.words, order: lane.order, off: lane.off },
      ...(sounds ? { sounds } : {}),
      of: def.spine.of,
      order: def.spine.order,
      picture: def.spine.picture,
      startsDuring: def.spine.starts_during,
    });
  }
  return [...out.values()];
}
