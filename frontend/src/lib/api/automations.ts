/**
 * Automations (Flavor B workflows) — SDK wrapper (platform.automations).
 * Pass authToken in SSR (from Astro.cookies); omit it in the browser to use the HttpOnly cookie.
 */

import type {
  Automation,
  AutomationCreate,
  AutomationDefinition,
  AutomationOptions,
  AutomationPreviewResult,
  AutomationUpdate,
  AutomationValidateResult,
} from "@inneropen/marvin-sdk/platform";
import { createSdkClient } from "../sdk";
import { getApiUrl } from "./config";

export type { Automation, AutomationCreate, AutomationOptions, AutomationUpdate };

/** Advisory coherence check for a definition (warnings, non-blocking). */
export async function validateAutomation(
  definition: AutomationDefinition,
  authToken?: string,
): Promise<AutomationValidateResult> {
  return createSdkClient(authToken).automations.validate(definition);
}

/** Dry-run a target selector — which entities it would act on, without running anything. */
export async function previewAutomation(
  definition: AutomationDefinition,
  payload: Record<string, unknown> = {},
  authToken?: string,
): Promise<AutomationPreviewResult> {
  return createSdkClient(authToken).automations.preview(definition, payload);
}

export async function listAutomations(authToken?: string): Promise<Automation[]> {
  return createSdkClient(authToken).automations.list();
}

export async function getAutomationOptions(authToken?: string): Promise<AutomationOptions> {
  return createSdkClient(authToken).automations.options();
}

export async function createAutomation(data: AutomationCreate, authToken?: string): Promise<Automation> {
  return createSdkClient(authToken).automations.create(data);
}

export async function updateAutomation(id: string, data: AutomationUpdate, authToken?: string): Promise<Automation> {
  return createSdkClient(authToken).automations.update(id, data);
}

export async function deleteAutomation(id: string, authToken?: string): Promise<void> {
  return createSdkClient(authToken).automations.delete(id);
}

/** Run an automation now (the Manual trigger). */
export async function runAutomation(id: string, authToken?: string) {
  return createSdkClient(authToken).automations.run(id);
}

/** A sample event a dry run can test against: a logged event, or one built for an entry. */
export interface DryRunSample {
  kind: "event" | "entry";
  id: string;
  label: string;
  event_type: string;
  occurred_at: string | null;
  synthesized: boolean;
  conditions_pass: boolean | null;
}

// Not in the SDK yet (picking a dry run's sample, listing candidates): a cookie-authed fetch like
// the SDK client's.
async function automationsApi<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(getApiUrl(path), { credentials: "include", headers: { Accept: "application/json" }, ...init });
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

/**
 * Dry-run an automation: resolve target + inputs, execute nothing, return the plan. An
 * event-triggered workflow runs against `sample` (or, without one, the latest matching event) and
 * the result also carries `sample`, `trigger_matched`, `conditions` and `would_fire`.
 */
export async function dryRunAutomation(id: string, sample?: Pick<DryRunSample, "kind" | "id">, authToken?: string) {
  if (!sample) return createSdkClient(authToken).automations.dryRun(id);
  const param = sample.kind === "entry" ? "entry_id" : "event_id";
  const query = new URLSearchParams({ dry_run: "true", [param]: sample.id });
  return automationsApi<Record<string, unknown>>(`/api/automations/${encodeURIComponent(id)}/run?${query}`, { method: "POST" });
}

/** Recent events (then entries) an event-triggered workflow's dry run can test against. */
export async function listDryRunSamples(id: string, limit = 10) {
  return automationsApi<{ event_type: string | null; samples: DryRunSample[] }>(
    `/api/automations/${encodeURIComponent(id)}/samples?limit=${limit}`,
  );
}

/** Recent runs of an automation (history list). */
export async function listAutomationExecutions(id: string, limit = 25, authToken?: string) {
  return createSdkClient(authToken).automations.executions(id, limit);
}

/** One run + its per-step records. */
export async function getAutomationExecution(id: string, executionId: string, authToken?: string) {
  return createSdkClient(authToken).automations.execution(id, executionId);
}
