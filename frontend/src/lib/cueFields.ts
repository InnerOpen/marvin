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
  /** The referenced entries' type, and the lane's title (what the cues are called). */
  entryType: string;
  title: string;
  /** The referenced entry's asset field holding a sound to hear, and its length field, when the lane declares them. */
  audio?: string;
  seconds?: string;
}

interface ViewLike {
  definition?: {
    kind?: string;
    spine?: { entry_type?: string };
    lanes?: { id?: string; title?: string; entry_type?: string; placed?: { field: string; ref: string; at: string }; audio?: string; seconds?: string }[];
  };
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
        entryType: lane.entry_type,
        title: lane.title || lane.id || lane.entry_type,
        audio: lane.audio,
        seconds: lane.seconds,
      });
    }
  }
  return [...out.values()];
}

export interface Cue {
  ref: string;
  at: number;
  /** Anything else the cue carried, kept as it was. */
  rest: Record<string, unknown>;
}

const num = (v: unknown): number => {
  const n = typeof v === "string" && v.trim() !== "" ? Number(v) : v;
  return typeof n === "number" && Number.isFinite(n) && n >= 0 ? n : 0;
};

/** The field's value as cues: a JSON text or an already-parsed list; anything that is not a list of objects is no cues. */
export function parseCues(value: unknown, spec: Pick<CueSpec, "ref" | "at">): Cue[] {
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
    out.push({ ref: typeof ref === "string" ? ref : "", at: num(at), rest });
  }
  return out;
}

/** The cues back as the field's JSON, in time order, cues naming nothing left out. */
export function serializeCues(cues: readonly Cue[], spec: Pick<CueSpec, "ref" | "at">): string {
  const rows = cues
    .filter((c) => c.ref)
    .sort((a, b) => a.at - b.at)
    .map((c) => ({ ...c.rest, [spec.ref]: c.ref, [spec.at]: Number(c.at.toFixed(3)) }));
  return JSON.stringify(rows, null, 2);
}
