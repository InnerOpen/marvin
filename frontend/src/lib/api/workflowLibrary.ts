/**
 * The Workflow Library — every recipe, what this workspace needs to use each, and filling one in for the workflow
 * editor. Configuring never saves: the editor's Save creates the workflow, switched off.
 *
 * Browser calls go through the same-origin proxy (fetchApi with no token); SSR passes the cookie token.
 * Hand-rolled until the SDK ships `automations.library()` / `automations.configureRecipe()`.
 */

import type { WorkflowLibrary } from "../workflowLibrary";
import { fetchApi } from "./client";

export interface RecipeConfigureResult {
  name: string;
  definition: Record<string, unknown>;
  /** What the builder would flag (a webhook or entry type this workspace doesn't have) — shown, not blocking. */
  issues: { level: string; message: string; where: string; path?: string | null }[];
}

export async function getWorkflowLibrary(authToken?: string): Promise<WorkflowLibrary> {
  return fetchApi<WorkflowLibrary>("/api/automations/library", {}, authToken);
}

/** The recipe filled in with `vars`. 409: not usable here (the message says why); 422: a value is missing or wrong. */
export async function configureRecipe(id: string, vars: Record<string, string | number>, authToken?: string): Promise<RecipeConfigureResult> {
  return fetchApi<RecipeConfigureResult>(
    `/api/automations/library/${encodeURIComponent(id)}/configure`,
    { method: "POST", body: JSON.stringify({ vars }), headers: { "Content-Type": "application/json" } },
    authToken,
  );
}
