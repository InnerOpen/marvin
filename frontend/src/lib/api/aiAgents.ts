/**
 * Workspace agents — /api/ai/agents (not in the SDK yet). Pass authToken in SSR (from Astro.cookies);
 * omit it in the browser to go through the same-origin proxy with the HttpOnly cookie.
 */

import type { AgentPromptPreview } from "@/lib/promptPreview";
import { fetchApi } from "./client";

export type AgentKind = "persona" | "model";
/** `ask` = "ask first": the tool is bound but each call pauses the run for the user's approval (Ask page threads only). */
export type PolicyValue = "allow" | "ask" | "block";
/** A tone slug: a built-in (auto | professional | playful) or one of the workspace's own (@/lib/tones). */
export type Register = string;

export interface Agent {
  id: string | null;
  slug: string;
  name: string;
  description?: string | null;
  kind: AgentKind;
  systemPrompt?: string | null;
  modelOverride?: string | null;
  toolAllowlist?: string[] | null;
  defaultRegister?: Register | null;
  minRole: number;
  sources?: string[] | null;
  enabled: boolean;
  allowWrites: boolean;
  toolPolicy?: Record<string, PolicyValue> | null;
  icon?: string | null;
  suggestions?: string[] | null;
  /** One line for the router's roster: when Marvin should hand a question to this agent. */
  handoffHint?: string | null;
  isSystem: boolean;
  /**
   * A built-in agent whose permission matrix this workspace changed (`toolPolicy` is then the effective,
   * merged matrix). Only the matrix of a built-in can change; reset with `resetAgentToolPolicy`.
   */
  toolPolicyOverridden?: boolean;
  /**
   * The bubble's character while this agent talks — its own upload, or a library pack's states — set
   * through /api/ai/agents/{slug}/character. Null → the workspace's. Built-ins never have one.
   */
  character?: { library?: string | null; name?: string | null; states: Record<string, string> } | null;
}

export type AgentCreate = Omit<Agent, "id" | "isSystem" | "minRole" | "enabled" | "allowWrites" | "character"> &
  Partial<Pick<Agent, "minRole" | "enabled" | "allowWrites">>;
export type AgentUpdate = Partial<Omit<Agent, "id" | "slug" | "isSystem" | "character" | "toolPolicyOverridden">>;

export interface ToolCategory {
  id: string;
  label: string;
  writes: boolean;
  description: string;
}
export interface CatalogTool {
  name: string;
  category: string;
  description: string;
  kind: "tool" | "operation";
  readOnly: boolean;
  minRole: number;
}
export interface Catalog {
  categories: ToolCategory[];
  tools: CatalogTool[];
}

export interface MatrixTool extends CatalogTool {
  decision: PolicyValue;
  reason: string;
  override: PolicyValue | null;
}
export interface MatrixRow {
  id: string;
  label: string;
  writes: boolean;
  description: string;
  default: PolicyValue;
  override: PolicyValue | null;
  /** What the row does with no entry in the matrix — the editor's "Default (…)" choice. */
  inherited?: PolicyValue;
  tools: MatrixTool[];
}
export interface Permissions {
  agent: string;
  role: number;
  allowWrites: boolean;
  /** A built-in agent whose matrix this workspace changed. */
  overridden?: boolean;
  rows: MatrixRow[];
}

export interface Source {
  entityType: string;
  entityId: string;
  title?: string | null;
}
/** A specialist the router ran for this turn; `threadId` is the child thread "Continue with X" opens. */
export interface Handoff {
  agent: string;
  threadId?: string | null;
  executionId?: string | null;
}
/** A `suggest_agent` call: the agent that should be asked, and what to ask it. Nothing was run. */
export interface Referral {
  agent: string;
  name?: string | null;
  question?: string | null;
  reason?: string | null;
}
/**
 * An approval card's preview: what a big bulk write would link, or what an ask-first call would touch
 * (`archive` / `trash`: the entries, no items) — see services/ai/tools/bulk_writes.py.
 */
export interface BulkWritePreview {
  summary: string;
  action: "attach" | "detach" | "archive" | "trash";
  links: number;
  targetType: string;
  targetCount: number;
  /** Target names, capped; `targetCount` is the real total. */
  targets: string[];
  itemKind: string;
  items: string[];
}
/**
 * A tool call waiting for the user's decision (an "ask first" tool). A specialist's ask carried up through
 * a hand-off has a path id (`c1/c7` — the hand-off call, then the specialist's call) and says whose it is.
 */
export interface PendingCall {
  id: string;
  tool: string;
  arguments: unknown;
  preview?: BulkWritePreview;
  /** The specialist that asked (innermost, when hand-offs nest); absent on the agent's own asks. */
  via?: string;
  viaName?: string;
  /** Every specialist between the conversation and the ask, outermost first. */
  viaChain?: string[];
  /** The specialist's own thread, where its paused run waits. */
  childThreadId?: string;
  childExecutionId?: string;
}
export interface AgentRunResult {
  answer: string;
  steps: { tool: string; arguments: unknown; result?: unknown }[];
  /** Citations gathered from the run's `search_content` results. */
  sources?: Source[];
  handoffs?: Handoff[];
  referrals?: Referral[];
  /** "complete" | "max_steps" | "awaiting_approval" — the last one carries `pending` and no answer yet. */
  stoppedReason: string;
  pending?: PendingCall[];
  executionId: string;
  /** The server-side thread this turn was stored on (only when the run asked for one). */
  threadId?: string | null;
  totalTokens: number;
  estimatedCostUsd?: number | null;
}

export interface Thread {
  id: string;
  agentSlug: string;
  title?: string | null;
  entityType?: string | null;
  entityId?: string | null;
  createdBy: string;
  /** Set on a hand-off child (the specialist's thread under a router thread). */
  parentThreadId?: string | null;
  /** The parent thread's title, on a hand-off child listed with `children: true`. */
  parentTitle?: string | null;
  status: "open" | "awaiting_approval" | "archived";
  totalTokens: number;
  lastMessageAt?: string | null;
  createdAt?: string | null;
}
export interface ThreadMessage {
  id: string;
  seq: number;
  role: "user" | "assistant";
  content: string;
  stepsJson?: { tool: string; arguments?: unknown; result?: string }[] | null;
  metaJson?: {
    sources?: Source[];
    totalTokens?: number;
    handoffs?: Handoff[];
    referrals?: Referral[];
    /** A turn closing a paused run that was never decided: a new message arrived, or it expired. */
    abandoned?: boolean;
    expired?: boolean;
    no_longer_permitted?: boolean;
    /** On a user turn: the files attached to the question (id, name, mimeType). */
    attachments?: { id: string; name: string; mimeType: string }[];
  } | null;
  executionId?: string | null;
  createdAt?: string | null;
}
export interface ThreadDetail extends Thread {
  messages: ThreadMessage[];
  /** Calls a parked run is waiting on (status "awaiting_approval"), flattened; empty otherwise. */
  pending: PendingCall[];
  /**
   * On a parked specialist's thread: the conversation its decision belongs to. Resuming here forwards
   * there, and the result is that conversation's (its `threadId` is this id).
   */
  rootThreadId?: string | null;
}

/** `threadId` value that asks a run to open a fresh server-side thread. */
export const NEW_THREAD = "new";

/** One live event of an in-flight run (see services/ai/run_progress.py). */
export interface RunEvent {
  type: "thinking" | "tool_call" | "tool_result" | "declined" | "awaiting_approval";
  tool?: string;
  arguments?: unknown;
  ok?: boolean;
  /** Set on `awaiting_approval`: the calls the run is waiting on (a specialist's carry its `via`). */
  calls?: { id: string; tool: string; via?: string }[];
  /** Set on events a delegated child run emitted: the specialist's slug (the innermost one when nested). */
  via?: string;
  viaChain?: string[];
  /** On a `run_agent` tool_result: the specialist paused for the user's approval; its answer comes later. */
  deferred?: boolean;
  /** On `declined`: "not_permitted" when an approved call was no longer allowed at decision time. */
  reason?: string;
  at: number;
}
export interface RunProgress {
  id: string;
  status: "running" | "completed" | "failed" | "awaiting_approval";
  events: RunEvent[];
  /** The run's thread and execution, set as soon as they exist — how a client that lost the response finds the answer. */
  threadId?: string | null;
  executionId?: string | null;
  /** Why a failed run failed. */
  error?: string | null;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export function listAgents(authToken?: string): Promise<Agent[]> {
  return fetchApi<Agent[]>("/api/ai/agents", {}, authToken);
}
export function getAgent(slug: string, authToken?: string): Promise<Agent> {
  return fetchApi<Agent>(`/api/ai/agents/${encodeURIComponent(slug)}`, {}, authToken);
}
export function getCatalog(authToken?: string): Promise<Catalog> {
  return fetchApi<Catalog>("/api/ai/agents/catalog", {}, authToken);
}
export function getPermissions(slug: string, authToken?: string): Promise<Permissions> {
  return fetchApi<Permissions>(`/api/ai/agents/${encodeURIComponent(slug)}/permissions`, {}, authToken);
}
export function createAgent(data: AgentCreate, authToken?: string): Promise<Agent> {
  return fetchApi<Agent>("/api/ai/agents", json(data), authToken);
}
export function updateAgent(slug: string, data: AgentUpdate, authToken?: string): Promise<Agent> {
  return fetchApi<Agent>(`/api/ai/agents/${encodeURIComponent(slug)}`, { ...json(data), method: "PATCH" }, authToken);
}
/**
 * Drop every override of an agent's permission matrix (ADMIN+): a built-in goes back to its code matrix, a
 * workspace agent to the defaults its Allow writes setting gives. To change a built-in's matrix, PATCH
 * `{ toolPolicy }` through `updateAgent` — any other field on a built-in is a 400.
 */
export function resetAgentToolPolicy(slug: string, authToken?: string): Promise<Agent> {
  return fetchApi<Agent>(`/api/ai/agents/${encodeURIComponent(slug)}/tool-policy`, { method: "DELETE" }, authToken);
}
/**
 * The system prompt a run of the agent sends, in labelled parts (lib/promptPreview). `data` is the Edit form's
 * unsaved values; anything left out is the stored agent's. ADMIN+; never calls a model.
 */
export function previewAgentPrompt(
  slug: string,
  data: AgentUpdate = {},
  authToken?: string,
): Promise<AgentPromptPreview> {
  return fetchApi<AgentPromptPreview>(
    `/api/ai/agents/${encodeURIComponent(slug)}/preview-prompt`,
    json(data),
    authToken,
  );
}
/**
 * The same preview for an agent not saved yet: `data` is the New form's whole create payload (the slug may be
 * blank while typing). Nothing is stored. ADMIN+; never calls a model.
 */
export function previewNewAgentPrompt(
  data: Omit<AgentCreate, "slug"> & { slug?: string },
  authToken?: string,
): Promise<AgentPromptPreview> {
  return fetchApi<AgentPromptPreview>("/api/ai/agents/preview-prompt", json(data), authToken);
}
export function deleteAgent(slug: string, authToken?: string): Promise<void> {
  return fetchApi<void>(`/api/ai/agents/${encodeURIComponent(slug)}`, { method: "DELETE" }, authToken);
}

/**
 * Run a named agent from the Ask page (the `ask_page` invocation source). Stateless callers pass
 * `history` (prior turns, oldest first, excluding this message); thread-backed callers pass `threadId`
 * (NEW_THREAD to open one) and the server keeps the history — `history` is then ignored.
 */
export function runAgent(
  slug: string,
  message: string,
  opts: {
    history?: { role: "user" | "assistant"; content: string }[];
    threadId?: string;
    /** A UUID the caller mints; poll `getRunProgress(id)` while this call is pending. */
    clientRunId?: string;
    register?: Register;
    entityType?: string;
    entityId?: string;
    /** Asset ids of the files attached to the conversation (@/lib/marvin/attachments). */
    attachments?: string[];
  } = {},
  authToken?: string,
): Promise<AgentRunResult> {
  return fetchApi<AgentRunResult>(
    `/api/ai/agents/${encodeURIComponent(slug)}/run`,
    json({
      message,
      source: "ask_page",
      ...(opts.register ? { register: opts.register } : {}),
      ...(opts.entityType && opts.entityId ? { entityType: opts.entityType, entityId: opts.entityId } : {}),
      ...(opts.attachments?.length ? { attachments: opts.attachments } : {}),
      ...(opts.threadId ? { threadId: opts.threadId } : {}),
      ...(opts.clientRunId ? { clientRunId: opts.clientRunId } : {}),
      ...(opts.history?.length && !opts.threadId ? { history: opts.history } : {}),
    }),
    authToken,
  );
}

/** Live steps of a run started with `clientRunId`; 404 = nothing recorded (unknown / expired / another replica). */
export function getRunProgress(runId: string, authToken?: string): Promise<RunProgress> {
  return fetchApi<RunProgress>(`/api/ai/agents/runs/${encodeURIComponent(runId)}/progress`, {}, authToken);
}

// ── Threads (server-side Ask conversations; own-only, admins see all) ──

/**
 * Top-level threads, every agent's unless `agent` is given. `children: true` adds the specialist threads
 * hand-offs opened under the listed ones (`limit` counts listed threads only); with `agent`, its own
 * hand-off threads are listed too. See groupThreads (lib/askThreads.ts) for nesting them.
 */
export function listThreads(
  opts: { agent?: string; limit?: number; children?: boolean } = {},
  authToken?: string,
): Promise<Thread[]> {
  const q = new URLSearchParams();
  if (opts.agent) q.set("agent", opts.agent);
  if (opts.limit) q.set("limit", String(opts.limit));
  if (opts.children) q.set("children", "true");
  const qs = q.toString();
  return fetchApi<Thread[]>(`/api/ai/threads${qs ? `?${qs}` : ""}`, {}, authToken);
}
export function getThread(id: string, authToken?: string): Promise<ThreadDetail> {
  return fetchApi<ThreadDetail>(`/api/ai/threads/${encodeURIComponent(id)}`, {}, authToken);
}
export function renameThread(id: string, title: string | null, authToken?: string): Promise<Thread> {
  return fetchApi<Thread>(
    `/api/ai/threads/${encodeURIComponent(id)}`,
    { ...json({ title }), method: "PATCH" },
    authToken,
  );
}
export function deleteThread(id: string, authToken?: string): Promise<void> {
  return fetchApi<void>(`/api/ai/threads/${encodeURIComponent(id)}`, { method: "DELETE" }, authToken);
}
/** The surfaces that decide a paused run; each is gated by its own invocation-source toggle. */
export type ResumeSource = "ask_page" | "bubble";

/**
 * Decide the calls a parked run is waiting on and continue it — from the Ask page (`ask_page`, the
 * default) or the bubble (`bubble`). Missing ids count as denied. The result has the shape of a run (it
 * may park again: `stoppedReason === "awaiting_approval"`); decided on a specialist's thread, it is the
 * root conversation's.
 */
export function resumeThread(
  id: string,
  decisions: Record<string, "approve" | "deny">,
  opts: { clientRunId?: string; source?: ResumeSource } = {},
  authToken?: string,
): Promise<AgentRunResult> {
  return fetchApi<AgentRunResult>(
    `/api/ai/threads/${encodeURIComponent(id)}/resume`,
    json({
      decisions,
      source: opts.source ?? "ask_page",
      ...(opts.clientRunId ? { clientRunId: opts.clientRunId } : {}),
    }),
    authToken,
  );
}
