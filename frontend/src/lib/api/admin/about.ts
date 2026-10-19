/**
 * Admin About API - the embeddings status carried by GET /api/admin/about.
 *
 * The SDK's AdminAboutInfo predates the `embeddings` object, so this reads it directly.
 */

import { fetchApi } from "../client";

interface IndexedEmbeddingModel {
  modelId: string;
  chunks: number;
}

export interface EmbeddingsInfo {
  /** EMBEDDINGS_BUILTIN_ENABLED. */
  builtinEnabled: boolean;
  /** Enabled and fastembed installed: the built-in model is what embeds. */
  builtinAvailable: boolean;
  /** The built-in model in use; null when workspaces use their AI provider's own. */
  model: string | null;
  dimensions: number | null;
  engine: string;
  engineVersion: string | null;
  onnxruntimeVersion: string | null;
  /** Platform-wide, most chunks first. A model other than `model` is a stale index awaiting a reindex. */
  indexedModels: IndexedEmbeddingModel[];
}

export interface AdminAbout {
  embeddings?: EmbeddingsInfo | null;
}

export async function getAdminAbout(authToken?: string): Promise<AdminAbout> {
  return fetchApi<AdminAbout>("/api/admin/about", { method: "GET" }, authToken);
}
