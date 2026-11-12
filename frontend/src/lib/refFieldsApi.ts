/** The pick-list options of a schema's ref fields (lib/refFields.ts), from the entries API, on the server. */

import { fetchApi } from "./api/client";
import { listEntryTypes } from "./api/entryTypes";
import { type RefOption, tiered, refFieldsOf, refOptions, refScopeSplit, type RefVia } from "./refFields";

const MAX_OPTIONS = 500;

type Found = { id?: string; slug?: string; title?: string; dataJson?: Record<string, unknown>; assets?: { role?: string; publicUrl?: string; mimeType?: string }[] };

/**
 * The entries of a type, narrowed by `fields`; `open` are fields the type may leave empty (a sound's story): the entries that hold that value, and the
 * ones with it empty, so what everyone shares is still offered.
 */
async function entriesOf(entryType: string, fields: Record<string, string>, authToken: string, listenRole?: string | null, matchKeys: string[] = [], open: Record<string, string> = {}): Promise<RefOption[]> {
  const ask = async (spec: Record<string, unknown>) =>
    (await fetchApi<{ entries?: Found[] }>("/api/platform/entries/query", { method: "POST", body: JSON.stringify({ spec, limit: MAX_OPTIONS }) }, authToken).catch(() => ({ entries: [] as Found[] }))).entries ?? [];
  const base = (extra: Record<string, unknown>) => ({ entry_type: entryType, ...(Object.keys(fields).length ? { fields } : {}), ...extra });
  const keys = Object.keys(open);
  const found = keys.length
    ? [...(await ask(base({ fields: { ...fields, ...open } }))), ...(await ask(base({ where: keys.map((field) => ({ field, op: "missing" })) })))]
    : await ask(base({}));
  const seen = new Set<string>();
  return refOptions(found.filter((e) => (e.slug && !seen.has(e.slug) ? (seen.add(e.slug), true) : false)), listenRole, matchKeys);
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
    const { fixed, open } = ctx ? refScopeSplit(typeSchema, ctx) : { fixed: {}, open: {} };
    const narrow = { ...fixed, ...f.filter };
    const keys = Object.keys(f.match);
    const id = `${f.ref}|${JSON.stringify(narrow)}|${JSON.stringify(open)}|${f.listen ?? ""}|${keys.join(",")}`;
    if (!asked.has(id)) asked.set(id, entriesOf(f.ref, narrow, authToken, f.listen, keys, open));
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
