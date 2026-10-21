/**
 * Playbooks (routes/groups/playbooks_controller.py): the list with each Playbook's status, and the entry type's creation on first
 * write. EDITOR and above. A Playbook itself is read and saved through the entries API (`/api/platform/entries`), the same one the
 * entry editor uses, so its history, Trash and role rules are the entries' own. Plain fetchApi until the SDK release carries the
 * routes. Pass authToken in SSR (from Astro.cookies); omit it in the browser.
 */

import type { PlaybookItem } from "../playbooks";
import { fetchApi } from "./client";

const BASE = "/api/groups/playbooks";
const ENTRIES = "/api/platform/entries";

export interface PlaybookList {
  entryTypeId: string | null;
  items: PlaybookItem[];
}

export interface PlaybookEntry {
  id: string;
  slug: string;
  status: string;
  dataJson?: Record<string, unknown> | null;
}

export const listPlaybooks = (authToken?: string) => fetchApi<PlaybookList>(BASE, {}, authToken);

/** The `playbook` entry type's id, creating the type when this workspace has no Playbook yet. */
export const ensurePlaybookType = async (authToken?: string) =>
  (await fetchApi<{ entryTypeId: string }>(`${BASE}/type`, { method: "POST" }, authToken)).entryTypeId;

export const getPlaybook = (id: string, authToken?: string) => fetchApi<PlaybookEntry>(`${ENTRIES}/${encodeURIComponent(id)}`, {}, authToken);

export const createPlaybook = (payload: object) => fetchApi<PlaybookEntry>(ENTRIES, { method: "POST", body: JSON.stringify(payload) });

export const updatePlaybook = (id: string, payload: object) =>
  fetchApi<PlaybookEntry>(`${ENTRIES}/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(payload) });

/** To the Trash (restorable from the Trash page). */
export const trashPlaybook = (id: string) => fetchApi<unknown>(`${ENTRIES}/${encodeURIComponent(id)}`, { method: "DELETE" });
