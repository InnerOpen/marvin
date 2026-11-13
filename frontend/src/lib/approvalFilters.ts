/**
 * The address of the approvals list, narrowed to what a page is about (a workflow by slug, some entries, the run that asked). The server
 * applies these before its cap of 100, so a page finds its own cards however many others wait. Pure, for `node --test`.
 */

export interface ApprovalFilters {
  automation?: string;
  entryIds?: string[];
  executionId?: string;
}

/** The server takes at most this many `entry_id`s in one request. */
export const MAX_ENTRY_FILTER = 50;

export function approvalsPath(state: "pending" | "decided" = "pending", only: ApprovalFilters = {}): string {
  const params = new URLSearchParams();
  if (state === "decided") params.set("state", state);
  if (only.automation) params.set("automation", only.automation);
  for (const id of (only.entryIds ?? []).slice(0, MAX_ENTRY_FILTER)) params.append("entry_id", id);
  if (only.executionId) params.set("execution_id", only.executionId);
  const query = params.toString();
  return `/api/automations/approvals${query ? `?${query}` : ""}`;
}
