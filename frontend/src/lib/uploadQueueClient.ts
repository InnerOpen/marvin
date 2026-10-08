/**
 * The upload queue (lib/uploadQueue.ts) in the browser: files in Cache Storage `marvin-uploads` (the service
 * worker keeps that cache across updates, src/pwa/sw-logic.js), sent through the SDK's normal asset upload.
 * Logging out drops it with every other marvin-* cache, after asking (lib/pwaClient.ts).
 */

import { fetchApi } from "@/lib/api/client";
import { createSdkClient } from "@/lib/sdk";
import {
  discard,
  enqueue,
  type QueuedUpload,
  type QueueStore,
  type ReplayResult,
  replay,
  type UploadFields,
} from "@/lib/uploadQueue";

/** Same name as UPLOAD_CACHE in src/pwa/sw-logic.js (plain JS for the worker). */
const CACHE = "marvin-uploads";
const INDEX = "/__uploads/index.json";
const fileKey = (id: string) => `/__uploads/file/${encodeURIComponent(id)}`;

/** Fired on document when the queue changes (a file queued, sent or discarded). */
export const QUEUE_EVENT = "marvin:upload-queue";

function available(): boolean {
  return typeof caches !== "undefined";
}

export function cacheStore(): QueueStore {
  return {
    async readIndex() {
      const hit = await (await caches.open(CACHE)).match(INDEX);
      try {
        const list = hit ? await hit.json() : [];
        return Array.isArray(list) ? list : [];
      } catch {
        return [];
      }
    },
    async writeIndex(list) {
      const cache = await caches.open(CACHE);
      if (list.length)
        await cache.put(INDEX, new Response(JSON.stringify(list), { headers: { "Content-Type": "application/json" } }));
      else await caches.delete(CACHE);
    },
    async putFile(id, file) {
      await (await caches.open(CACHE)).put(
        fileKey(id),
        new Response(file, { headers: { "Content-Type": file.type || "application/octet-stream" } }),
      );
    },
    async getFile(id) {
      const hit = await (await caches.open(CACHE)).match(fileKey(id));
      return hit ? await hit.blob() : null;
    },
    async deleteFile(id) {
      await (await caches.open(CACHE)).delete(fileKey(id));
    },
  };
}

function announce() {
  document.dispatchEvent(new CustomEvent(QUEUE_EVENT));
}

/** Keep `file` to upload into `workspace` later. False when it can't be kept (no Cache Storage, or the queue is full). */
export async function queueUpload(file: File, fields: UploadFields, workspace: string): Promise<boolean> {
  if (!available() || !workspace) return false;
  try {
    const item = await enqueue(
      cacheStore(),
      { workspace, fileName: file.name, type: file.type, size: file.size, fields },
      file,
      { id: crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`, now: Date.now() },
    );
    if (item) announce();
    return item !== null;
  } catch {
    return false; // quota, private mode
  }
}

export async function waitingUploads(): Promise<QueuedUpload[]> {
  if (!available()) return [];
  try {
    return await cacheStore().readIndex();
  } catch {
    return [];
  }
}

export async function discardUploads(): Promise<number> {
  if (!available()) return 0;
  const n = await discard(cacheStore());
  announce();
  return n;
}

async function currentWorkspace(): Promise<string | null> {
  try {
    return String((await fetchApi<{ id: string }>("/api/self/workspaces/current")).id);
  } catch {
    return null;
  }
}

let sending: Promise<ReplayResult | null> | null = null;

/** Send what waits for the active workspace. One run at a time; null when nothing waits or it can't run. */
export function sendWaitingUploads(): Promise<ReplayResult | null> {
  if (sending) return sending;
  sending = (async () => {
    if (!available() || !(await waitingUploads()).length) return null;
    const online = navigator.onLine;
    const workspace = online ? await currentWorkspace() : null;
    const sdk = createSdkClient();
    const result = await replay(cacheStore(), {
      workspace,
      online,
      upload: (item, blob) => sdk.assets.upload(new File([blob], item.fileName, { type: item.type }), item.fields),
    });
    announce();
    return result;
  })().finally(() => {
    sending = null;
  });
  return sending;
}
