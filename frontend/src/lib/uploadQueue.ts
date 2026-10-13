/**
 * Uploads that wait for a connection.
 *
 * An asset upload (Assets → New, the Share page) that fails because the device is offline or the network dropped
 * is kept — the file and its fields, in Cache Storage (`marvin-uploads`, lib/uploadQueueClient.ts) — and sent when
 * the app is back online or next opened. Only into the workspace it was meant for: uploads go to the active
 * workspace, so one queued for another waits until that workspace is active again. An upload the server refused
 * (too big, a type it doesn't take, no permission, a slug taken) is not retried: that answer won't change.
 *
 * Kept free of the DOM and of runtime imports so it runs under `node --test` (uploadQueue.test.mjs); storage and
 * the upload itself are passed in.
 */

/** Waiting uploads at most; past that a new one is refused (and the page says so). */
export const MAX_QUEUED = 20;

/** Answers worth trying again later: the server or a proxy was briefly unavailable. */
const RETRY_STATUSES = new Set([408, 425, 429, 500, 502, 503, 504]);
const NETWORK_ERROR =
  /failed to fetch|networkerror|network error|load failed|network request failed|timed? ?out|aborted/i;

export interface UploadFields {
  slug: string;
  name: string;
  altText?: string;
  description?: string;
  metadata?: Record<string, unknown>;
}

export interface QueuedUpload {
  id: string;
  /** The workspace (group id) the upload was meant for. */
  workspace: string;
  fileName: string;
  type: string;
  size: number;
  fields: UploadFields;
  /** Epoch ms. */
  queuedAt: number;
}

export interface QueueStore {
  readIndex(): Promise<QueuedUpload[]>;
  writeIndex(list: QueuedUpload[]): Promise<void>;
  putFile(id: string, file: Blob): Promise<void>;
  getFile(id: string): Promise<Blob | null>;
  deleteFile(id: string): Promise<void>;
}

function statusOf(error: unknown): number | null {
  const e = error as { statusCode?: unknown; status?: unknown; response?: { status?: unknown } } | null;
  for (const value of [e?.statusCode, e?.status, e?.response?.status]) {
    if (typeof value === "number" && value > 0) return value;
  }
  return null;
}

/** Whether a failed upload should wait and try again (no connection, or a passing server error). */
export function isRetryable(error: unknown, online: boolean): boolean {
  if (!online) return true;
  const status = statusOf(error);
  if (status !== null) return RETRY_STATUSES.has(status);
  const message = (error as { message?: unknown } | null)?.message ?? error;
  return NETWORK_ERROR.test(String(message ?? ""));
}

/** Keep an upload for later. Null when the queue is full. */
export async function enqueue(
  store: QueueStore,
  upload: Omit<QueuedUpload, "id" | "queuedAt">,
  file: Blob,
  { id, now }: { id: string; now: number },
): Promise<QueuedUpload | null> {
  const list = await store.readIndex();
  if (list.length >= MAX_QUEUED) return null;
  const item: QueuedUpload = { ...upload, id, queuedAt: now };
  await store.putFile(id, file);
  await store.writeIndex([...list, item]);
  return item;
}

/** Drop one waiting upload, or all of them. */
export async function discard(store: QueueStore, id?: string): Promise<number> {
  const list = await store.readIndex();
  const gone = id ? list.filter((u) => u.id === id) : list;
  await Promise.all(gone.map((u) => store.deleteFile(u.id)));
  await store.writeIndex(list.filter((u) => !gone.includes(u)));
  return gone.length;
}

export interface ReplayResult {
  sent: QueuedUpload[];
  /** Refused for good (or its file is gone): dropped from the queue. */
  failed: { upload: QueuedUpload; error: string }[];
  /** Still waiting: no connection yet, a passing error, or meant for another workspace. */
  waiting: QueuedUpload[];
}

/** Send what waits for `workspace`, oldest first. */
export async function replay(
  store: QueueStore,
  {
    workspace,
    online,
    upload,
  }: { workspace: string | null; online: boolean; upload: (item: QueuedUpload, file: Blob) => Promise<unknown> },
): Promise<ReplayResult> {
  const list = await store.readIndex();
  const result: ReplayResult = { sent: [], failed: [], waiting: [] };
  for (const item of [...list].sort((a, b) => a.queuedAt - b.queuedAt)) {
    if (!online || !workspace || item.workspace !== workspace) {
      result.waiting.push(item);
      continue;
    }
    const file = await store.getFile(item.id);
    if (!file) {
      result.failed.push({ upload: item, error: "the file is no longer on this device" });
      continue;
    }
    try {
      await upload(item, file);
      result.sent.push(item);
    } catch (error) {
      if (isRetryable(error, online)) result.waiting.push(item);
      else result.failed.push({ upload: item, error: String((error as { message?: unknown })?.message ?? error) });
    }
  }
  const done = [...result.sent, ...result.failed.map((f) => f.upload)];
  await Promise.all(done.map((u) => store.deleteFile(u.id)));
  await store.writeIndex(list.filter((u) => !done.includes(u)));
  return result;
}

/** The waiting note's text, or null when nothing waits. */
export function queueNote(list: QueuedUpload[], workspace: string | null): string | null {
  if (!list.length) return null;
  const here = list.filter((u) => u.workspace === workspace).length;
  const elsewhere = list.length - here;
  const count = (n: number) => `${n} upload${n === 1 ? "" : "s"}`;
  const parts = [];
  if (here) parts.push(`${count(here)} waiting for a connection`);
  if (elsewhere) parts.push(`${count(elsewhere)} waiting for another workspace — switch to it to send`);
  return parts.join("; ");
}
