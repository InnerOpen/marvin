/**
 * Fields that take turns (`exclusive_with`): a story's script is written in its Fountain box OR attached as its Fountain file, not both.
 * Either side naming the other is enough; a name that is no field of the type is ignored. The server refuses a write that fills the
 * second of a pair (services/content_validator.py `exclusive_conflict`); the form shows the other one closed while one is filled.
 * The pure parts, for the form's script (components/SchemaForm.astro) and the guided setup's upload step (lib/wizardActions.ts).
 */

export interface PairField {
  key: string;
  label: string;
  type: string;
  exclusive_with?: unknown;
}

/** Whether a field's value holds something: nothing, blank text and an empty list hold nothing (as the server reads it). */
export function isFilled(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === "string") return value.trim() !== "";
  if (Array.isArray(value)) return value.some(isFilled);
  if (typeof value === "object") return Object.keys(value as object).length > 0;
  return true;
}

const namesOf = (field: PairField): string[] => (Array.isArray(field.exclusive_with) ? field.exclusive_with.filter((k): k is string => typeof k === "string") : []);

/** The fields `key` takes turns with, from either side, in schema order. */
export function partnersOf<F extends PairField>(fields: F[], key: string): F[] {
  const self = fields.find((f) => f.key === key);
  if (!self) return [];
  const named = new Set(namesOf(self));
  return fields.filter((f) => f.key !== key && (named.has(f.key) || namesOf(f).includes(key)));
}

const isText = (type: string) => type === "text" || type === "textarea" || type === "markdown";

/** What filling `field` is, in words for "… here instead": write it, attach a file, link one. */
function fillWords(field: PairField): string {
  if (isText(field.type)) return "write it here instead";
  if (field.type.startsWith("asset")) return "attach a file here instead";
  if (field.type.startsWith("resource")) return "link one here instead";
  return "fill this in instead";
}

/** How to empty `field`, in words: remove the file, clear the text. */
function freeWords(field: PairField): string {
  if (field.type.startsWith("asset")) return "remove the file";
  if (field.type.startsWith("resource")) return "remove the link";
  if (isText(field.type)) return "clear that text";
  return "empty it";
}

const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** The line under a field that is closed because `held` (its partner) holds something:
 *  "“Fountain file” holds it. Remove the file to write it here instead." */
export function blockedNote(field: PairField, held: PairField): string {
  return `“${held.label}” holds it${isText(held.type) ? " as text" : ""}. ${capital(freeWords(held))} to ${fillWords(field)}.`;
}

/** The warning on both fields of a pair that were both filled when the page opened (saved before the rule): nothing is hidden. */
export function conflictNote(field: PairField, other: PairField): string {
  const free = (f: PairField) => freeWords(f).replace("that text", "the text");
  return `Both “${field.label}” and “${other.label}” are filled in, and only one is used. Empty the one you do not want: ${free(field)} here, or ${free(other)} in “${other.label}”.`;
}

/** The refusal of a guided upload into `field` while `held` holds something: said before anything is uploaded. */
export function uploadRefusal(field: PairField, held: PairField, title: string): string {
  return `${title} already has “${held.label}” filled in, and “${field.label}” is used instead of it, not with it. Empty “${held.label}” first (${freeWords(held).replace("that text", "the text")} on the entry's page, or in the step that edits it), then upload here.`;
}

export interface FieldState {
  /** The partner that holds something while this field is empty: the field is shown closed, with `blockedNote`. */
  blockedBy: string | null;
  /** Partners that hold something while this field does too (data from before the rule): both show `conflictNote`. */
  conflicts: string[];
}

/** How each field of a pair stands, from the values as they are now (keys of fields in no pair are left out). */
export function exclusiveState(fields: PairField[], values: Record<string, unknown>): Record<string, FieldState> {
  const out: Record<string, FieldState> = {};
  for (const field of fields) {
    const partners = partnersOf(fields, field.key);
    if (!partners.length) continue;
    const filledPartners = partners.filter((p) => isFilled(values[p.key])).map((p) => p.key);
    const mine = isFilled(values[field.key]);
    out[field.key] = { blockedBy: mine ? null : (filledPartners[0] ?? null), conflicts: mine ? filledPartners : [] };
  }
  return out;
}

/** The refusal of a write that leaves both fields of a pair filled when they were not both filled before (the server's rule,
 *  services/content_validator.py `exclusive_conflict`), said by the page before it asks: null when the write may go ahead. */
export function writeRefusal(fields: PairField[], before: Record<string, unknown>, after: Record<string, unknown>): string | null {
  for (const a of fields) {
    for (const b of partnersOf(fields, a.key)) {
      if (!(isFilled(after[a.key]) && isFilled(after[b.key]))) continue;
      const hadA = isFilled(before[a.key]);
      const hadB = isFilled(before[b.key]);
      if (hadA && hadB) continue;
      if (!hadA && !hadB) return `“${a.label}” and “${b.label}” take one or the other, and this would fill both. Empty one of them and save again.`;
      const [held, added] = hadA ? [a, b] : [b, a];
      return `“${held.label}” already holds something, and “${added.label}” is used instead of it, not with it. Empty “${held.label}” first (${freeWords(held).replace("that text", "the text")}), then fill “${added.label}”.`;
    }
  }
  return null;
}
