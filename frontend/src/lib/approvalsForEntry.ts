// The workflow approvals still waiting on one entry, for the banner on the entry's page. The approvals list names the entry each one
// belongs to (`entryId`), so nothing more is asked of the server: the page filters the list it already has the right to read.
import type { WorkflowApproval } from "./api/workflowApprovals";

export function pendingFor(approvals: readonly WorkflowApproval[], entryId: string | null | undefined): WorkflowApproval[] {
  if (!entryId) return [];
  return approvals.filter((a) => a.entryId === entryId && a.status === "pending");
}
