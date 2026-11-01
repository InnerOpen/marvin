/**
 * "Delete all of these" on an Automation page's From a removed integration section: one call per kind of item
 * (DELETE /api/groups/removed-integration-items/{kind}, ADMIN). Not in the SDK yet, so it goes through fetchApi.
 */

import { fetchApi } from "./client";

export type RemovedKind = "workflows" | "incoming-webhooks" | "scheduled-tasks" | "outgoing-webhooks";

export interface RemovedIntegrationDeleted {
  kind: RemovedKind;
  deleted: number;
  names: string[];
}

export async function deleteRemovedIntegrationItems(kind: RemovedKind): Promise<RemovedIntegrationDeleted> {
  return fetchApi(`/api/groups/removed-integration-items/${kind}`, { method: "DELETE" });
}
