/** The pick-list options of a schema's ref fields (lib/refFields.ts), from the entries API, on the server. */

import { fetchApi } from "./api/client";
import { listEntryTypes } from "./api/entryTypes";
import { type RefOption, tiered, refFieldsOf, refOptions, refScope, type RefVia } from "./refFields";

const MAX_OPTIONS = 500;

async function entriesOf(entryType: string, fields: Record<string, string>, authToken: string, listenRole?: string | null, matchKeys: string[] = []): Promise<RefOption[]> {
  const spec = Object.keys(fields).length ? { entry_type: entryType, fields } : { entry_type: entryType };
  const found = await fetchApi<{ entries?: { slug?: string; title?: string; dataJson?: Record<string, unknown>; assets?: { role?: string; publicUrl?: string; mimeType?: string }[] }[] }>(
    "/api/platform/entries/query",
    { method: "POST", body: JSON.stringify({ spec, limit: MAX_OPTIONS }) },
    authToken,
  ).catch(() => ({ entries: [] }));
  return refOptions(found.entries ?? [], listenRole, matchKeys);
}

/** What a field's `ref_via` prefers for this entry: the values of `via.field` on the entries whose fields match this entry's. */
async function viaValues(via: RefVia, data: Record<string, unknown>, authToken: string): Promise<string[]> {
  const fields: Record<string, string> = {};
  for (const [theirs, mine] of Object.entries(via.match)) {
    const value = data[mine];
    if (typeof value !== "string" || !value.trim()) return []; // nothing to match on yet (a story not chosen): no preference
    fields[theirs] = value.trim();
  }
  const found = await fetchApi<{ entries?: { dataJson?: Record<string, unknown> }[] }>(
    "/api/platform/entries/query",
    { method: "POST", body: JSON.stringify({ spec: { entry_type: via.entry_type, fields }, limit: MAX_OPTIONS }) },
    authToken,
  ).catch(() => ({ entries: [] }));
  return [...new Set((found.entries ?? []).map((e) => e.dataJson?.[via.field]).filter((v): v is string => typeof v === "string" && v !== ""))];
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
  /** The entry's own data: a field with `ref_via` lists first what this entry's neighbours name (the voices cast in its story). */
  data?: Record<string, unknown> | null,
): Promise<Record<string, RefOption[]>> {
  const fields = refFieldsOf(schema);
  if (!fields.length || !authToken) return {};
  const types = ctx && Object.keys(ctx).length ? await listEntryTypes(authToken).catch(() => []) : [];
  // One query per referenced type with its narrowing (a wizard's choices so far, the field's own filter) and whether to carry a recording.
  const asked = new Map<string, Promise<RefOption[]>>();
  const optionsOf = (f: (typeof fields)[number]) => {
    const typeSchema = types.find((t) => t.slug === f.ref)?.schemaJson as { fields?: any[] } | null | undefined;
    const narrow = { ...(ctx ? refScope(typeSchema, ctx) : {}), ...f.filter };
    const keys = Object.keys(f.match);
    const id = `${f.ref}|${JSON.stringify(narrow)}|${f.listen ?? ""}|${keys.join(",")}`;
    if (!asked.has(id)) asked.set(id, entriesOf(f.ref, narrow, authToken, f.listen, keys));
    return asked.get(id)!;
  };
  return Object.fromEntries(
    await Promise.all(
      fields.map(async (f) => {
        const all = await optionsOf(f);
        if (!f.vias.length || !data) return [f.key, all] as const;
        const tiers = await Promise.all(
          f.vias.map(async (via) => ({ label: via.label ?? `Cast in this ${Object.keys(via.match).length ? via.match[Object.keys(via.match)[0]] : "story"}`, slugs: await viaValues(via, data, authToken) })),
        );
        return [f.key, tiered(all, tiers, `Other ${f.ref}s`)] as const;
      }),
    ),
  );
}
