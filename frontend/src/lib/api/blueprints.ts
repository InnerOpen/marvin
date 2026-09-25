/**
 * Blueprints — the catalog of structure a workspace could have, and applying it.
 *
 * A blueprint describes a collection, entry type or scheduled task without creating anything.
 * Core ships a catalog of examples; installed integration providers contribute the content their
 * actions depend on. Applying creates what is missing and never overwrites what exists, so a
 * repeat apply is a no-op that says so.
 *
 * There is deliberately no blueprint gallery. The catalog is consumed where it is useful: as
 * examples offered while you create a collection or entry type, as the content an integration
 * brings on install, and as the worked examples that teach an agent the rule vocabulary well
 * enough to compose rules of its own.
 *
 * Browser calls go through the same-origin proxy (fetchApi with no token); SSR passes the cookie token.
 */

import { fetchApi } from "./client";

export type BlueprintKind = "collection" | "entry_type" | "scheduled_task";

/** `entry_type`/`collection` render as a picker fed by the workspace's own content. */
export type ParameterKind = "entry_type" | "collection" | "text" | "number";

export interface BlueprintParameter {
  key: string;
  label: string;
  kind: ParameterKind;
  required: boolean;
  default: string | null;
  help: string;
}

export interface Blueprint {
  kind: BlueprintKind;
  slug: string;
  name: string;
  description: string;
  category: string;
  /** `core`, or the slug of the provider that contributed it. */
  source: string;
  requires: string[];
  parameters: BlueprintParameter[];
  payload: Record<string, unknown>;
  /** False when `requires` is unmet — shown, but not applicable. */
  available: boolean;
  missingRequirements: string[];
  /** Already in this workspace. Always false for a parameterised blueprint: its slug
   *  is not known until the parameters are. */
  applied: boolean;
}

export interface BlueprintApplyResult {
  slug: string;
  kind: BlueprintKind;
  created: boolean;
  detail: string;
  name: string;
}

export interface BlueprintFilters {
  kind?: BlueprintKind;
  category?: string;
  source?: string;
}

function query(filters: BlueprintFilters = {}): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value);
  }
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

/** The catalog, annotated with what this workspace can do about each entry. */
export async function listBlueprints(filters: BlueprintFilters = {}, authToken?: string): Promise<Blueprint[]> {
  return fetchApi<Blueprint[]>(`/api/groups/blueprints${query(filters)}`, {}, authToken);
}

/** Category names in catalog order — core's first, then each provider's. */
export async function listBlueprintCategories(authToken?: string): Promise<string[]> {
  return fetchApi<string[]>("/api/groups/blueprints/categories", {}, authToken);
}

/** One blueprint including its payload — what a prefilled editor reads. */
export async function getBlueprint(slug: string, source?: string, authToken?: string): Promise<Blueprint> {
  return fetchApi<Blueprint>(`/api/groups/blueprints/${encodeURIComponent(slug)}${query({ source })}`, {}, authToken);
}

/** Create this blueprint's object, unless something already has its slug. */
export async function applyBlueprint(
  slug: string,
  params?: Record<string, string>,
  source?: string,
  authToken?: string,
): Promise<BlueprintApplyResult> {
  return fetchApi<BlueprintApplyResult>(
    `/api/groups/blueprints/${encodeURIComponent(slug)}/apply${query({ source })}`,
    { method: "POST", body: JSON.stringify(params ?? null), headers: { "Content-Type": "application/json" } },
    authToken,
  );
}

/**
 * Apply several — what the "apply this integration's content" button sends. Entry types are
 * created before the collections and tasks that reference them, whatever order they arrive in.
 * `params` is keyed by blueprint slug.
 */
export async function applyBlueprints(
  slugs: string[],
  params?: Record<string, Record<string, string>>,
  source?: string,
  authToken?: string,
): Promise<BlueprintApplyResult[]> {
  return fetchApi<BlueprintApplyResult[]>(
    `/api/groups/blueprints/apply${query({ source })}`,
    { method: "POST", body: JSON.stringify({ slugs, params: params ?? null }), headers: { "Content-Type": "application/json" } },
    authToken,
  );
}
