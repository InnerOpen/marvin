/**
 * A json field that can start from another field's choice (`suggest` in its definition).
 *
 *   "suggest": { "from": "camera", "values": { "Push in": {...}, "Rocking": {...} }, "note": "From {pick}. Edit to make it your own." }
 *
 * While the box is empty or still holds the suggestion, it shows the one for the choice in the `from` field, and nothing is saved from it.
 * Once the person changes the text it is theirs and is saved. Clearing the box goes back to following the choice. No DOM here.
 */

export interface Suggest {
  from: string;
  values: Record<string, unknown>;
  note?: string;
}

/** How a choice is compared: "Push in", "push-in" and "push_in" are one. */
export function normalChoice(value: unknown): string {
  return String(value ?? "").trim().toLowerCase().replace(/[\s_-]+/g, "-");
}

/** Reads the definition's `suggest`, or null when it is not usable. */
export function readSuggest(raw: unknown): Suggest | null {
  const s = raw as Partial<Suggest> | null | undefined;
  if (!s || typeof s !== "object" || typeof s.from !== "string" || !s.from) return null;
  if (!s.values || typeof s.values !== "object" || Array.isArray(s.values)) return null;
  return { from: s.from, values: s.values, note: typeof s.note === "string" ? s.note : undefined };
}

/** The suggested text (pretty JSON) for a choice, or "" when the choice has none. */
export function suggestionFor(suggest: Suggest, pick: unknown): string {
  const wanted = normalChoice(pick);
  if (!wanted) return "";
  for (const [name, value] of Object.entries(suggest.values)) {
    if (normalChoice(name) === wanted) return JSON.stringify(value, null, 2);
  }
  return "";
}

/** The note under the box for a choice ("From Push in. Edit to make it your own."), or "" when nothing is suggested. */
export function noteFor(suggest: Suggest, pick: unknown, shown: string): string {
  if (!shown) return "";
  const template = suggest.note ?? "From {pick}. Edit it to make it your own.";
  return template.replace("{pick}", String(pick ?? "").trim());
}

/**
 * What the box shows after the choice changed (or on load). `current` is the box now, `lastSuggested` the suggestion it was given last.
 * The box follows the choice only while it is empty or still the old suggestion; text the person wrote stays.
 */
export function nextBox(current: string, lastSuggested: string, suggested: string): { text: string; suggested: boolean } {
  if (current.trim() === "" || current === lastSuggested) return { text: suggested, suggested: suggested !== "" };
  return { text: current, suggested: false };
}
