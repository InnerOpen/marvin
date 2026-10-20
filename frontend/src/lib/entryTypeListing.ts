// Internal entry types (backend: services/entry_listing.py): helper content a feature owns, like the Social auto-reply rules, edited
// from that feature's own pages. They aren't offered where a person picks a type to write (the New menu, Quick Create, the type
// filter), and their entries stay out of every list. A type is internal by `capabilities.listed: false`, and the backend's core rule
// also makes these slugs internal whatever their capabilities say. Pure, so `npm test` covers it (entryTypeListing.test.mjs).

export const INTERNAL_TYPE_SLUGS = ["social-auto-reply", "social-reply-log", "ig-auto-reply", "ig-reply-log"];

export interface TypeLike {
  slug?: string | null;
  capabilitiesJson?: Record<string, unknown> | null;
}

export function isListedType(type: TypeLike | null | undefined): boolean {
  if (!type) return true;
  return type.capabilitiesJson?.listed !== false && !INTERNAL_TYPE_SLUGS.includes(type.slug ?? "");
}

/** The types to offer a person who is about to write something. */
export function listedTypes<T extends TypeLike>(types: T[] | null | undefined): T[] {
  return (types ?? []).filter(isListedType);
}
