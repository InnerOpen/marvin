/**
 * Tones — how a run's work product reads, separate from the persona (services/ai/tones.py). The built-ins
 * auto / professional / playful plus the workspace's own, from GET /api/groups/ai-settings/tones. Pure
 * helpers shared by the AI settings editor, the agent and Ask pickers and the bubble's `/tone` command.
 */

/** A tone slug: a built-in or one of the workspace's own. */
export type ToneSlug = string;
export type PersonaRule = "frame" | "everywhere" | "drop";

export interface Tone {
  slug: ToneSlug;
  name: string;
  instructions: string;
  persona: PersonaRule;
  description?: string | null;
  builtin: boolean;
  hidden: boolean;
  /** Slugs of the workspace agents that default to this tone (it can't be deleted while any do). */
  usedBy: string[];
}

export interface TonesState {
  tones: Tone[];
  defaultTone: ToneSlug;
  maxCustomTones: number;
  maxNameChars: number;
  maxInstructionsChars: number;
}

export const PERSONA_RULES: { value: PersonaRule; label: string; hint: string }[] = [
  { value: "frame", label: "Frame only", hint: "The persona greets and frames; work product follows this tone." },
  { value: "everywhere", label: "Everywhere", hint: "The persona applies to everything, work product included." },
  { value: "drop", label: "Drop the persona", hint: "No persona for the run — best for client-facing copy." },
];

/** The built-in tones, for when the tones endpoint can't be reached. */
export const BUILTIN_TONES: Tone[] = [
  {
    slug: "auto",
    name: "Auto",
    instructions: "",
    persona: "frame",
    description: "Voice for chat, plain for work.",
    builtin: true,
    hidden: false,
    usedBy: [],
  },
  {
    slug: "professional",
    name: "Professional",
    instructions: "",
    persona: "drop",
    description: "Plain everywhere, no persona.",
    builtin: true,
    hidden: false,
    usedBy: [],
  },
  {
    slug: "playful",
    name: "Playful",
    instructions: "",
    persona: "everywhere",
    description: "The persona applies to everything.",
    builtin: true,
    hidden: false,
    usedBy: [],
  },
];

/** A tone by slug or (case-insensitive) name — what `/tone <name|slug>` types. Hidden tones aren't offered. */
export function findTone(tones: Tone[], ref: string): Tone | undefined {
  const key = ref.trim().toLowerCase();
  if (!key) return undefined;
  const visible = tones.filter((t) => !t.hidden);
  return visible.find((t) => t.slug === key) ?? visible.find((t) => t.name.toLowerCase() === key);
}

/** The tones a picker offers: every visible one, plus `keep` (a stored value) even if it's hidden since. */
export function pickerTones(tones: Tone[], keep?: string | null): Tone[] {
  return tones.filter((t) => !t.hidden || t.slug === keep);
}

/** `<option>`s for a tone `<select>`; `selected` is a slug ("" for a leading "workspace default" option). */
export function toneOptions(
  tones: Tone[],
  selected: string | null | undefined,
  opts: { inherit?: string } = {},
): string {
  const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
  const value = selected ?? "";
  const known = tones.some((t) => t.slug === value);
  const rows = pickerTones(tones, value).map((t) => [t.slug, t.description ? `${t.name} — ${t.description}` : t.name]);
  if (opts.inherit !== undefined) rows.unshift(["", opts.inherit]);
  // A stored slug the workspace no longer has still shows, so saving the form doesn't silently change it.
  if (value && !known) rows.push([value, `${value} (deleted — falls back to the default)`]);
  return rows
    .map(([v, label]) => `<option value="${esc(v)}"${v === value ? " selected" : ""}>${esc(label)}</option>`)
    .join("");
}
