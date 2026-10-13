/**
 * Admin Plugins API - the plugin packages the platform operator installed (read-only)
 */

import { fetchApi } from "../client";

/** What a plugin extends: integration providers, storage (asset providers / backup targets); AI providers next. */
export type PluginKind = "integration" | "storage" | "ai_provider";

export interface PluginProviderRead {
  slug: string;
  name: string;
  /** Emoji fallback when there is no accepted logo. */
  icon?: string;
  hasLogo?: boolean;
  actions: number;
  blueprints: number;
  /** Distinct workspaces with at least one connection to this provider. */
  workspaces: number;
  /** Storage plugins: "assets" (asset storage provider) and/or "backups" (backup target). */
  provides?: string[];
  /** Storage plugins: what the platform uses it for ("assets" = the active STORAGE_PROVIDER). */
  inUse?: string[];
}

export interface PluginRead {
  name: string;
  package: string | null;
  version: string | null;
  kind: PluginKind;
  ok: boolean;
  error: string | null;
  providers: PluginProviderRead[];
}

export async function listPlugins(authToken?: string): Promise<PluginRead[]> {
  return fetchApi<PluginRead[]>("/api/admin/plugins", { method: "GET" }, authToken);
}
