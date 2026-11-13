import type { CaptionResult } from "@/lib/captionCheck";
/**
 * Workflow runs waiting at an Approval step (GET /api/automations/approvals) and deciding one
 * (POST /api/automations/approvals/{id}/decide) — the run then goes on from the next step. Editors and above; a step
 * may ask for admins. Hand-rolled until the SDK ships `automations.approvals()`.
 */

import { type ApprovalFilters, approvalsPath } from "@/lib/approvalFilters";
import { fetchApi } from "./client";

export interface WorkflowApproval {
  id: string;
  automationId: string;
  automationName?: string | null;
  automationSlug?: string | null;
  /** The run that asked (GET /api/automations/runs/{executionId} says where it stands). */
  executionId?: string | null;
  message: string;
  /** The long part of the question (a whole prompt): shown folded under the message. */
  detail?: string | null;
  approvers: "editor" | "admin" | string;
  status: string;
  entryId?: string | null;
  entryTitle?: string | null;
  createdAt?: string | null;
  expiresAt: string;
  /** Settled approvals: who decided (their name), when, and the note they left. */
  decidedByName?: string | null;
  decidedAt?: string | null;
  note?: string | null;
  /** An approval with choices: the labels to pick from, and the one picked once approved. */
  choices?: string[] | null;
  choice?: string | null;
  /** A picture shown with the question (the step's `image`). */
  imageUrl?: string | null;
  /** Pending, and the next step posts: what it will post, checked for each network (lib/captionCheck.ts). */
  postPreview?: { text: string; results: CaptionResult[] } | null;
}

/** Waiting for you (`pending`, oldest first), or the latest settled ones (`decided`, newest first, with who, when and the note).
 *  `only` narrows the list on the server to one workflow, some entries or the run that asked (lib/approvalFilters.ts). */
export async function listApprovals(authToken?: string, state: "pending" | "decided" = "pending", only: ApprovalFilters = {}): Promise<WorkflowApproval[]> {
  return fetchApi<WorkflowApproval[]>(approvalsPath(state, only), {}, authToken);
}

export async function decideApproval(
  id: string,
  decision: "approve" | "deny",
  note?: string,
  choice?: string | null,
): Promise<WorkflowApproval> {
  return fetchApi<WorkflowApproval>(`/api/automations/approvals/${encodeURIComponent(id)}/decide`, {
    method: "POST",
    body: JSON.stringify({ decision, note: note || null, choice: choice ?? null }),
  });
}
