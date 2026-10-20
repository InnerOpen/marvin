// Internal entry types (backend: services/entry_listing.py): helper content a feature owns, like the Social auto-reply rules or an
// Audience form's submissions, edited from that feature's own pages. They aren't offered where a person picks a type to write (the
// New menu, Quick Create, the type filter), and their entries stay out of every list but the Trash (so a trashed Social rule can be
// restored). A type is internal only when `capabilities.listed` is false: one flag, shown as "Show in content lists" on the entry
// type editor and as an "Internal" badge on the Content model list. Pure, so `npm test` covers it (entryTypeListing.test.mjs).

export interface TypeLike {
  slug?: string | null;
  capabilitiesJson?: Record<string, unknown> | null;
}

function submissionOf(type: TypeLike | null | undefined): Record<string, unknown> | null {
  const caps = type?.capabilitiesJson;
  if (caps?.submittable !== true) return null;
  const submission = caps.submission;
  return submission && typeof submission === "object" && !Array.isArray(submission) ? (submission as Record<string, unknown>) : {};
}

/** Where a form's submissions go: "audience" (the default, even when nothing is stored) or "entries"; null for a type that isn't a form. */
export function submissionDestination(type: TypeLike | null | undefined): "audience" | "entries" | null {
  const submission = submissionOf(type);
  return submission === null ? null : submission.destination === "entries" ? "entries" : "audience";
}

/** What a form's submissions are: "message" (the default) or "signup"; null for a type that isn't a form. */
export function submissionKind(type: TypeLike | null | undefined): "message" | "signup" | null {
  const submission = submissionOf(type);
  return submission === null ? null : submission.kind === "signup" ? "signup" : "message";
}

export function isListedType(type: TypeLike | null | undefined): boolean {
  if (!type) return true;
  return type.capabilitiesJson?.listed !== false;
}

/** The types to offer a person who is about to write something. */
export function listedTypes<T extends TypeLike>(types: T[] | null | undefined): T[] {
  return (types ?? []).filter(isListedType);
}

/** What uses the type, for the hint on the editor and the badge's tooltip: Social's rule type, or a form that sends to the Audience.
 *  A hint only (the slug is read for the Social type); whether the type is internal is the flag, not this. Null when nothing is known. */
export function usedBy(type: TypeLike | null | undefined): string | null {
  const slug = type?.slug ?? "";
  if (slug === "social-auto-reply") return "Audience › Social › Rules";
  if (slug === "social-reply-log") return "nothing now (a retired Social type)";
  if (submissionDestination(type) === "audience") return submissionKind(type) === "signup" ? "Audience › Subscribers" : "Audience › Submissions";
  return null;
}

/** The "Internal" badge's tooltip: why the type is not listed, with what uses it. Null for a listed type. */
export function internalReason(type: TypeLike | null | undefined): string | null {
  if (isListedType(type)) return null;
  const by = usedBy(type);
  return `Its entries are kept out of All entries, the status lists, counts, search and the AI index${by ? `. Used by ${by}` : ""}.`;
}
