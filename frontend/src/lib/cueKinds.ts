/**
 * What a cue on a word can do (lib/wordCues.ts), kind by kind: the one place for every kind's name, the numbers it takes, their ranges and what
 * the Screenplay Studio render does when one is left out. The beat page's editor and the Timeline both read it, so a change to the render's
 * kinds is a change here.
 *
 * The kinds, ranges and defaults are the render's own (ScreenplayStudio render/storyrender/camera.py: `cue_of`, `look_of`, `mix_of`,
 * `emphasis_of`, v218/v219). The render holds a number to its range, and leaves out a cue whose kind it does not know or whose colour that kind
 * does not take; Marvin holds numbers the same way, keeps anything else as written and shows it.
 *
 * `enabled` says whether the editor offers a kind. One listed with `enabled: false`: a row that already holds it keeps it, the editor shows it
 * as written and the Timeline draws it, but nobody picks it by mistake. Turning one on or off is that one line. Pure: no fetching.
 */

export type CueGroup = "camera" | "look" | "mix";

/** One choice of a field that is picked, not typed (a direction, a colour). */
export interface CueChoice {
  value: number | string;
  label: string;
}

export interface CueField {
  key: string;
  /** What the editor calls it (its label and tooltip). */
  label: string;
  /** A typed number, held to this range (as the render holds it). */
  min?: number;
  max?: number;
  step?: number;
  /** A pick from these instead: a number moves to the nearest; a word that is not one of them the render refuses. */
  choices?: readonly CueChoice[];
  /** What the render uses when it is left out. */
  default?: number | string;
  /** How leaving it out reads when it has no single default ("to the end of the shot"). */
  unset?: string;
  /** Written after the value: "s" for seconds. */
  unit?: string;
}

export interface CueKind {
  kind: string;
  /** Its name in words ("Whip pan"). */
  name: string;
  /** The editor's option: its name and what it does. */
  label: string;
  fields: readonly CueField[];
  /** Offered in the editor. */
  enabled: boolean;
  /** Drawn as a labelled chip next to the cue's flag; off for the camera moves the flag's ✣ has always stood for. */
  chip: boolean;
  /** A field whose value the chip shows ("dead air 1.5 s"). */
  chipField?: string;
  /** A sentence the editor shows once the kind is chosen. */
  help?: string;
}

const LOOK_SECONDS = { min: 0.05, max: 30 } as const; // the render's range for a look's or a mix's seconds
const seconds = (label: string, fallback: number | undefined, range: { min: number; max: number } = LOOK_SECONDS, unset?: string): CueField => ({
  key: "seconds",
  label,
  ...range,
  step: 0.05,
  unit: "s",
  ...(fallback !== undefined ? { default: fallback } : {}),
  ...(unset ? { unset } : {}),
});
const share = (key: string, label: string, fallback: number): CueField => ({ key, label, min: 0, max: 1, step: 0.05, default: fallback });
const picks = (...values: string[]): readonly CueChoice[] => values.map((value) => ({ value, label: value }));

/** How far a whip pan sweeps unless told: the render also zooms in by 1 + 2 × this to make room for the sweep. */
export const WHIP = 0.35;

/** Camera moves at the cue, on top of the beat's own (camera.py `cue_of`). */
export const CAMERA: readonly CueKind[] = [
  { kind: "punch", name: "Punch", label: "Punch (a quick zoom in)", enabled: true, chip: false, fields: [{ key: "amount", label: "How far in, 1 to 1.5", min: 1, max: 1.5, step: 0.01, default: 1.06 }] },
  { kind: "shake", name: "Shake", label: "Shake", enabled: true, chip: false, fields: [{ key: "amount", label: "How hard, % of the frame, 0 to 10", min: 0, max: 10, step: 0.1, default: 1.2 }] },
  {
    kind: "nudge",
    name: "Nudge",
    label: "Nudge (drift toward a point)",
    enabled: true,
    chip: false,
    fields: [share("x", "Toward x, 0 (left) to 1 (right)", 0.5), share("y", "Toward y, 0 (top) to 1 (bottom)", 0.5)],
  },
  {
    kind: "whip-pan",
    name: "Whip pan",
    label: "Whip pan (a fast sweep sideways and back)",
    enabled: true,
    chip: true,
    help: `It zooms in to make room for its sweep, by 1 + 2 × how far: the default ${WHIP} is ${1 + 2 * WHIP}× at its peak.`,
    fields: [
      { key: "x", label: "Direction", choices: [{ value: -1, label: "left" }, { value: 1, label: "right" }], default: 1 },
      { key: "amount", label: "How far, a share of the frame, 0.05 to 0.5", min: 0.05, max: 0.5, step: 0.05, default: WHIP },
    ],
  },
  {
    kind: "sway",
    name: "Sway",
    label: "Sway (a handheld sway that dies away)",
    enabled: true,
    chip: true,
    fields: [{ key: "amount", label: "How far, % of the frame, 0 to 5", min: 0, max: 5, step: 0.1, default: 0.8 }, seconds("For how long, seconds", 1.5, { min: 0.2, max: 10 })],
  },
];

/** How the picture looks from the cue, laid over the shot (camera.py `look_of`). */
export const LOOK: readonly CueKind[] = [
  {
    kind: "flash",
    name: "Flash",
    label: "Flash (a quick flash of light)",
    enabled: true,
    chip: true,
    fields: [{ key: "color", label: "Colour", choices: picks("white", "black", "orange", "red", "gold", "blue"), default: "white" }, share("amount", "How bright, 0 to 1", 0.9), seconds("For how long, seconds", 0.25)],
  },
  { kind: "burn", name: "Burn", label: "Burn (an orange flash, like a film burn)", enabled: true, chip: true, fields: [share("amount", "How bright, 0 to 1", 0.9), seconds("For how long, seconds", 0.35)] },
  { kind: "dip", name: "Dip", label: "Dip (to black or white and back)", enabled: true, chip: true, fields: [{ key: "color", label: "Colour", choices: picks("black", "white"), default: "black" }, seconds("For how long, seconds", 0.8)] },
  { kind: "freeze", name: "Freeze", label: "Freeze (the camera's move holds still, then carries on)", enabled: true, chip: true, fields: [seconds("For how long, seconds", 0.6)] },
  {
    kind: "tint",
    name: "Tint",
    label: "Tint (a colour grade)",
    enabled: true,
    chip: true,
    fields: [{ key: "color", label: "Grade", choices: picks("sepia", "mono", "cold", "warm"), default: "sepia" }, share("amount", "How much, 0 to 1", 1), seconds("For how long, seconds", undefined, LOOK_SECONDS, "to the end of the shot")],
  },
  { kind: "blur", name: "Blur", label: "Blur (starts out of focus and sharpens)", enabled: true, chip: true, fields: [share("amount", "How strong, 0 to 1", 0.6), seconds("For how long, seconds", 0.8)] },
  { kind: "vignette", name: "Vignette", label: "Vignette (the edges darken and release)", enabled: true, chip: true, fields: [share("amount", "How dark, 0 to 1", 0.7), seconds("For how long, seconds", 1)] },
  { kind: "glitch", name: "Glitch", label: "Glitch (a burst of split colour and jitter)", enabled: true, chip: true, fields: [seconds("For how long, seconds", 0.2)] },
];

/** The default length of a change to the mix: the render's, and how long the Timeline draws it. */
export const MIX_SECONDS = 1.5;

/** What is heard under the voice from the cue; the voice itself is never touched (camera.py `mix_of`). */
export const MIX: readonly CueKind[] = [
  { kind: "dead-air", name: "Dead air", label: "Dead air (ambience, music and effects go silent)", enabled: true, chip: true, chipField: "seconds", fields: [seconds("For how long, seconds", MIX_SECONDS)] },
  { kind: "duck", name: "Duck", label: "Duck (music and ambience dip)", enabled: true, chip: true, fields: [share("amount", "Down to, 0 to 1", 0.3), seconds("For how long, seconds", MIX_SECONDS)] },
];

/** The word after the cue stands out in the captions: `true`, or `{scale}` for how much bigger (camera.py `emphasis_of`). */
export const EMPHASIS = {
  enabled: true,
  name: "Emphasis",
  label: "Emphasise the word after it in the captions",
  scale: { key: "scale", label: "How much bigger, 1 to 2", min: 1, max: 2, step: 0.05, default: 1.3 } satisfies CueField,
};

export const CUE_KINDS: Record<CueGroup, readonly CueKind[]> = { camera: CAMERA, look: LOOK, mix: MIX };

/** A camera move, look or mix change as a row holds it: its kind and whatever else it carries, kept as it was. */
export type Effect = { kind: string } & Record<string, unknown>;

/** The kind's definition, or undefined for one this build does not know. */
export function kindOf(group: CueGroup, kind: string): CueKind | undefined {
  const k = kind.toLowerCase();
  return CUE_KINDS[group].find((d) => d.kind === k);
}

const numberOf = (v: unknown): number | null => {
  const n = typeof v === "string" && v.trim() !== "" ? Number(v) : v;
  return typeof n === "number" && Number.isFinite(n) ? n : null;
};

/** One field's value as the render reads it: a number held to its range (a numeric choice moved to the nearest, a tie to the later: 0 is
 * right), a word lowercased when it is one of the choices and kept as written when not; null to leave it out. */
function fieldValue(f: CueField, v: unknown): number | string | null {
  if (f.choices && typeof f.choices[0]?.value === "string") {
    if (typeof v !== "string" || !v.trim()) return null;
    const word = v.trim().toLowerCase();
    return f.choices.some((c) => c.value === word) ? word : v;
  }
  const n = numberOf(v);
  if (n === null) return null;
  if (f.choices) return f.choices.reduce((best, c) => (Math.abs((c.value as number) - n) <= Math.abs((best as number) - n) ? c.value : best), f.choices[0].value);
  return Math.min(Math.max(n, f.min ?? -Infinity), f.max ?? Infinity);
}

/** A known kind holding a word its pick does not take (a flash in purple): the render leaves the whole cue out. */
export function refused(group: CueGroup, effect: Effect): boolean {
  const def = kindOf(group, effect.kind);
  return !!def?.fields.some((f) => f.choices && typeof f.choices[0]?.value === "string" && typeof effect[f.key] === "string" && !f.choices.some((c) => c.value === effect[f.key]));
}

/**
 * A row's camera, look or mix as the render reads it: a known kind with its numbers held to their ranges (anything else it carried stays), and
 * a kind this build does not know kept exactly as written, so a save never loses it. Undefined when it is not an object with a kind.
 */
export function effectOf(group: CueGroup, raw: unknown): Effect | undefined {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const r = raw as Record<string, unknown>;
  if (typeof r.kind !== "string" || !r.kind.trim()) return undefined;
  const def = kindOf(group, r.kind);
  if (!def) return { ...r } as Effect;
  const out: Effect = { ...r, kind: def.kind };
  for (const f of def.fields) {
    if (!(f.key in r)) continue;
    const v = fieldValue(f, r[f.key]);
    if (v === null) delete out[f.key];
    else out[f.key] = v;
  }
  return out;
}

const plain = (n: number) => String(Number(n.toFixed(3)));

/** One field's value in words, its default when the row leaves it out: "right", "1.5 s", "to the end of the shot". */
function fieldWords(f: CueField, v: unknown): string {
  const value = v ?? f.default;
  if (value === undefined) return f.unset ?? "";
  const choice = f.choices?.find((c) => c.value === value);
  const text = choice ? choice.label : typeof value === "number" ? plain(value) : String(value);
  return f.unit ? `${text} ${f.unit}` : text;
}

/** How a camera move, look or mix change reads, the defaults filled in: "Punch 1.06", "Whip pan right, 0.3", "Dead air 1.5 s". A kind the
 * editor does not offer yet says so; one this build does not know is named as written. */
export function effectWords(group: CueGroup, effect: Effect): string {
  const def = kindOf(group, effect.kind);
  if (!def) return `${effect.kind} (not a kind the render knows: it does nothing)`;
  const values = def.fields.map((f) => fieldWords(f, effect[f.key])).filter(Boolean);
  const note = refused(group, effect) ? " (a colour this kind does not take: the render leaves it out)" : def.enabled ? "" : " (not offered in the editor yet)";
  return `${def.name}${values.length ? ` ${values.join(", ")}` : ""}${note}`;
}

/** The short label the Timeline draws next to the cue's flag ("flash", "dead air 1.5 s", "whip pan"), or null where the flag's ✣ says it. */
export function effectChip(group: CueGroup, effect: Effect): string | null {
  const def = kindOf(group, effect.kind);
  if (!def) return `${effect.kind}?`;
  if (!def.chip) return null;
  const field = def.chipField ? def.fields.find((f) => f.key === def.chipField) : undefined;
  return `${def.name.toLowerCase()}${field ? ` ${fieldWords(field, effect[field.key])}` : ""}`;
}

/** How long a change to the mix lasts: its own seconds, else the render's 1.5 s. */
export function mixSeconds(mix: Effect): number {
  const n = numberOf(mix.seconds);
  return n !== null && n > 0 ? n : MIX_SECONDS;
}

/** Emphasis as a row holds it: `true` or an object (`{scale?}`, a numeric scale made a number, anything else kept); undefined for none. */
export function emphasisOf(raw: unknown): true | Record<string, unknown> | undefined {
  if (raw === true) return true;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const r = { ...(raw as Record<string, unknown>) };
  if ("scale" in r) {
    const v = fieldValue(EMPHASIS.scale, r.scale);
    if (v === null) delete r.scale;
    else r.scale = v;
  }
  return r;
}

/** "Emphasis" or "Emphasis ×1.4", and whether the editor offers it yet. */
export function emphasisWords(emphasis: true | Record<string, unknown>): string {
  const scale = emphasis === true ? undefined : numberOf(emphasis.scale);
  return `${EMPHASIS.name}${scale !== null && scale !== undefined ? ` ×${plain(scale)}` : ""}${EMPHASIS.enabled ? "" : " (not offered in the editor yet)"}`;
}

/** One labelled chip beside a cue's flag on the Timeline: what it is, its words for the tooltip, and whether the render knows it / does it yet. */
export interface CueChip {
  group: CueGroup | "emphasis";
  chip: string;
  words: string;
  unknown: boolean;
  pending: boolean;
}

const GROUP_NAMES: Record<CueGroup, string> = { camera: "Camera", look: "Look", mix: "Mix" };

/** The chips a cue's flag gets for what its ♪ ✣ ▣ glyphs do not say: a newer camera move, a look, a change to the mix, emphasis. A kind the
 * render does not know is shown by its own name with a "?", never left out. */
export function cueChips(cue: { camera?: Effect | null; look?: Effect; mix?: Effect; emphasis?: true | Record<string, unknown> }): CueChip[] {
  const out: CueChip[] = [];
  for (const group of ["camera", "look", "mix"] as const) {
    const effect = cue[group];
    const chip = effect ? effectChip(group, effect) : null;
    if (!effect || chip === null) continue;
    const def = kindOf(group, effect.kind);
    out.push({ group, chip, words: `${GROUP_NAMES[group]}: ${effectWords(group, effect)}`, unknown: !def || refused(group, effect), pending: !!def && !def.enabled });
  }
  if (cue.emphasis) {
    out.push({ group: "emphasis", chip: "emphasis", words: `${emphasisWords(cue.emphasis)}: the word after it stands out in the captions`, unknown: false, pending: !EMPHASIS.enabled });
  }
  return out;
}
