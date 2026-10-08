/**
 * Files attached to an agent question — the bubble's 📎 chips and the Ask page's.
 *
 * A file is uploaded as an asset, then its id rides every agent run of the conversation as `attachments`
 * (separate from the page context) until it is removed or the conversation is cleared. The bubble keeps
 * the list per agent in session storage, next to that agent's thread (@/lib/marvin/pending).
 *
 * Kept free of the DOM and of runtime imports so it runs under `node --test` (attachments.test.mjs).
 */

/** The server refuses more (AIAgentRequest.attachments). */
export const MAX_ATTACHMENTS = 4;

/** What the file picker offers: images, and the documents `read_attachment` can read. */
export const ATTACH_ACCEPT =
  "image/*,application/pdf,.pdf,.docx,.txt,.md,.markdown,.csv,.tsv,.json,.yaml,.yml,.xml,text/*";

/** Session-storage key (scope it per workspace) holding agent slug → attachments. */
export const ATTACHMENTS_KEY = "marvin.attachments";

export interface Attachment {
  id: string;
  name: string;
  mimeType: string;
  /** Already named on a user turn of the transcript, so later turns don't list it again. */
  sent?: boolean;
}

type KV = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function isAttachment(value: unknown): value is Attachment {
  const a = value as Attachment | null;
  return !!a && typeof a.id === "string" && typeof a.name === "string" && typeof a.mimeType === "string";
}

function readAll(store: KV, key: string): Record<string, Attachment[]> {
  try {
    const raw = JSON.parse(store.getItem(key) || "{}");
    return raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
  } catch {
    return {};
  }
}

/** The attachments of `agent`'s conversation. */
export function loadAttachments(store: KV, key: string, agent: string): Attachment[] {
  const list = readAll(store, key)[agent];
  return Array.isArray(list) ? list.filter(isAttachment).slice(0, MAX_ATTACHMENTS) : [];
}

export function saveAttachments(store: KV, key: string, agent: string, list: Attachment[]): void {
  const all = readAll(store, key);
  if (list.length) all[agent] = list;
  else delete all[agent];
  try {
    if (Object.keys(all).length) store.setItem(key, JSON.stringify(all));
    else store.removeItem(key);
  } catch {
    /* quota or disabled storage — the chips last this page */
  }
}

/** Every agent's attachments gone: the conversation was cleared. */
export function forgetAttachments(store: KV, key: string): void {
  try {
    store.removeItem(key);
  } catch {
    /* nothing stored */
  }
}

/** Room for how many more files. */
export function roomFor(list: Attachment[]): number {
  return Math.max(0, MAX_ATTACHMENTS - list.length);
}

/** `list` with `item` added at the end (a file already attached keeps its place); never past the cap. */
export function withAttachment(list: Attachment[], item: Attachment): Attachment[] {
  if (list.some((a) => a.id === item.id)) return list;
  return list.length >= MAX_ATTACHMENTS ? list : [...list, item];
}

export function withoutAttachment(list: Attachment[], id: string): Attachment[] {
  return list.filter((a) => a.id !== id);
}

/** The ids to send with a run. */
export function attachmentIds(list: Attachment[]): string[] {
  return list.map((a) => a.id);
}

/** A chip's icon. */
export function attachmentIcon(mimeType: string): string {
  return mimeType.startsWith("image/") ? "🖼" : "📄";
}

/** The attachments stored on a thread's user turn (`metaJson.attachments`), or none. */
export function turnAttachments(meta: unknown): Attachment[] {
  const list = (meta as { attachments?: unknown } | null | undefined)?.attachments;
  return Array.isArray(list) ? list.filter(isAttachment) : [];
}
