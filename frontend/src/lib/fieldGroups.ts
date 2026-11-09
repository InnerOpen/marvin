// A schema field may name a `group`. The form puts a group's fields in one collapsible section, placed where the group's first field is;
// fields with no group stay where they are. Pure, so the form and the tests share it.

export interface Segment<F> {
  /** The group's name, or null for a single field that has none. */
  group: string | null;
  fields: F[];
  /** Shown open: a field in it has an error, which must not hide in a folded section. */
  open: boolean;
  /** How many of its fields hold something. */
  filled: number;
}

const isFilled = (v: unknown) => !(v === undefined || v === null || v === "" || (Array.isArray(v) && v.length === 0));

export function groupFields<F extends { key: string; group?: unknown }>(fields: F[], values: Record<string, unknown> = {}, errors: Record<string, string> = {}): Segment<F>[] {
  const out: Segment<F>[] = [];
  for (const field of fields) {
    const group = typeof field.group === "string" && field.group.trim() ? field.group.trim() : null;
    const home = group === null ? undefined : out.find((s) => s.group === group);
    if (home) home.fields.push(field);
    else out.push({ group, fields: [field], open: false, filled: 0 });
  }
  for (const seg of out) {
    seg.filled = seg.fields.filter((f) => isFilled(values[f.key])).length;
    seg.open = seg.fields.some((f) => !!errors[f.key]);
  }
  return out;
}
