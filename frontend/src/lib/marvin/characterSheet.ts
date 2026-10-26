/**
 * Marvin — a character's sheet: the bubble lines and mood settings a library pack carries (Admin → Character
 * library), and that a workspace (AI settings → Persona) or an agent (Settings → Agents) gets a copy of when
 * it picks the pack (services/ai/character_library.py: apply_pack_persona).
 *
 * The fields are built as HTML strings, so the server-rendered pages and the Agents page's script-built
 * Edit form share them, and read back from whatever element holds them. Each list is one textarea, one line
 * per row; an empty list falls back (the bubble's built-in lines, or the workspace's).
 */

import type { Voice } from "@/lib/marvin/persona";

const BUBBLE_LISTS = [
  { key: "greetings", label: "Greetings", hint: "When the panel opens." },
  { key: "taglines", label: "Taglines", hint: "Rotate under the name; keep them short." },
  { key: "thinking", label: "Thinking", hint: "While it works on a request." },
  { key: "errors", label: "Errors", hint: "Open an error; the real message follows." },
  { key: "emotes", label: "Emotes", hint: "Stage directions, like *smiles*." },
] as const;

type BubbleListKey = (typeof BUBBLE_LISTS)[number]["key"];
export type BubbleLines = Partial<Record<BubbleListKey, string[]>>;

/** The Social Battery's settings (schemas/group/ai_settings.py: MoodSettings). Stored, read by nothing yet. */
type MoodBand = { greetings?: string[]; taglines?: string[] };
export type MoodSettings = {
  drains?: "use" | "treatment" | null;
  meter?: "visible" | "hidden" | null;
  memory?: "daily" | "weeks" | null;
  absence?: "recharges" | "cools" | "neutral" | null;
  low?: MoodBand | null;
  high?: MoodBand | null;
};

const MOOD_CHOICES = [
  {
    key: "drains",
    label: "What drains it",
    options: [
      ["use", "Any use — a social battery"],
      ["treatment", "Only how it's treated — trust"],
    ],
  },
  {
    key: "meter",
    label: "Meter",
    options: [
      ["visible", "Shown to the person"],
      ["hidden", "Hidden — noticed only through behaviour"],
    ],
  },
  {
    key: "memory",
    label: "Memory",
    options: [
      ["daily", "Starts fresh each day"],
      ["weeks", "Builds over weeks"],
    ],
  },
  {
    key: "absence",
    label: "After a long absence",
    options: [
      ["recharges", "Recharges"],
      ["cools", "Cools a little"],
      ["neutral", "Neither"],
    ],
  },
] as const;

const MOOD_BANDS = [
  { key: "low", label: "Low" },
  { key: "high", label: "High" },
] as const;
const BAND_LISTS = ["greetings", "taglines"] as const;

const esc = (s: unknown): string =>
  String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

/** A textarea's lines: trimmed, blank rows dropped. */
export function linesOf(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

/** The five bubble-line lists as fields; `placeholders` (a voice) shows what an empty list falls back to. */
export function linesFieldsHtml(lines: BubbleLines | null | undefined, placeholders?: Partial<Voice>): string {
  const fields = BUBBLE_LISTS.map(
    (list) => `<label class="form-field">
      <span class="label">${list.label}</span>
      <textarea class="input sheet-lines-list" data-list="${list.key}" rows="4" placeholder="${esc((placeholders?.[list.key] ?? []).slice(0, 4).join("\n"))}">${esc((lines?.[list.key] ?? []).join("\n"))}</textarea>
      <small class="hint">${list.hint}</small>
    </label>`,
  ).join("");
  return `<div class="sheet-lines-grid">${fields}</div>`;
}

/** The lines `root`'s list fields hold; null when every list is empty. */
export function readLines(root: ParentNode): BubbleLines | null {
  const lines: BubbleLines = {};
  for (const area of root.querySelectorAll<HTMLTextAreaElement>(".sheet-lines-list"))
    lines[area.dataset.list as BubbleListKey] = linesOf(area.value);
  return Object.values(lines).some((l) => l?.length) ? lines : null;
}

export function fillLines(root: ParentNode, lines: BubbleLines | null | undefined): void {
  for (const area of root.querySelectorAll<HTMLTextAreaElement>(".sheet-lines-list"))
    area.value = (lines?.[area.dataset.list as BubbleListKey] ?? []).join("\n");
}

/** The Social Battery's settings (services/ai/mood.py), collapsed until some are set. They apply once the workspace switches the
 * Social Battery on (AI settings → Persona). */
export function moodFieldsHtml(mood: MoodSettings | null | undefined): string {
  const selects = MOOD_CHOICES.map((choice) => {
    const current = mood?.[choice.key] ?? "";
    const options = [["", "Not set"], ...choice.options]
      .map(([value, label]) => `<option value="${value}"${value === current ? " selected" : ""}>${esc(label)}</option>`)
      .join("");
    return `<label class="form-field"><span class="label">${choice.label}</span><select class="input mood-choice" data-mood="${choice.key}">${options}</select></label>`;
  }).join("");
  const bands = MOOD_BANDS.map((band) =>
    BAND_LISTS.map(
      (list) => `<label class="form-field">
        <span class="label">${band.label} — ${list}</span>
        <textarea class="input mood-lines" data-band="${band.key}" data-list="${list}" rows="3">${esc((mood?.[band.key]?.[list] ?? []).join("\n"))}</textarea>
      </label>`,
    ).join(""),
  ).join("");
  return `<details class="mood-fields"${hasMood(mood) ? " open" : ""}>
    <summary>Mood <span class="mood-badge">the Social Battery</span></summary>
    <p class="hint">A mood meter per character: how it feels about the person it's talking to changes its greetings, taglines and asides — flavour only, never the help. It runs once the workspace switches the Social Battery on (AI settings → Persona); each person can reset their own meter.</p>
    <div class="mood-grid">${selects}</div>
    <p class="hint">What it says in a low or a high mood, in place of its usual greetings and taglines. One line per row.</p>
    <div class="mood-grid">${bands}</div>
  </details>`;
}

function hasMood(mood: MoodSettings | null | undefined): boolean {
  return (
    !!mood &&
    Object.values(mood).some((v) => (v && typeof v === "object" ? Object.values(v).some((l) => l?.length) : !!v))
  );
}

/** The mood settings `root`'s fields hold; null when nothing is set. */
export function readMood(root: ParentNode): MoodSettings | null {
  const mood: Record<string, unknown> = {};
  for (const select of root.querySelectorAll<HTMLSelectElement>(".mood-choice"))
    if (select.value) mood[select.dataset.mood!] = select.value;
  for (const area of root.querySelectorAll<HTMLTextAreaElement>(".mood-lines")) {
    const lines = linesOf(area.value);
    if (!lines.length) continue;
    const band = (mood[area.dataset.band!] ?? {}) as MoodBand;
    band[area.dataset.list as keyof MoodBand] = lines;
    mood[area.dataset.band!] = band;
  }
  return Object.keys(mood).length ? (mood as MoodSettings) : null;
}

/** Replace the mood fields `root` holds with ones showing `mood`. */
export function fillMood(root: ParentNode, mood: MoodSettings | null | undefined): void {
  const box = root.querySelector(".mood-fields");
  if (box) box.outerHTML = moodFieldsHtml(mood);
}
