// The entry type's one single-asset field (a speech line's `audio`, a post's `hero`), so any asset attached to an entry can be made the
// one that field uses ("Use as Audio"). Nothing here knows what the assets are for: a type that keeps several recordings or pictures
// attached gets the choice, and which role each carries stays the workspace's own business.

export interface AssetFieldRef {
  key: string;
  label: string;
}

export function assetFieldOf(schema: { fields?: { key?: string; label?: string; type?: string }[] } | null | undefined): AssetFieldRef | null {
  const field = schema?.fields?.find((f) => f.type === "asset" && f.key);
  return field?.key ? { key: field.key, label: field.label || field.key } : null;
}

/** The attached assets that are not already the field's value, and are worth offering: only when there is a choice (two or more attached). */
export function offerableAssets<T extends { id: string }>(attached: readonly T[], currentId: string | null | undefined): T[] {
  return attached.length > 1 ? attached.filter((a) => a.id !== currentId) : [];
}
