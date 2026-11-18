/**
 * Cues on words: a JSON list on a spine item (a beat's `cues`) whose cues sit at a word of one of its lines, as the Screenplay Studio render
 * reads them (marvin_pull `_cues`): `[{line, word, sound?, volume?, camera?, look?, mix?, emphasis?, pic?, nudge?}]`. `line` is the line's
 * slug, `word` how many words are spoken before the cue; a sound plays at the end of the word before it, a camera move, a look and a change to
 * the mix start there, a picture comes in at the start of the word after it, and `emphasis` makes that word stand out in the captions. The
 * kinds of camera move, look and mix, their numbers and defaults are in lib/cueKinds.ts. A timeline view declares the field
 * (`spine.word_cues`); the entry page edits it as rows and the Timeline draws it. Pure: no fetching.
 */

import { type Effect, effectOf, effectWords, emphasisOf } from "./cueKinds.ts";

/** A camera move at the cue (its kinds, numbers and defaults: lib/cueKinds.ts `CAMERA`). Anything else it carries is kept. */
export type Camera = Effect & { amount?: number; x?: number; y?: number; seconds?: number };
/** How the picture looks from the cue (lib/cueKinds.ts `LOOK`). */
export type Look = Effect & { amount?: number; seconds?: number; color?: string };
/** What is heard under the voice from the cue (lib/cueKinds.ts `MIX`). */
export type Mix = Effect & { amount?: number; seconds?: number };

export interface WordCue {
  line: string;
  word: number;
  sound?: string;
  /** The sound's own level for this cue, 0 to 1; missing keeps the sound's. */
  volume?: number;
  camera?: Camera;
  look?: Look;
  mix?: Mix;
  /** The word after the cue stands out in the captions: `true`, or `{scale}`. */
  emphasis?: true | Record<string, unknown>;
  /** The slug of the overlay beat whose picture comes in here. */
  pic?: string;
  /** Seconds the cue's sound, camera move, look, mix and emphasis come later (+) or earlier (-) than its word, -10 to 10; missing is 0. */
  nudge?: number;
  /** Where the cue stands in the field's list as stored (malformed entries counted), to write back to that entry alone. */
  position?: number;
  /** Anything else the cue carried, kept as it was. */
  rest: Record<string, unknown>;
}

const KNOWN = new Set(["line", "word", "sound", "volume", "camera", "look", "mix", "emphasis", "pic", "nudge"]);

const number = (v: unknown): number | null => {
  const n = typeof v === "string" && v.trim() !== "" ? Number(v) : v;
  return typeof n === "number" && Number.isFinite(n) ? n : null;
};
const held = (v: number, low: number, high: number) => Math.min(Math.max(v, low), high);

/** A cue's camera as the render reads it (camera.py `cue_of`): a known kind with its numbers held to their ranges, an unknown one kept as
 * written (so a save never drops it); undefined when it is not a move at all. */
export function cameraOf(raw: unknown): Camera | undefined {
  return effectOf("camera", raw) as Camera | undefined;
}

/** How a camera cue reads: "Punch 1.06", "Shake 2", "Nudge 0.7, 0.4", "Whip pan right, 0.3". */
export function cameraWords(camera: Camera): string {
  return effectWords("camera", camera);
}

/** What a cue carries besides what this reads: keys of its own, and a camera, look, mix or emphasis that could not be read (not an object
 * with a kind), so a save never drops what someone wrote. */
function restOf(r: Record<string, unknown>, read: Record<string, unknown>): Record<string, unknown> {
  const unreadable = (k: string, v: unknown) => k in read && read[k] === undefined && v !== undefined && v !== null && v !== false;
  return Object.fromEntries(Object.entries(r).filter(([k, v]) => !KNOWN.has(k) || unreadable(k, v)));
}

/** The field's value as cues: JSON text or a parsed list; a cue with no line, or a word that is not a whole number 0 or more, is left out. */
export function parseWordCues(value: unknown): WordCue[] {
  let list: unknown = value;
  if (typeof list === "string") {
    try {
      list = list.trim() ? JSON.parse(list) : [];
    } catch {
      return [];
    }
  }
  if (!Array.isArray(list)) return [];
  const out: WordCue[] = [];
  for (const [position, raw] of list.entries()) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) continue;
    const r = raw as Record<string, unknown>;
    const word = number(r.word ?? 0);
    if (typeof r.line !== "string" || !r.line || word === null || word < 0) continue;
    const volume = number(r.volume);
    const camera = cameraOf(r.camera);
    const look = effectOf("look", r.look) as Look | undefined;
    const mix = effectOf("mix", r.mix) as Mix | undefined;
    const emphasis = emphasisOf(r.emphasis);
    const nudge = number(r.nudge);
    const rest = restOf(r, { camera, look, mix, emphasis });
    out.push({
      line: r.line,
      word: Math.floor(word),
      ...(typeof r.sound === "string" && r.sound ? { sound: r.sound } : {}),
      ...(volume !== null ? { volume: held(volume, 0, 1) } : {}),
      ...(camera ? { camera } : {}),
      ...(look ? { look } : {}),
      ...(mix ? { mix } : {}),
      ...(emphasis ? { emphasis } : {}),
      ...(typeof r.pic === "string" && r.pic ? { pic: r.pic } : {}),
      ...(nudge ? { nudge: held(nudge, -10, 10) } : {}),
      position,
      rest,
    });
  }
  return out;
}

/** Cues back to the field's JSON, in the render's shape: line and word always, the others only when set; what else a cue carried stays. */
export function serializeWordCues(cues: readonly WordCue[]): string {
  const list = cues.map((c) => ({
    ...c.rest,
    line: c.line,
    word: c.word,
    ...(c.sound ? { sound: c.sound } : {}),
    ...(c.volume !== undefined ? { volume: Number(c.volume.toFixed(3)) } : {}),
    ...(c.camera ? { camera: c.camera } : {}),
    ...(c.look ? { look: c.look } : {}),
    ...(c.mix ? { mix: c.mix } : {}),
    ...(c.emphasis ? { emphasis: c.emphasis } : {}),
    ...(c.pic ? { pic: c.pic } : {}),
    ...(c.nudge ? { nudge: Number(c.nudge.toFixed(3)) } : {}),
  }));
  return JSON.stringify(list, null, 2);
}

/** The words of a line as the render counts them for a cue: the take's timed words when it has them, else the text's words (anything between
 * spaces), so the n-th chip is the word a cue's `word: n` comes before. */
export function chipsOf(text: string, words: readonly { text: string }[] | null | undefined): string[] {
  return words?.length ? words.map((w) => w.text) : text.split(/\s+/).filter(Boolean);
}
