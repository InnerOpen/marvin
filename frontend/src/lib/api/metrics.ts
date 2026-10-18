/**
 * Metric observations: the numbers a workflow's Metric step recorded, per metric, variant and window
 * (GET /api/groups/metrics, GET /api/groups/metrics/observations, DELETE …/observations/{id}).
 * Reading is EDITOR and above; removing one is ADMIN/OWNER. Observations, not conclusions. Plain fetchApi until the SDK
 * release carries them. Pass authToken in SSR (from Astro.cookies); omit it in the browser.
 */

import { fetchApi } from "./client";

export interface MetricSummary {
  metric: string;
  count: number;
  firstWindow: string;
  lastWindow: string;
}

export interface MetricObservation {
  id: string;
  metric: string;
  /** "" when the step named none. */
  variant: string;
  subject: string;
  /** `2026-10-18` (day), `2026-W42` (ISO week) or `2026-10` (month). */
  window: string;
  granularity: "day" | "week" | "month";
  windowStart: string;
  value: number;
  workflowName?: string | null;
  workflowSlug?: string | null;
  updatedAt?: string | null;
}

export interface MetricObservationList {
  items: MetricObservation[];
  total: number;
  limit: number;
  offset: number;
  note: string;
}

export interface MetricFilter {
  metric?: string;
  variant?: string;
  subject?: string;
  windowFrom?: string;
  windowTo?: string;
  limit?: number;
}

export async function listMetrics(authToken?: string): Promise<MetricSummary[]> {
  return fetchApi("/api/groups/metrics", {}, authToken);
}

export async function listObservations(filter: MetricFilter = {}, authToken?: string): Promise<MetricObservationList> {
  const q = new URLSearchParams();
  if (filter.metric) q.set("metric", filter.metric);
  if (filter.variant !== undefined) q.set("variant", filter.variant);
  if (filter.subject !== undefined) q.set("subject", filter.subject);
  if (filter.windowFrom) q.set("window_from", filter.windowFrom);
  if (filter.windowTo) q.set("window_to", filter.windowTo);
  q.set("limit", String(filter.limit ?? 500));
  return fetchApi(`/api/groups/metrics/observations?${q}`, {}, authToken);
}

export async function deleteObservation(id: string, authToken?: string): Promise<void> {
  await fetchApi(`/api/groups/metrics/observations/${encodeURIComponent(id)}`, { method: "DELETE" }, authToken);
}
