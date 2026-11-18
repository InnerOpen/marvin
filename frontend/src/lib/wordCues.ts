/**
 * Cues on words: a JSON list on a spine item (a beat's `cues`) whose cues sit at a word of one of its lines, as the Screenplay Studio render
 * reads them (marvin_pull `_cues`): `[{line, word, sound?, volume?, camera?, pic?}]`. `line` is the line's slug, `word` how many words are spoken
 * before the cue; a sound plays at the end of the word before it, a camera move starts there, a picture comes in at the start of the word after
 * it. A timeline view declares the field (`spine.word_cues`); the entry page edits it as rows and the Timeline draws it. Pure: no fetching.
 */

export const CAMERA_KINDS = ["punch", "shake", "nudge"] as const;
export type CameraKind = (typeof CAMERA_KINDS)[number];

export interface Camera {
  kind: CameraKind;
  /** Punch: how far in, 1 to 1.5 (1.06 when not set). Shake: how hard, a share of the frame in percent, 0 to 10 (1.2 when not set). */
  amount?: number;
  /** Nudge: the point of the picture it drifts toward, 0 to 1 each (0.5 when not set). */
  x?: number;
  y?: number;
}

/** What the render does when a camera cue leaves a number out (ScreenplayStudio render/storyrender/camera.py). */
export const CAMERA_DEFAULTS = { punch: 1.06, shake: 1.2, x: 0.5, y: 0.5 } as const;

export interface WordCue {
  line: string;
  word: number;
  sound?: string;
  /** The sound's own level for this cue, 0 to 1; missing keeps the sound's. */
  volume?: number;
  camera?: Camera;
  /** The slug of the overlay beat whose picture comes in here. */
  pic?: string;
  /** Anything else the cue carried, kept as it was. */
  rest: Record<string, unknown>;
}

const KNOWN = new Set(["line", "word", "sound", "volume", "camera", "pic"]);

const number = (v: unknown): number | null => {
  const n = typeof v === "string" && v.trim() !== "" ? Number(v) : v;
  return typeof n === "number" && Number.isFinite(n) ? n : null;
};
const held = (v: number, low: number, high: number) => Math.min(Math.max(v, low), high);

/** A cue's camera as the render reads it (camera.py `cue_of`): a known kind, numbers held to its ranges; undefined for anything else. */
export function cameraOf(raw: unknown): Camera | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const r = raw as Record<string, unknown>;
  const kind = String(r.kind ?? "").toLowerCase();
  if (!(CAMERA_KINDS as readonly string[]).includes(kind)) return undefined;
  if (kind === "nudge") {
    const [x, y] = [number(r.x), number(r.y)];
    return { kind: "nudge", ...(x !== null ? { x: held(x, 0, 1) } : {}), ...(y !== null ? { y: held(y, 0, 1) } : {}) };
  }
  const amount = number(r.amount);
  if (amount === null) return { kind: kind as CameraKind };
  return { kind: kind as CameraKind, amount: kind === "punch" ? held(amount, 1, 1.5) : held(amount, 0, 10) };
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
  for (const raw of list) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) continue;
    const r = raw as Record<string, unknown>;
    const word = number(r.word ?? 0);
    if (typeof r.line !== "string" || !r.line || word === null || word < 0) continue;
    const volume = number(r.volume);
    const camera = cameraOf(r.camera);
    out.push({
      line: r.line,
      word: Math.floor(word),
      ...(typeof r.sound === "string" && r.sound ? { sound: r.sound } : {}),
      ...(volume !== null ? { volume: held(volume, 0, 1) } : {}),
      ...(camera ? { camera } : {}),
      ...(typeof r.pic === "string" && r.pic ? { pic: r.pic } : {}),
      rest: Object.fromEntries(Object.entries(r).filter(([k]) => !KNOWN.has(k))),
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
    ...(c.pic ? { pic: c.pic } : {}),
  }));
  return JSON.stringify(list, null, 2);
}

/** The words of a line as the render counts them for a cue: the take's timed words when it has them, else the text's words (anything between
 * spaces), so the n-th chip is the word a cue's `word: n` comes before. */
export function chipsOf(text: string, words: readonly { text: string }[] | null | undefined): string[] {
  return words?.length ? words.map((w) => w.text) : text.split(/\s+/).filter(Boolean);
}

/** How a camera cue reads: "Punch 1.06", "Shake 2", "Nudge 0.7, 0.4". */
export function cameraWords(camera: Camera): string {
  const name = camera.kind.charAt(0).toUpperCase() + camera.kind.slice(1);
  if (camera.kind === "nudge") return `${name} ${camera.x ?? CAMERA_DEFAULTS.x}, ${camera.y ?? CAMERA_DEFAULTS.y}`;
  return `${name} ${camera.amount ?? CAMERA_DEFAULTS[camera.kind]}`;
}
