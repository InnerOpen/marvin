/**
 * What a wizard page does with entries and assets, on the server. Every call goes through the ordinary entries and assets APIs, so who may
 * read, create or change what is decided there, not here.
 */

import { createEntry, updateEntry } from "./api/entries";
import { fetchApi } from "./api/client";
import { listEntryTypes, type EntryTypeRead } from "./api/entryTypes";
import { coerceDataJsonValue, fieldTypeMap } from "./schemaFields";
import { createSdkClient } from "./sdk";
import type { ApprovalCard } from "./wizard";

export interface Row {
  id: string;
  slug: string;
  title: string;
  dataJson?: Record<string, any> | null;
  assets?: { role?: string | null; publicUrl?: string | null; mimeType?: string | null; name?: string | null }[];
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
export async function uploadAsset(file: File, nameHint: string, authToken: string, displayName?: string): Promise<string> {
  const slug = `${nameHint}-${Date.now().toString(36)}`.toLowerCase().replace(/[^a-z0-9-]+/g, "-").slice(0, 80);
  const asset = await createSdkClient(authToken).assets.upload(file, { slug, name: displayName || file.name || slug });
  return String((asset as { id: string }).id);
}

export function describeFailure(e: unknown): string {
  return e instanceof Error && e.message ? e.message.slice(0, 300) : "Something went wrong.";
}

const AUTO_SLUG_FIELD = "slug";

/** Keys of the fields an entry of this type must have: a wizard's own list of fields can't leave one out and still save. */
export function requiredKeys(type: EntryTypeRead | null): string[] {
  const fields = ((type?.schemaJson as { fields?: { key: string; required?: boolean }[] } | null)?.fields ?? []) as { key: string; required?: boolean }[];
  return fields.filter((f) => f.required).map((f) => f.key);
}

/** The required fields of an entry type with their labels, for saying what is missing. */
export function requiredFields(type: EntryTypeRead | null): { key: string; label: string }[] {
  const fields = ((type?.schemaJson as { fields?: { key: string; label?: string; required?: boolean }[] } | null)?.fields ?? []) as { key: string; label?: string; required?: boolean }[];
  return fields.filter((f) => f.required && f.key !== AUTO_SLUG_FIELD).map((f) => ({ key: f.key, label: f.label ?? f.key }));
}

/** The fields a step asks for: the ones it names, then any the type requires (a required `slug` field is filled from the name, so it is not asked). */
export function askedKeys(type: EntryTypeRead | null, named: string[] | undefined, supplied: string[] = []): string[] {
  return [...new Set([...(named ?? []), ...requiredKeys(type)])].filter((k) => k !== AUTO_SLUG_FIELD && !supplied.includes(k));
}

/** A required `slug` field left unset takes the name, lowercased with dashes. */
export function withAutoSlug(type: EntryTypeRead | null, data: Record<string, unknown>, title: string): Record<string, unknown> {
  if (!requiredKeys(type).includes(AUTO_SLUG_FIELD) || data[AUTO_SLUG_FIELD]) return data;
  return { ...data, [AUTO_SLUG_FIELD]: title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80) };
}

interface WorkflowRow {
  id: string;
  slug: string;
  name: string;
  description?: string | null;
  enabled: boolean;
}

/** The workspace's workflow of this slug: whether it is there and on. */
export interface WorkflowState {
  found: boolean;
  enabled: boolean;
  /** The signed-in person may not list or run workflows (an editor: that is an admin's right today). */
  forbidden?: boolean;
  id?: string;
  name?: string;
  description?: string;
}

export async function workflowState(slug: string, authToken: string): Promise<WorkflowState> {
  let rows: WorkflowRow[] | { items?: WorkflowRow[] };
  try {
    rows = await fetchApi<WorkflowRow[] | { items?: WorkflowRow[] }>("/api/automations", {}, authToken);
  } catch (e) {
    return { found: false, enabled: false, forbidden: /403|forbidden/i.test(e instanceof Error ? e.message : String(e)) };
  }
  const found = (Array.isArray(rows) ? rows : (rows.items ?? [])).find((w) => w.slug === slug);
  return found ? { found: true, enabled: !!found.enabled, id: found.id, name: found.name, description: found.description } : { found: false, enabled: false };
}

/** The entry a context key names, checked to be of the type the wizard says it is; null when it is not there or is something else. */
export async function entryOfType(typeSlug: string | undefined, slug: string | undefined, authToken: string): Promise<Row | null> {
  if (!slug || !typeSlug) return null;
  return (await findEntries({ entry_type: typeSlug, entries: [slug] }, authToken, 1)).entries[0] ?? null;
}

/** Start a workflow now and don't wait for it. A workflow that is off is never switched on from here: it runs with its author's permissions. */
export async function runWorkflow(slug: string, inputs: Record<string, unknown>, authToken: string): Promise<string> {
  const state = await workflowState(slug, authToken);
  if (state.forbidden) throw new Error("Only a workspace admin can start a workflow today; ask one to run this step.");
  if (!state.found) throw new Error(`This workspace has no workflow “${slug}”. Install the package that brings it.`);
  if (!state.enabled) throw new Error(`“${state.name}” is switched off. Turn it on under Automation → Workflows, then run this step again.`);
  await fetchApi(`/api/automations/${encodeURIComponent(state.id!)}/run?background=true`, { method: "POST", body: JSON.stringify({ inputs }) }, authToken);
  return state.name ?? slug;
}

export const MAX_DECIDED_SHOWN = 4;

/** The approvals a wizard step may show: the ones waiting, and the latest decided. Empty for someone below editor (they can't decide). */
export async function approvalCards(authToken: string): Promise<{ pending: ApprovalCard[]; decided: ApprovalCard[] }> {
  const get = (state: string) => fetchApi<ApprovalCard[]>(`/api/automations/approvals?state=${state}`, {}, authToken).catch(() => [] as ApprovalCard[]);
  const [pending, decided] = await Promise.all([get("pending"), get("decided")]);
  return { pending, decided };
}

/** Decide a waiting approval as the signed-in person (the server checks their role against the step's). */
export async function decideApproval(id: string, decision: "approve" | "deny", choice: string | null, note: string | null, authToken: string): Promise<void> {
  const body: Record<string, unknown> = { decision };
  if (choice) body.choice = choice;
  if (note) body.note = note;
  await fetchApi(`/api/automations/approvals/${encodeURIComponent(id)}/decide`, { method: "POST", body: JSON.stringify(body) }, authToken);
}
