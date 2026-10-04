/**
 * Ask Marvin bubble — SDK-backed calls (browser: omit token, uses the HttpOnly cookie).
 * Every call identifies as the `bubble` surface, so the workspace's bubble invocation-source toggle
 * governs it (the Ask page is `ask_page`, the entry editor's inline actions are `editor`).
 * Chat = plain completion; ask = grounded RAG answer via the answer-workspace-question operation.
 */

import { createSdkClient } from "../sdk";

/** Plain, ungrounded chat completion (no tools, no RAG). */
export async function sendChat(message: string) {
  return createSdkClient().ai.chat({ message, source: "bubble" });
}

/** Grounded answer from the workspace's indexed content (RAG). */
export async function askWorkspace(question: string) {
  return createSdkClient().ai.operations.execute("answer-workspace-question", {
    input: { question },
    source: "bubble",
  });
}

/**
 * Where a bubble agent run lives: its server thread (`threadId`, or NEW_THREAD to open one — the
 * server replays the thread as the agent's memory) and the run id the client minted to follow it
 * (see @/lib/marvin/pending).
 */
export interface BubbleRunRef {
  threadId: string;
  clientRunId: string;
}

/**
 * Agent loop — Marvin picks and chains tools to reach a goal.
 * `context` grounds the run in whatever the current page declared (see @/lib/marvin/context);
 * omit it for an unscoped, workspace-wide ask.
 */
export async function runAgent(
  message: string,
  context: { entityType?: string; entityId?: string } | null | undefined,
  ref: BubbleRunRef,
  register?: string, // a tone slug (@/lib/tones)
) {
  // The SDK's `register` union predates custom tones; the server takes any tone slug the workspace has.
  type SdkRegister = Parameters<ReturnType<typeof createSdkClient>["ai"]["agent"]>[0]["register"];
  return createSdkClient().ai.agent({
    message,
    source: "bubble",
    ...(register ? { register: register as SdkRegister } : {}),
    ...(context?.entityType && context.entityId ? { entityType: context.entityType, entityId: context.entityId } : {}),
    // Spread rather than listed: the SDK's request type predates threads; the server reads them all the same.
    ...ref,
  });
}

// ── Named agents (system + workspace-defined) ────────────────────────────────
// Not in the SDK yet; same-origin fetch through the proxy (cookie → Bearer server-side).

import { getApiBaseUrl } from "./config";

export interface AgentSummary {
  slug: string;
  name: string;
  kind: "persona" | "model";
  description?: string | null;
  isSystem: boolean;
  enabled: boolean;
  allowWrites: boolean;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getApiBaseUrl()}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json())?.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export function listAgents() {
  return api<AgentSummary[]>("/api/ai/agents");
}

/** Run a named agent — same shape as runAgent, routed to `/api/ai/agents/{slug}/run`. */
export function runAgentAs(
  slug: string,
  message: string,
  context: { entityType?: string; entityId?: string } | null | undefined,
  ref: BubbleRunRef,
  register?: string, // a tone slug (@/lib/tones)
) {
  return api<any>(`/api/ai/agents/${encodeURIComponent(slug)}/run`, {
    method: "POST",
    body: JSON.stringify({
      message,
      source: "bubble",
      ...(register ? { register } : {}),
      ...(context?.entityType && context.entityId
        ? { entityType: context.entityType, entityId: context.entityId }
        : {}),
      ...ref,
    }),
  });
}
