/**
 * Workspace agents — /api/ai/agents (not in the SDK yet). Pass authToken in SSR (from Astro.cookies);
 * omit it in the browser to go through the same-origin proxy with the HttpOnly cookie.
 */

import { fetchApi } from "./client";

export type AgentKind = "persona" | "model";
export type PolicyValue = "allow" | "block";
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

export interface AgentRunResult {
  answer: string;
  steps: { tool: string; arguments: unknown; result?: unknown }[];
  stoppedReason: string;
  executionId: string;
  totalTokens: number;
  estimatedCostUsd?: number | null;
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

/** Run a named agent. `history` = prior turns, oldest first, excluding this message. */
export function runAgent(
  slug: string,
  message: string,
  opts: {
    history?: { role: "user" | "assistant"; content: string }[];
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
      source: "editor",
      ...(opts.register ? { register: opts.register } : {}),
      ...(opts.entityType && opts.entityId ? { entityType: opts.entityType, entityId: opts.entityId } : {}),
      ...(opts.history?.length ? { history: opts.history } : {}),
    }),
    authToken,
  );
}
