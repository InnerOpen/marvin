/** The pick-list options of a schema's ref fields (lib/refFields.ts), from the entries API, on the server. */

import { fetchApi } from "./api/client";
import { listEntryTypes } from "./api/entryTypes";
import { type RefOption, refFieldsOf, refOptions, refScope, refTypesOf } from "./refFields";

const MAX_OPTIONS = 500;

async function entriesOf(entryType: string, fields: Record<string, string>, authToken: string): Promise<RefOption[]> {
  const spec = Object.keys(fields).length ? { entry_type: entryType, fields } : { entry_type: entryType };
  const found = await fetchApi<{ entries?: { slug?: string; title?: string }[] }>(
    "/api/platform/entries/query",
    { method: "POST", body: JSON.stringify({ spec, limit: MAX_OPTIONS }) },
    authToken,
  ).catch(() => ({ entries: [] }));
  return refOptions(found.entries ?? []);
}

/**
 * The options of each ref field of the schema, by field key: one query per referenced type, an empty list when it fails (the field then
 * offers only its current value). `ctx` (a wizard's entry choices so far) narrows each type by the fields it shares with them; without it
 * the whole workspace's entries are offered.
 */
export async function refOptionsFor(
  schema: { fields?: any[] | null } | null | undefined,
  authToken: string | null | undefined,
  ctx?: Record<string, string>,
): Promise<Record<string, RefOption[]>> {
  const fields = refFieldsOf(schema);
  if (!fields.length || !authToken) return {};
  const types = ctx && Object.keys(ctx).length ? await listEntryTypes(authToken).catch(() => []) : [];
  const byType = Object.fromEntries(
    await Promise.all(
      refTypesOf(schema).map(async (slug) => {
        const typeSchema = types.find((t) => t.slug === slug)?.schemaJson as { fields?: any[] } | null | undefined;
        return [slug, await entriesOf(slug, ctx ? refScope(typeSchema, ctx) : {}, authToken)] as const;
      }),
    ),
  );
  return Object.fromEntries(fields.map((f) => [f.key, byType[f.ref] ?? []]));
}
