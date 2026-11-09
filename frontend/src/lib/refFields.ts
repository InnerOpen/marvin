/**
 * Ref fields: a text field that holds the slug of another entry (an actor's `voice`, a cast member's `actor`) says which entry type with
 * `ref: "<entry type slug>"`, and the forms offer that type's entries as a pick list instead of a box to type a slug into. The pure part;
 * refFieldsApi.ts asks the entries API.
 */

export interface RefOption {
  slug: string;
  title: string;
  /** A heading the option is listed under, when the list is split (the voices cast in this story, then the rest). */
  group?: string;
}

/**
 * `ref_via` on a ref field: prefer the entries that other entries name. "The `voice` of the `cast-member`s whose `story` is this entry's
 * `story`" is `{entry_type: "cast-member", field: "voice", match: {story: "story"}}` (match: the other type's field → this entry's field).
 */
export interface RefVia {
  entry_type: string;
  field: string;
  match: Record<string, string>;
}

interface FieldLike {
  key?: string;
  type?: string;
  ref?: unknown;
  ref_via?: unknown;
}

type SchemaLike = { fields?: FieldLike[] | null } | null | undefined;

const fieldsOf = (schema: SchemaLike): FieldLike[] => (Array.isArray(schema?.fields) ? schema!.fields! : []);

/** The entry type a field refers to: only a text field's non-empty `ref` counts. */
export function refOf(field: FieldLike): string | null {
  return field.type === "text" && typeof field.ref === "string" && field.ref.trim() ? field.ref.trim() : null;
}

/** A field's `ref_via`, when it is well formed (an entry type, a field, and at least one match). */
export function refViaOf(field: FieldLike): RefVia | null {
  const v = field.ref_via as Partial<RefVia> | null | undefined;
  if (!v || typeof v.entry_type !== "string" || typeof v.field !== "string" || !v.match || typeof v.match !== "object") return null;
  const match = Object.fromEntries(Object.entries(v.match).filter(([k, x]) => k && typeof x === "string" && x));
  return Object.keys(match).length ? { entry_type: v.entry_type, field: v.field, match } : null;
}

/** The fields of a schema that refer to another type, each with that type's slug (and its `ref_via`, when it has one). */
export function refFieldsOf(schema: SchemaLike): { key: string; ref: string; via: RefVia | null }[] {
  return fieldsOf(schema).flatMap((f) => {
    const ref = refOf(f);
    return ref && f.key ? [{ key: f.key, ref, via: refViaOf(f) }] : [];
  });
}

/**
 * The options with the preferred ones first under their own heading and the rest under another, so a form offers the story's own cast and
 * still lets someone pick outside it. With none preferred (nobody cast yet) the list is left as it was.
 */
export function preferred(options: RefOption[], slugs: Iterable<string>, first: string, rest: string): RefOption[] {
  const wanted = new Set(slugs);
  const chosen = options.filter((o) => wanted.has(o.slug));
  if (!chosen.length) return options;
  return [...chosen.map((o) => ({ ...o, group: first })), ...options.filter((o) => !wanted.has(o.slug)).map((o) => ({ ...o, group: rest }))];
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
