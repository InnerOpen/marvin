/**
 * What a wizard page does with entries and assets, on the server. Every call goes through the ordinary entries and assets APIs, so who may
 * read, create or change what is decided there, not here.
 */

import { createEntry, updateEntry } from "./api/entries";
import { fetchApi } from "./api/client";
import { listApprovals } from "./api/workflowApprovals";
import { type SelectionCondition, type WorkflowSelection, getSelection, getWorkflowState, startRun } from "./api/workflowRuns";
import { listEntryTypes, type EntryTypeRead } from "./api/entryTypes";
import { coerceDataJsonValue, fieldTypeMap } from "./schemaFields";
import { createSdkClient } from "./sdk";
import { inOrder } from "./runList";
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

/** Move an entry to the Trash (restorable from there). */
export async function trashEntry(id: string, authToken: string): Promise<void> {
  await fetchApi(`/api/platform/entries/${encodeURIComponent(id)}`, { method: "DELETE" }, authToken);
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

/** An asset of this workspace by its id, as far as a file box needs to know it; null when it is not there. */
export async function assetById(id: string, authToken: string): Promise<{ id: string; name?: string | null; mimeType?: string | null; publicUrl?: string | null } | null> {
  return createSdkClient(authToken).assets.get(id).catch(() => null);
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

/** The workspace's workflow of this slug: whether it is there and on, and whether the signed-in person may run it. */
export interface WorkflowState {
  found: boolean;
  enabled: boolean;
  /** The signed-in person may run it now (an admin, and it is on). */
  canRun: boolean;
  /** It is there and on, and the signed-in person may not run it (an editor: that is an admin's right today). */
  forbidden?: boolean;
  id?: string;
  name?: string;
}

export async function workflowState(slug: string, authToken: string): Promise<WorkflowState> {
  try {
    const state = await getWorkflowState(slug, authToken);
    if (!state.found) return { found: false, enabled: false, canRun: false };
    return { found: true, enabled: state.enabled, canRun: state.canRun, forbidden: state.enabled && !state.canRun, id: state.id ?? undefined, name: state.name ?? undefined };
  } catch (e) {
    // Below editor: not theirs to know which workflows there are.
    return { found: false, enabled: false, canRun: false, forbidden: /403|forbidden/i.test(e instanceof Error ? e.message : String(e)) };
  }
}

/** The entry a context key names, checked to be of the type the wizard says it is; null when it is not there or is something else. */
export async function entryOfType(typeSlug: string | undefined, slug: string | undefined, authToken: string): Promise<Row | null> {
  if (!slug || !typeSlug) return null;
  return (await findEntries({ entry_type: typeSlug, entries: [slug] }, authToken, 1)).entries[0] ?? null;
}

/** Start a workflow now and don't wait for it: the id of the run it started, to follow (null when the server could not name one). A
 *  workflow that is off is never switched on from here: it runs with its author's permissions. */
export async function runWorkflow(slug: string, inputs: Record<string, unknown>, authToken: string): Promise<string | null> {
  const state = await workflowState(slug, authToken);
  if (state.forbidden) throw new Error("Only a workspace admin can start a workflow today; ask one to run this step.");
  if (!state.found) throw new Error(`This workspace has no workflow “${slug}”. Install the package that brings it.`);
  if (!state.enabled) throw new Error(`“${state.name}” is switched off. Turn it on under Automation → Workflows, then run this step again.`);
  return startRun(state.id!, inputs, authToken);
}

export const MAX_DECIDED_SHOWN = 4;

/** The approvals a wizard step may show: the ones its workflow has waiting, and its latest decided. The server narrows the list to the
 *  workflow, so a step finds its cards however many others wait. Empty for someone below editor (they can't decide). */
export async function approvalCards(workflow: string, authToken: string): Promise<{ pending: ApprovalCard[]; decided: ApprovalCard[] }> {
  const get = (state: "pending" | "decided") => listApprovals(authToken, state, { automation: workflow }).catch(() => [] as ApprovalCard[]);
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

/** What a run step's workflow would act on if it ran now (its first step's `collect`, run by the server with these inputs), with the
 *  entries themselves read through the entries API in the workflow's order; null when it does not start by gathering entries, or the
 *  server could not say (the step then shows its button as before). */
export async function runSelection(
  workflow: string,
  inputs: Record<string, unknown>,
  leftOut: SelectionCondition[][],
  authToken: string,
): Promise<{ selection: WorkflowSelection; rows: Row[] } | null> {
  const selection = await getSelection(workflow, inputs, leftOut, authToken).catch(() => null);
  if (!selection?.found) return null;
  const rows = selection.ids.length ? (await findEntries({ entries: selection.ids }, authToken, selection.ids.length)).entries : [];
  return { selection, rows: inOrder(rows, selection.ids) };
}
