/**
 * What a cue on a word can do (lib/wordCues.ts), kind by kind: the one place for every kind's name, the numbers it takes, their ranges and what
 * the Screenplay Studio render does when one is left out. The beat page's editor and the Timeline both read it, so a change to the render's
 * kinds is a change here.
 *
 * `enabled` says whether the editor offers a kind. One listed with `enabled: false` (the render may not do it yet): a row that already holds it
 * keeps it, the editor shows it as written and the Timeline draws it, but nobody picks it by mistake. Turning one on is that one line.
 * A kind not listed at all is kept and shown by its own name. Pure: no fetching.
 *
 * Where the numbers come from: punch, shake and nudge are the render's (camera.py). For the newer kinds only these come from the cue contract:
 * the kind names, dead air's and duck's 1.5 s, tint's "to the end of the beat", whip pan's x of -1 or 1, and the 0 to 1 amounts of flash, tint,
 * blur and duck. Every other default and range here (whip pan's and sway's amounts, the looks' seconds, flash's colours, duck's 0.3, emphasis's
 * scale) is assumed until the render's own are known. Only `held` ranges (the render's or the contract's) are applied to what a row holds;
 * the others bound the editor's inputs and leave a stored value as written.
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
  /** A typed number: the editor's input keeps to this range. */
  min?: number;
  max?: number;
  step?: number;
  /** A pick from these instead. */
  choices?: readonly CueChoice[];
  /** The render holds a value to the range (or a number to the nearest choice), so a row's value is held to it too. Else a row keeps what it
   * says even outside the range, which is only assumed. */
  held?: boolean;
  /** What the render uses when it is left out. */
  default?: number | string;
  /** How leaving it out reads when it has no single default ("to the end of the beat"). */
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
}

const seconds = (label: string, fallback: number | undefined, unset?: string): CueField => ({
  key: "seconds",
  label,
  min: 0.1,
  max: 30,
  step: 0.1,
  unit: "s",
  ...(fallback !== undefined ? { default: fallback } : {}),
  ...(unset ? { unset } : {}),
});
const share = (key: string, label: string, fallback: number, held = true): CueField => ({ key, label, min: 0, max: 1, step: 0.05, default: fallback, held });

/** Camera moves at the cue, on top of the beat's own (render camera.py `cue_of`). */
export const CAMERA: readonly CueKind[] = [
  { kind: "punch", name: "Punch", label: "Punch (a quick zoom in)", enabled: true, chip: false, fields: [{ key: "amount", label: "How far in, 1 to 1.5", min: 1, max: 1.5, step: 0.01, default: 1.06, held: true }] },
  { kind: "shake", name: "Shake", label: "Shake", enabled: true, chip: false, fields: [{ key: "amount", label: "How hard, % of the frame, 0 to 10", min: 0, max: 10, step: 0.1, default: 1.2, held: true }] },
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
    label: "Whip pan (a fast pan away)",
    enabled: true,
    chip: true,
    fields: [
      { key: "x", label: "Direction", choices: [{ value: -1, label: "left" }, { value: 1, label: "right" }], default: 1, held: true },
      share("amount", "How far, a share of the frame, 0 to 1", 0.3, false),
    ],
  },
  {
    kind: "sway",
    name: "Sway",
    label: "Sway (a slow rock)",
    enabled: true,
    chip: true,
    fields: [{ key: "amount", label: "How far, % of the frame, 0 to 10", min: 0, max: 10, step: 0.1, default: 1.5 }, seconds("For how long, seconds", 2)],
  },
];

const TINTS: readonly CueChoice[] = ["sepia", "mono", "cold", "warm"].map((c) => ({ value: c, label: c }));
const BLACK_WHITE: readonly CueChoice[] = ["black", "white"].map((c) => ({ value: c, label: c }));

/** What the picture looks like from the cue. */
export const LOOK: readonly CueKind[] = [
  { kind: "flash", name: "Flash", label: "Flash (a burst of light)", enabled: true, chip: true, fields: [share("amount", "How bright at its peak, 0 to 1", 0.8), { key: "color", label: "Colour", choices: [...BLACK_WHITE].reverse(), default: "white" }] },
  { kind: "dip", name: "Dip", label: "Dip (to a colour and back)", enabled: true, chip: true, fields: [{ key: "color", label: "Colour", choices: BLACK_WHITE, default: "black" }, seconds("For how long, seconds", 0.5)] },
  { kind: "freeze", name: "Freeze", label: "Freeze (the picture holds still)", enabled: false, chip: true, fields: [seconds("For how long, seconds", 1)] },
  {
    kind: "tint",
    name: "Tint",
    label: "Tint (a colour grade)",
    enabled: true,
    chip: true,
    fields: [{ key: "color", label: "Grade", choices: TINTS, default: "sepia" }, share("amount", "How strong, 0 to 1", 0.5), seconds("For how long, seconds", undefined, "to the end of the beat")],
  },
  { kind: "blur", name: "Blur", label: "Blur", enabled: false, chip: true, fields: [share("amount", "How strong, 0 to 1", 0.5), seconds("For how long, seconds", 1)] },
  { kind: "vignette", name: "Vignette", label: "Vignette (dark edges)", enabled: true, chip: true, fields: [seconds("For how long, seconds", 2)] },
  { kind: "glitch", name: "Glitch", label: "Glitch", enabled: false, chip: true, fields: [seconds("For how long, seconds", 0.3)] },
];

/** The default length of a change to the mix: the render's, and how long the Timeline draws it. */
export const MIX_SECONDS = 1.5;

/** What is heard under the voice from the cue; the voice itself is never touched. */
export const MIX: readonly CueKind[] = [
  { kind: "dead-air", name: "Dead air", label: "Dead air (ambience, music and effects go silent)", enabled: true, chip: true, chipField: "seconds", fields: [seconds("For how long, seconds", MIX_SECONDS)] },
  { kind: "duck", name: "Duck", label: "Duck (music and ambience dip)", enabled: true, chip: true, fields: [share("amount", "Down to, 0 to 1", 0.3), seconds("For how long, seconds", MIX_SECONDS)] },
];

/** The word after the cue stands out in the captions: `true`, or `{scale}` for how much bigger. */
export const EMPHASIS = {
  enabled: false,
  name: "Emphasis",
  label: "Emphasise the word after it in the captions",
  scale: { key: "scale", label: "How much bigger, 1 to 2", min: 1, max: 2, step: 0.05, default: 1.2 } satisfies CueField,
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

/** One field's value as the render reads it: a number (held to a `held` range, a numeric choice moved to the nearest), a pick as written;
 * null to leave it out. */
function fieldValue(f: CueField, v: unknown): number | string | null {
  if (f.choices && typeof f.choices[0]?.value === "string") return typeof v === "string" && v ? v : null;
  const n = numberOf(v);
  if (n === null || !f.held) return n;
  if (f.choices) return f.choices.reduce((best, c) => (Math.abs((c.value as number) - n) < Math.abs((best as number) - n) ? c.value : best), f.choices[0].value);
  return Math.min(Math.max(n, f.min ?? -Infinity), f.max ?? Infinity);
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

/** One field's value in words, its default when the row leaves it out: "right", "1.5 s", "to the end of the beat". */
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
  return `${def.name}${values.length ? ` ${values.join(", ")}` : ""}${def.enabled ? "" : " (not offered in the editor yet)"}`;
}

/** The short label the Timeline draws next to the cue's flag ("flash", "dead air 1.5 s", "whip pan"), or null where the flag's ✣ says it. */
export function effectChip(group: CueGroup, effect: Effect): string | null {
  const def = kindOf(group, effect.kind);
  if (!def) return `${effect.kind}?`;
  if (!def.chip) return null;
  const field = def.chipField ? def.fields.find((f) => f.key === def.chipField) : undefined;
  return `${def.name.toLowerCase()}${field ? ` ${fieldWords(field, effect[field.key])}` : ""}`;
}

/** How long a change to the mix lasts: its own seconds, else the default (the contract's 1.5 s). */
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
    out.push({ group, chip, words: `${GROUP_NAMES[group]}: ${effectWords(group, effect)}`, unknown: !def, pending: !!def && !def.enabled });
  }
  if (cue.emphasis) {
    out.push({ group: "emphasis", chip: "emphasis", words: `${emphasisWords(cue.emphasis)}: the word after it stands out in the captions`, unknown: false, pending: !EMPHASIS.enabled });
  }
  return out;
}
