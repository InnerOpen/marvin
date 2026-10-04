/**
 * Workspace tones — /api/groups/ai-settings/tones (not in the SDK yet). Reading is open to every member
 * (the pickers need it); saving is ADMIN/OWNER. Pass authToken in SSR; omit it in the browser.
 */

import type { PersonaRule, TonePreview, TonesState } from "@/lib/tones";
import { fetchApi } from "./client";

export interface ToneInput {
  /** Omit for a new tone (the server makes one from the name); a slug never changes on rename. */
  slug?: string;
  name: string;
  instructions: string;
  persona: PersonaRule;
  description?: string | null;
}

const BASE = "/api/groups/ai-settings/tones";

const send = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export function getTones(authToken?: string): Promise<TonesState> {
  return fetchApi<TonesState>(BASE, {}, authToken);
}

/** Replace the custom tones + hidden list (and optionally the default). 409 when agents use a removed tone. */
export function saveTones(
  data: { tones: ToneInput[]; hidden: string[]; defaultTone?: string },
  authToken?: string,
): Promise<TonesState> {
  return fetchApi<TonesState>(BASE, send("PUT", data), authToken);
}

/**
 * The section a tone adds to every agent step, with the workspace character — whole and in parts — and a rough
 * token count. A saved tone by `slug`, a draft by its fields, or with neither the workspace default.
 * `personaPrompt` / `assistantName` preview unsaved Character fields in place of the stored ones. ADMIN/OWNER.
 */
export function previewTone(
  data: {
    slug?: string;
    name?: string;
    instructions?: string;
    persona?: PersonaRule;
    personaPrompt?: string;
    assistantName?: string;
  },
  authToken?: string,
): Promise<TonePreview> {
  return fetchApi(`${BASE}/preview`, send("POST", data), authToken);
}
