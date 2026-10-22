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

type BlueprintKind =
  | "collection"
  | "entry_type"
  | "entry_fields"
  | "scheduled_task"
  | "event_subscription"
  | "incoming_webhook"
  | "workflow"
  | "playbook";

/** `entry_type`/`collection` render as a picker fed by the workspace's own content. */
type ParameterKind = "entry_type" | "collection" | "integration" | "text" | "number";

interface BlueprintParameter {
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
  /** True only when the source cannot work without it. Everything else is a suggestion. */
  required: boolean;
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
  /** An Update is worth offering (workflows and Playbooks): `update`, `edited_update` or `differs`. */
  outdated?: boolean;
  /** An applied workflow against the integration's current version. `edited`: changed in this workspace,
   *  nothing new from the integration; `edited_update`: changed here and a newer version exists; `differs`:
   *  installed before edits were tracked, so an old version can't be told from an edit. */
  state?: BlueprintState | null;
  /** The workspace changed it (`edited`, `edited_update`). */
  edited?: boolean;
  /** A Playbook once added: the id of the draft it made (the card links to it) and its status (`draft` until published). */
  installedId?: string | null;
  installedStatus?: string | null;
  /** A Playbook whose name something else already holds: why Add is refused (shown in place of Add). */
  conflict?: string | null;
}

export type BlueprintState = "current" | "update" | "edited" | "edited_update" | "differs";

export interface BlueprintApplyResult {
  slug: string;
  kind: BlueprintKind;
  created: boolean;
  /** An Update replaced an applied workflow's steps, or a Playbook's text and files. */
  updated?: boolean;
  /** An Update was refused because it would replace changes made here; repeat with `replaceEdits`. */
  needsConfirmation?: boolean;
  detail: string;
  name: string;
}

export interface BlueprintFilters {
  kind?: BlueprintKind;
  category?: string;
  source?: string;
}

function query(filters: object = {}): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

/** The catalog, annotated with what this workspace can do about each entry. */
export async function listBlueprints(filters: BlueprintFilters = {}, authToken?: string): Promise<Blueprint[]> {
  return fetchApi<Blueprint[]>(`/api/groups/blueprints${query(filters)}`, {}, authToken);
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
    {
      method: "POST",
      body: JSON.stringify({ slugs, params: params ?? null }),
      headers: { "Content-Type": "application/json" },
    },
    authToken,
  );
}

/**
 * Replace an applied workflow's steps (or a Playbook's text and files) with what its integration declares now; a workflow keeps
 * whether it's on, a Playbook its status. One changed in this workspace comes back `needsConfirmation` unless `replaceEdits`.
 */
export async function updateBlueprint(
  slug: string,
  source?: string,
  replaceEdits = false,
  authToken?: string,
  integrationId?: string,
): Promise<BlueprintApplyResult> {
  return fetchApi<BlueprintApplyResult>(
    `/api/groups/blueprints/${encodeURIComponent(slug)}/update${query({ source, replace_edits: replaceEdits || undefined, integration_id: integrationId })}`,
    { method: "POST", body: JSON.stringify(null), headers: { "Content-Type": "application/json" } },
    authToken,
  );
}
