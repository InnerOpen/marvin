/**
 * A workspace's own events (`custom.<name>`): list, register or change, remove. Workspace OWNER/ADMIN.
 * Pass authToken in SSR (from Astro.cookies); omit it in the browser. Plain fetchApi until the SDK release carries them.
 */

import { fetchApi } from "./client";

export type CustomEventFieldType = "string" | "number" | "boolean" | "date";

interface CustomEventField {
  key: string;
  type: CustomEventFieldType;
  description?: string | null;
}

export interface CustomEvent {
  name: string;
  /** The full event name, `custom.<name>`. */
  eventType: string;
  title?: string | null;
  description?: string | null;
  fields: CustomEventField[];
  /** Names of the workflows that start on it or send it. */
  usedBy: string[];
}

export interface CustomEventSave {
  title?: string | null;
  description?: string | null;
  fields: CustomEventField[];
}

export const CUSTOM_EVENT_FIELD_TYPES: CustomEventFieldType[] = ["string", "number", "boolean", "date"];

export async function listCustomEvents(authToken?: string): Promise<CustomEvent[]> {
  return fetchApi("/api/groups/custom-events", {}, authToken);
}

export async function saveCustomEvent(name: string, body: CustomEventSave, authToken?: string): Promise<CustomEvent> {
  return fetchApi(
    `/api/groups/custom-events/${encodeURIComponent(name)}`,
    { method: "PUT", body: JSON.stringify(body) },
    authToken,
  );
}

export async function deleteCustomEvent(name: string, authToken?: string): Promise<void> {
  await fetchApi(`/api/groups/custom-events/${encodeURIComponent(name)}`, { method: "DELETE" }, authToken);
}
