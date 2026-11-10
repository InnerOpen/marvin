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
  /** A recording to hear before choosing it (the field's `ref_listen`: the asset role to play), when the entry has one. */
  audio?: string;
}

/**
 * `ref_via` on a ref field: prefer the entries that other entries name. "The `voice` of the `cast-member`s whose `story` is this entry's
 * `story`" is `{entry_type: "cast-member", field: "voice", match: {story: "story"}}` (match: the other type's field → this entry's field).
 */
export interface RefVia {
  entry_type: string;
  field: string;
  match: Record<string, string>;
  /** The heading its entries are listed under (default "Cast in this <the first matched field>"). */
  label?: string;
}

interface FieldLike {
  key?: string;
  type?: string;
  ref?: unknown;
  ref_via?: unknown;
  ref_filter?: unknown;
  ref_listen?: unknown;
}

type SchemaLike = { fields?: FieldLike[] | null } | null | undefined;

const fieldsOf = (schema: SchemaLike): FieldLike[] => (Array.isArray(schema?.fields) ? schema!.fields! : []);

/** The entry type a field refers to: only a text field's non-empty `ref` counts. */
export function refOf(field: FieldLike): string | null {
  return field.type === "text" && typeof field.ref === "string" && field.ref.trim() ? field.ref.trim() : null;
}

/** One `ref_via`, when it is well formed (an entry type, a field, and at least one match). */
function oneVia(v: unknown): RefVia | null {
  const x = v as Partial<RefVia> | null | undefined;
  if (!x || typeof x.entry_type !== "string" || typeof x.field !== "string" || !x.match || typeof x.match !== "object") return null;
  const match = Object.fromEntries(Object.entries(x.match).filter(([k, m]) => k && typeof m === "string" && m));
  if (!Object.keys(match).length) return null;
  return { entry_type: x.entry_type, field: x.field, match, ...(typeof x.label === "string" && x.label.trim() ? { label: x.label.trim() } : {}) };
}

/** A field's `ref_via`: one, or a list of tiers (the speaker's own voice, then the story's cast); the well formed ones, in order. */
export function refViasOf(field: FieldLike): RefVia[] {
  const raw = Array.isArray(field.ref_via) ? field.ref_via : field.ref_via ? [field.ref_via] : [];
  return raw.flatMap((v) => oneVia(v) ?? []);
}

/** The fields of a schema that refer to another type, each with that type's slug (and its `ref_via` tiers, when it has any). */
export function refFieldsOf(schema: SchemaLike): { key: string; ref: string; vias: RefVia[]; filter: Record<string, string>; listen: string | null }[] {
  return fieldsOf(schema).flatMap((f) => {
    const ref = refOf(f);
    return ref && f.key ? [{ key: f.key, ref, vias: refViasOf(f), filter: refFilterOf(f), listen: refListenOf(f) }] : [];
  });
}

/** `ref_filter` on a ref field: only the entries whose fields hold these values are offered (a music field offers sounds of kind music). */
export function refFilterOf(field: FieldLike): Record<string, string> {
  const raw = field.ref_filter;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  return Object.fromEntries(Object.entries(raw).filter(([k, v]) => k && typeof v === "string" && v));
}

/** `ref_listen` on a ref field: the role of the asset to play beside the pick list, so a sound can be heard before it is chosen. */
export function refListenOf(field: FieldLike): string | null {
  return typeof field.ref_listen === "string" && field.ref_listen.trim() ? field.ref_listen.trim() : null;
}

/**
 * The options split into tiers, each under its own heading in order, and the rest under the last: an option goes under the first tier that
 * names it. With nothing named (nobody cast yet) the list is left as it was.
 */
export function tiered(options: RefOption[], tiers: { label: string; slugs: Iterable<string> }[], rest: string): RefOption[] {
  const sets = tiers.map((t) => ({ label: t.label, slugs: new Set(t.slugs) }));
  const home = (o: RefOption) => sets.find((t) => t.slugs.has(o.slug))?.label;
  if (!options.some((o) => home(o))) return options;
  const groups = [...sets.map((t) => t.label), rest];
  return groups.flatMap((label) => options.filter((o) => (home(o) ?? rest) === label).map((o) => ({ ...o, group: label })));
}

/** The distinct entry types a schema's text fields refer to. */
export function refTypesOf(schema: SchemaLike): string[] {
  return [...new Set(refFieldsOf(schema).map((f) => f.ref))];
}

/** Entries as pick-list options, by title (ignoring case); an entry without a slug cannot be referred to, so it is left out. */
export function refOptions(
  entries: { slug?: string | null; title?: string | null; assets?: { role?: string | null; publicUrl?: string | null; mimeType?: string | null }[] | null }[],
  listenRole?: string | null,
): RefOption[] {
  return entries
    .filter((e): e is typeof e & { slug: string } => typeof e.slug === "string" && e.slug !== "")
    .map((e) => {
      const heard = listenRole ? e.assets?.find((a) => a.role === listenRole && a.publicUrl && (a.mimeType ?? "").startsWith("audio/")) : undefined;
      return { slug: e.slug, title: e.title?.trim() || e.slug, ...(heard?.publicUrl ? { audio: heard.publicUrl } : {}) };
    })
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
