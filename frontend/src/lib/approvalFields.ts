/**
 * An approval's boxes (`fields`: the prompt a paid step will send, shown so it can be changed before approving). What a
 * card sends when it is decided: only the boxes a person changed, so one left alone is sent as it was asked, byte for
 * byte. Shared by Automation → Approvals and a guided setup's cards; free of the DOM so it runs under `node --test`
 * (approvalFields.test.mjs).
 */

export interface ApprovalField {
  name: string;
  label: string;
  /** `text` (one line) or `textarea`. */
  type?: string;
  /** The text as asked: what the steps after it use unless it is changed. */
  value: string;
  maxLength?: number;
  required?: boolean;
  /** It starts from what a Redo with changes left, not from the workflow's own text. */
  carried?: boolean;
}

/** Line ends as one `\n` (a form posts `\r\n`). */
const normal = (text: string): string => text.replace(/\r\n?/g, "\n");

/** Whether `text` is the box's text as asked. A text box drops one leading line break, and a form posts `\r\n`: neither is a change. */
export function unchanged(field: ApprovalField, text: string): boolean {
  const asked = normal(field.value ?? "");
  const now = normal(text);
  return now === asked || `\n${now}` === asked;
}

/** The boxes to send: {name: text} for each one changed (`given`: what the boxes hold now). Unknown names are left out. */
export function changedFields(
  fields: readonly ApprovalField[] | null | undefined,
  given: Record<string, string>,
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const field of fields ?? []) {
    const text = given[field.name];
    if (typeof text === "string" && !unchanged(field, text)) out[field.name] = normal(text);
  }
  return out;
}

/** The form field a box is posted as on a guided setup's card. */
export const fieldInputName = (name: string): string => `field.${name}`;

/** What a posted card's boxes hold, by name (`field.<name>` in the form), all of them: the server keeps a box whose text is
 *  the one it asked with as it was (a page posting a form doesn't hold the text it was drawn with). */
export function fieldsFromForm(form: Iterable<[string, unknown]>): Record<string, string> {
  const given: Record<string, string> = {};
  for (const [key, value] of form) {
    if (key.startsWith("field.") && key.length > 6 && typeof value === "string") given[key.slice(6)] = normal(value);
  }
  return given;
}

/** A choice's button text: the `redo` choice says it carries the change once a box is changed. */
export function choiceLabel(label: string, redo: string | null | undefined, changed: boolean): string {
  return changed && redo && label === redo ? `${label} with changes` : label;
}

/** How tall a box starts: its text's lines (a long line wraps at about 90 characters), between 3 and 14. */
export function boxRows(text: string): number {
  const lines = normal(text ?? "")
    .split("\n")
    .reduce((n, line) => n + Math.max(1, Math.ceil(line.length / 90)), 0);
  return Math.min(14, Math.max(3, lines));
}
