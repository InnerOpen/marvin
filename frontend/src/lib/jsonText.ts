/** A row with no list or object inside it (a clip's word time `{word, start, end}`), which reads on one line. */
const flat = (v: unknown): boolean => v === null || typeof v !== "object" || (!Array.isArray(v) && Object.values(v as object).every((x) => x === null || typeof x !== "object"));

/**
 * A json field's value as the text in its box: indented, as it always was. A read-only list of flat rows (a clip's word times, filled in by a
 * job) is one row to a line instead, so a list of a hundred words reads down the box rather than five lines a word. Both are the same JSON.
 */
export function jsonText(value: unknown, readOnly = false): string {
  if (value === undefined || value === null || value === "") return "";
  if (readOnly && Array.isArray(value) && value.length > 0 && value.every(flat)) return `[\n${value.map((v) => `  ${JSON.stringify(v)}`).join(",\n")}\n]`;
  return JSON.stringify(value, null, 2);
}
