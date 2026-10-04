/**
 * Tones — how a run delivers its work, separate from the persona (who the assistant is; services/ai/tones.py). The built-ins
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
  { value: "frame", label: "Frame only", hint: "The character greets and frames; work product follows this tone." },
  { value: "everywhere", label: "Everywhere", hint: "The character applies to everything, work product included." },
  {
    value: "drop",
    label: "Drop the character",
    hint: "No character for the run, just this tone — best for client-facing copy.",
  },
];

/** POST /api/groups/ai-settings/tones/preview: the whole section plus its parts, labelled by where they come from. */
export interface TonePreview {
  /** Exactly what is appended to an agent's system prompt. */
  clause: string;
  tokens: number;
  persona: PersonaRule;
  /** The persona rule in plain words. */
  personaSummary: string;
  /** Whether the workspace has a character to use (its Persona, or Marvin's default voice). */
  hasPersona: boolean;
  /** From your Persona: the Character block ("" when this tone drops it, or there is none). */
  character: string;
  /** From this tone: its persona rule's scope and its instructions. */
  fromTone: string;
  /** The precedence rule, when a character and a tone's instructions both apply. */
  rule: string;
}

/** What the tone editor's preview shows for each part: the text, or a note saying why there is none. */
export function previewSections(p: TonePreview): {
  summary: string;
  character: string;
  characterNote: string;
  fromTone: string;
  fromToneNote: string;
  rule: string;
} {
  let characterNote = "";
  if (!p.character) {
    characterNote =
      p.persona === "drop"
        ? "Not used — this tone drops the character."
        : "No persona set, so there's no character to add.";
  }
  return {
    summary: p.personaSummary,
    character: p.character,
    characterNote,
    fromTone: p.fromTone,
    fromToneNote: p.fromTone ? "" : "Nothing — this tone only places the character, and there is none.",
    rule: p.rule,
  };
}

/** The built-in tones, for when the tones endpoint can't be reached. */
export const BUILTIN_TONES: Tone[] = [
  {
    slug: "auto",
    name: "Auto",
    instructions: "",
    persona: "frame",
    description: "Character for chat, plain for work.",
    builtin: true,
    hidden: false,
    usedBy: [],
  },
  {
    slug: "professional",
    name: "Professional",
    instructions: "",
    persona: "drop",
    description: "Plain everywhere, no character.",
    builtin: true,
    hidden: false,
    usedBy: [],
  },
  {
    slug: "playful",
    name: "Playful",
    instructions: "",
    persona: "everywhere",
    description: "The character applies to everything.",
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
