/**
 * Workflow runs waiting at an Approval step (GET /api/automations/approvals) and deciding one
 * (POST /api/automations/approvals/{id}/decide) — the run then goes on from the next step. Editors and above; a step
 * may ask for admins. Hand-rolled until the SDK ships `automations.approvals()`.
 */

import { fetchApi } from "./client";

export interface WorkflowApproval {
  id: string;
  automationId: string;
  automationName?: string | null;
  automationSlug?: string | null;
  message: string;
  approvers: "editor" | "admin" | string;
  status: string;
  entryId?: string | null;
  entryTitle?: string | null;
  createdAt?: string | null;
  expiresAt: string;
  note?: string | null;
}

export async function listApprovals(authToken?: string): Promise<WorkflowApproval[]> {
  return fetchApi<WorkflowApproval[]>("/api/automations/approvals", {}, authToken);
}

export async function decideApproval(
  id: string,
  decision: "approve" | "deny",
  note?: string,
): Promise<WorkflowApproval> {
  return fetchApi<WorkflowApproval>(`/api/automations/approvals/${encodeURIComponent(id)}/decide`, {
    method: "POST",
    body: JSON.stringify({ decision, note: note || null }),
  });
}
