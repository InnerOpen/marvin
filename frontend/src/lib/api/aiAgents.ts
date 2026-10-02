/**
 * Workspace agents — /api/ai/agents (not in the SDK yet). Pass authToken in SSR (from Astro.cookies);
 * omit it in the browser to go through the same-origin proxy with the HttpOnly cookie.
 */

import { fetchApi } from "./client";

export type AgentKind = "persona" | "model";
/** `ask` = "ask first": the tool is bound but each call pauses the run for the user's approval (Ask page threads only). */
export type PolicyValue = "allow" | "ask" | "block";
export type Register = "auto" | "professional" | "playful";

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
}

export type AgentCreate = Omit<Agent, "id" | "isSystem" | "minRole" | "enabled" | "allowWrites"> &
  Partial<Pick<Agent, "minRole" | "enabled" | "allowWrites">>;
export type AgentUpdate = Partial<Omit<Agent, "id" | "slug" | "isSystem">>;

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
  tools: MatrixTool[];
}
export interface Permissions {
  agent: string;
  role: number;
  allowWrites: boolean;
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
/** A tool call waiting for the user's decision (an "ask first" tool). */
export interface PendingCall {
  id: string;
  tool: string;
  arguments: unknown;
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
  metaJson?: { sources?: Source[]; totalTokens?: number; handoffs?: Handoff[]; referrals?: Referral[] } | null;
  executionId?: string | null;
  createdAt?: string | null;
}
export interface ThreadDetail extends Thread {
  messages: ThreadMessage[];
  /** Calls a parked run is waiting on (status "awaiting_approval"); empty otherwise. */
  pending: PendingCall[];
}

/** `threadId` value that asks a run to open a fresh server-side thread. */
export const NEW_THREAD = "new";

/** One live event of an in-flight run (see services/ai/run_progress.py). */
export interface RunEvent {
  type: "thinking" | "tool_call" | "tool_result" | "declined" | "awaiting_approval";
  tool?: string;
  arguments?: unknown;
  ok?: boolean;
  /** Set on `awaiting_approval`: the calls the run is waiting on. */
  calls?: { id: string; tool: string }[];
  /** Set on events a delegated child run emitted: the specialist's slug. */
  via?: string;
  at: number;
}
export interface RunProgress {
  id: string;
  status: "running" | "completed" | "failed" | "awaiting_approval";
  events: RunEvent[];
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
export function deleteAgent(slug: string, authToken?: string): Promise<void> {
  return fetchApi<void>(`/api/ai/agents/${encodeURIComponent(slug)}`, { method: "DELETE" }, authToken);
}

/**
 * Run a named agent. Stateless callers pass `history` (prior turns, oldest first, excluding this
 * message); thread-backed callers pass `threadId` (NEW_THREAD to open one) and the server keeps the
 * history — `history` is then ignored.
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
  } = {},
  authToken?: string,
): Promise<AgentRunResult> {
  return fetchApi<AgentRunResult>(
    `/api/ai/agents/${encodeURIComponent(slug)}/run`,
    json({
      message,
      source: "agent",
      ...(opts.register ? { register: opts.register } : {}),
      ...(opts.entityType && opts.entityId ? { entityType: opts.entityType, entityId: opts.entityId } : {}),
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

/** Top-level threads by default; `children: true` includes the specialist threads hand-offs opened. */
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
/**
 * Decide the calls a parked run is waiting on and continue it. Missing ids count as denied. The
 * result has the shape of a run (it may park again: `stoppedReason === "awaiting_approval"`).
 */
export function resumeThread(
  id: string,
  decisions: Record<string, "approve" | "deny">,
  opts: { clientRunId?: string } = {},
  authToken?: string,
): Promise<AgentRunResult> {
  return fetchApi<AgentRunResult>(
    `/api/ai/threads/${encodeURIComponent(id)}/resume`,
    json({ decisions, ...(opts.clientRunId ? { clientRunId: opts.clientRunId } : {}) }),
    authToken,
  );
}
