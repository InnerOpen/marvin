/**
 * What a wizard page does with entries and assets, on the server. Every call goes through the ordinary entries and assets APIs, so who may
 * read, create or change what is decided there, not here.
 */

import { createEntry, updateEntry } from "./api/entries";
import { fetchApi } from "./api/client";
import { listEntryTypes, type EntryTypeRead } from "./api/entryTypes";
import { coerceDataJsonValue, fieldTypeMap } from "./schemaFields";
import { createSdkClient } from "./sdk";

export interface Row {
  id: string;
  slug: string;
  title: string;
  dataJson?: Record<string, any> | null;
}

export const MAX_TEXT_UPLOAD_BYTES = 1_000_000;
const MAX_ROWS = 200;

export async function findEntries(spec: Record<string, unknown>, authToken: string, limit = MAX_ROWS): Promise<{ entries: Row[]; total: number }> {
  const found = await fetchApi<{ entries?: Row[]; total?: number }>(
    "/api/platform/entries/query",
    { method: "POST", body: JSON.stringify({ spec, limit }) },
    authToken,
  ).catch(() => ({ entries: [], total: 0 }));
  return { entries: found.entries ?? [], total: found.total ?? found.entries?.length ?? 0 };
}

export async function entryBySlug(slug: string | undefined, authToken: string): Promise<Row | null> {
  if (!slug) return null;
  return (await findEntries({ entries: [slug] }, authToken, 1)).entries[0] ?? null;
}

export async function typeBySlug(slug: string | undefined, authToken: string): Promise<EntryTypeRead | null> {
  return (await listEntryTypes(authToken)).find((t) => t.slug === slug) ?? null;
}

/** The posted `dataJson.<key>` values for the named keys, each coerced to its declared type (FormData is all strings). */
export function postedData(form: FormData, type: EntryTypeRead | null, keys: string[], prefix = "dataJson."): Record<string, unknown> {
  const types = fieldTypeMap(type?.schemaJson);
  const out: Record<string, unknown> = {};
  for (const key of keys) {
    const raw = form.get(`${prefix}${key}`);
    if (raw !== null) out[key] = coerceDataJsonValue(types[key], String(raw));
    else if (types[key] === "boolean") out[key] = false; // an unchecked box posts nothing
  }
  return out;
}

export async function createOf(type: EntryTypeRead, title: string, data: Record<string, unknown>, authToken: string): Promise<Row> {
  return (await createEntry({ entry_type_id: type.id, title, status: "draft", data_json: data } as any, authToken)) as unknown as Row;
}

/** Set some fields of an entry, keeping the rest (an update replaces the whole data). */
export async function setData(entry: Row, changes: Record<string, unknown>, authToken: string): Promise<void> {
  await updateEntry(entry.id, { data_json: { ...(entry.dataJson ?? {}), ...changes } } as any, authToken);
}

/** Store an uploaded file as an asset and say its id; the entry's asset field then holds it (the server attaches it). */
export async function uploadAsset(file: File, nameHint: string, authToken: string): Promise<string> {
  const slug = `${nameHint}-${Date.now().toString(36)}`.toLowerCase().replace(/[^a-z0-9-]+/g, "-").slice(0, 80);
  const asset = await createSdkClient(authToken).assets.upload(file, { slug, name: file.name || slug });
  return String((asset as { id: string }).id);
}

export function describeFailure(e: unknown): string {
  return e instanceof Error && e.message ? e.message.slice(0, 300) : "Something went wrong.";
}
