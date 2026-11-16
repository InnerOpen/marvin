import type { ApprovalField } from "@/lib/approvalFields";
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
  /** Boxes the approver may change before approving (the prompt a paid step sends), each with its text as asked. */
  fields?: ApprovalField[] | null;
  /** Once approved: the boxes' text as approved, and which were changed. */
  fieldValues?: Record<string, string> | null;
  editedFields?: string[];
  /** The choice that makes it again: picked with a changed box, the next try starts from the change. */
  redo?: string | null;
  /** Pending, and it guards a paid step: its likely cost, from this workspace's earlier calls like it (or "cost unknown"). */
  estimate?: ApprovalEstimate | null;
  /** It guards a paid step; with a daily limit set, how much of today's is used (UTC). */
  paid?: boolean;
  spendLimit?: { limit: number; usedToday: number; resetsAt: string } | null;
}

export interface ApprovalEstimate {
  text: string;
  items?: { step?: string | null; text: string; amount?: number | null; unit?: string | null; calls?: number | null; unknown?: boolean }[];
  total?: { amount: number; unit: string } | null;
}

/** Waiting for you (`pending`, oldest first), or the latest settled ones (`decided`, newest first, with who, when and the note).
 *  `only` narrows the list on the server to one workflow, some entries or the run that asked (lib/approvalFilters.ts). */
export async function listApprovals(authToken?: string, state: "pending" | "decided" = "pending", only: ApprovalFilters = {}): Promise<WorkflowApproval[]> {
  return fetchApi<WorkflowApproval[]>(approvalsPath(state, only), {}, authToken);
}

/** Several waiting approvals answered at once ("Approve all 20"): each with its own choice and changed boxes. Each answer says how it
 *  went: its `status`, or the `error` that kept it back while the others still went. The runs go on one after another. */
export async function decideMany(
  items: { id: string; choice?: string; fields?: Record<string, string> }[],
  decision: "approve" | "deny",
  note?: string,
): Promise<{ id: string; status?: string | null; error?: string | null; code?: number | null }[]> {
  return fetchApi(`/api/automations/approvals/decide-many`, { method: "POST", body: JSON.stringify({ decision, note: note || null, items }) });
}

export async function decideApproval(
  id: string,
  decision: "approve" | "deny",
  note?: string,
  choice?: string | null,
  fields?: Record<string, string> | null,
): Promise<WorkflowApproval> {
  const changed = fields && Object.keys(fields).length ? { fields } : {};
  return fetchApi<WorkflowApproval>(`/api/automations/approvals/${encodeURIComponent(id)}/decide`, {
    method: "POST",
    body: JSON.stringify({ decision, note: note || null, choice: choice ?? null, ...changed }),
  });
}
