/**
 * Helpers for coercing CMS form values to their declared entry-type schema types.
 *
 * `FormData` values are always strings, so a `number` schema field (e.g. an entry's "order")
 * would otherwise be saved as a string — which the content validator rejects — or as `null`
 * for a blank input, so the value silently never persists. Coerce each value to its declared
 * type before building `data_json`.
 */

export type SchemaField = { key: string; type: string };

/** Build a `fieldKey → declared type` map from an entry type's `schema_json`. */
export function fieldTypeMap(schemaJson: unknown): Record<string, string> {
  const fields = (schemaJson as { fields?: SchemaField[] } | null)?.fields ?? [];
  return Object.fromEntries(fields.map((f) => [f.key, f.type]));
}

/** Coerce a raw form value (always a string) to its declared schema field type. */
export function coerceDataJsonValue(fieldType: string | undefined, value: string): unknown {
  if (fieldType === "boolean") return value === "true";
  if (value === "") return null;
  if (fieldType === "number") {
    const parsed = Number(value);
    return Number.isNaN(parsed) ? null : parsed;
  }
  // Back-compat: a checkbox with no declared type still posts 'true'/'false'.
  if (value === "true" || value === "false") return value === "true";
  return value;
}
