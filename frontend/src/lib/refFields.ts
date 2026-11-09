/**
 * Ref fields: a text field that holds the slug of another entry (an actor's `voice`, a cast member's `actor`) says which entry type with
 * `ref: "<entry type slug>"`, and the forms offer that type's entries as a pick list instead of a box to type a slug into. The pure part;
 * refFieldsApi.ts asks the entries API.
 */

export interface RefOption {
  slug: string;
  title: string;
}

interface FieldLike {
  key?: string;
  type?: string;
  ref?: unknown;
}

type SchemaLike = { fields?: FieldLike[] | null } | null | undefined;

const fieldsOf = (schema: SchemaLike): FieldLike[] => (Array.isArray(schema?.fields) ? schema!.fields! : []);

/** The entry type a field refers to: only a text field's non-empty `ref` counts. */
export function refOf(field: FieldLike): string | null {
  return field.type === "text" && typeof field.ref === "string" && field.ref.trim() ? field.ref.trim() : null;
}

/** The fields of a schema that refer to another type, each with that type's slug. */
export function refFieldsOf(schema: SchemaLike): { key: string; ref: string }[] {
  return fieldsOf(schema).flatMap((f) => {
    const ref = refOf(f);
    return ref && f.key ? [{ key: f.key, ref }] : [];
  });
}

/** The distinct entry types a schema's text fields refer to. */
export function refTypesOf(schema: SchemaLike): string[] {
  return [...new Set(refFieldsOf(schema).map((f) => f.ref))];
}

/** Entries as pick-list options, by title (ignoring case); an entry without a slug cannot be referred to, so it is left out. */
export function refOptions(entries: { slug?: string | null; title?: string | null }[]): RefOption[] {
  return entries
    .filter((e): e is { slug: string; title?: string | null } => typeof e.slug === "string" && e.slug !== "")
    .map((e) => ({ slug: e.slug, title: e.title?.trim() || e.slug }))
    .sort((a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: "base" }));
}

/** The options plus the current value when it is set and not among them, so a stale or out-of-scope slug is shown, never dropped on save. */
export function withCurrent(options: RefOption[], value: unknown): RefOption[] {
  if (typeof value !== "string" || value === "" || options.some((o) => o.slug === value)) return options;
  return [...options, { slug: value, title: `${value} (not found)` }];
}

/**
 * In a wizard, what narrows a referenced type's entries: each choice so far whose name is also a field of that type (a cast member's
 * actor is one of the chosen world's troupe, so `world` narrows the actors). Shaped as an entries-query `fields` filter.
 */
export function refScope(typeSchema: SchemaLike, ctx: Record<string, string>): Record<string, string> {
  const keys = new Set(fieldsOf(typeSchema).map((f) => f.key));
  return Object.fromEntries(Object.entries(ctx).filter(([k, v]) => v && keys.has(k)));
}
