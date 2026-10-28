/**
 * Playbooks (routes/groups/playbooks_controller.py): the list with each Playbook's status, and the entry type's creation on first
 * write. EDITOR and above. A Playbook itself is read and saved through the entries API (`/api/platform/entries`), the same one the
 * entry editor uses, so its history, Trash and role rules are the entries' own. Plain fetchApi until the SDK release carries the
 * routes. Pass authToken in SSR (from Astro.cookies); omit it in the browser.
 */

import { exportFilename, type PlaybookItem, type PlaybookUse, type SystemPlaybookItem, type SystemPlaybookRead } from "../playbooks";
import { fetchApi } from "./client";
import { getApiUrl } from "./config";

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
  /** An imported Playbook keeps its review here (`importReview`, lib/playbookReview.ts). */
  metadataJson?: Record<string, unknown> | null;
}

export const listPlaybooks = (authToken?: string) => fetchApi<PlaybookList>(BASE, {}, authToken);

/** The `playbook` entry type's id, creating the type when this workspace has no Playbook yet. */
export const ensurePlaybookType = async (authToken?: string) =>
  (await fetchApi<{ entryTypeId: string }>(`${BASE}/type`, { method: "POST" }, authToken)).entryTypeId;

/** The runs that loaded this Playbook lately, newest first. */
export const listPlaybookUses = async (id: string, authToken?: string) =>
  (await fetchApi<{ items: PlaybookUse[] }>(`${BASE}/${encodeURIComponent(id)}/uses`, {}, authToken)).items;

export interface PlaybookFileText {
  path: string;
  size: number;
  text?: string | null;
  truncated?: boolean;
  error?: string | null;
}

/** A Playbook's reference files with their text (EDITOR+, any status): read-only, for reading before publishing. */
export const listPlaybookFiles = async (id: string, authToken?: string) =>
  (await fetchApi<{ items: PlaybookFileText[] }>(`${BASE}/${encodeURIComponent(id)}/files`, {}, authToken)).items;

export const getPlaybook = (id: string, authToken?: string) => fetchApi<PlaybookEntry>(`${ENTRIES}/${encodeURIComponent(id)}`, {}, authToken);

export const createPlaybook = (payload: object) => fetchApi<PlaybookEntry>(ENTRIES, { method: "POST", body: JSON.stringify(payload) });

export const updatePlaybook = (id: string, payload: object) =>
  fetchApi<PlaybookEntry>(`${ENTRIES}/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(payload) });

/** To the Trash (restorable from the Trash page). */
export const trashPlaybook = (id: string) => fetchApi<unknown>(`${ENTRIES}/${encodeURIComponent(id)}`, { method: "DELETE" });

export interface PlaybookImported {
  id: string;
  name: string;
  status: string;
  fileCount: number;
  skipped: { path: string; reason: string }[];
}

/** Import a SKILL.md or a skill zip as a draft Playbook (EDITOR+). `name` picks another name when the file's is taken. */
export function importPlaybook(file: File, name?: string) {
  const body = new FormData();
  body.append("file", file);
  if (name) body.append("name", name);
  return fetchApi<PlaybookImported>(`${BASE}/import`, { method: "POST", body });
}

/** Download a Playbook as a skill folder zip (EDITOR+, any status). Browser only: it saves the file through a temporary link. */
export async function exportPlaybook(id: string, name: string) {
  const response = await fetch(getApiUrl(`${BASE}/${encodeURIComponent(id)}/export`), { credentials: "include" });
  if (!response.ok) throw new Error(response.status === 404 ? "This Playbook no longer exists." : "The export failed. Try again.");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(await response.blob());
  link.download = exportFilename(response.headers.get("Content-Disposition"), name);
  link.click();
  URL.revokeObjectURL(link.href);
}

/** Import a skill from a public GitHub link as a draft Playbook (EDITOR+): the link is pinned to the commit it names now. */
export function importPlaybookFromGithub(url: string, name?: string) {
  return fetchApi<PlaybookImported>(`${BASE}/import-github`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(name ? { url, name } : { url }),
  });
}

// ── system Playbooks (shipped by Marvin and its plugins; read-only) ─────────────────────────────────────────────────

/** The system Playbooks with whether this workspace gets each (EDITOR+). Includes the ones switched off. */
export const listSystemPlaybooks = async (authToken?: string) =>
  (await fetchApi<{ items: SystemPlaybookItem[] }>(`${BASE}/system`, {}, authToken)).items;

export const getSystemPlaybook = (name: string, authToken?: string) =>
  fetchApi<SystemPlaybookRead>(`${BASE}/system/${encodeURIComponent(name)}`, {}, authToken);

/** The runs that loaded a system Playbook lately, newest first. */
export const listSystemPlaybookUses = async (name: string, authToken?: string) =>
  (await fetchApi<{ items: PlaybookUse[] }>(`${BASE}/system/${encodeURIComponent(name)}/uses`, {}, authToken)).items;

/** Switch a system Playbook on or off for this workspace (ADMIN+). */
export const switchSystemPlaybook = (name: string, enabled: boolean) =>
  fetchApi<SystemPlaybookItem>(`${BASE}/system/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify({ enabled }) });

/** Copy a system Playbook into a draft of this workspace's own (ADMIN+). `name` picks the copy's name; the suggestion otherwise. */
export const copySystemPlaybook = (name: string, copyName?: string) =>
  fetchApi<PlaybookImported>(`${BASE}/system/${encodeURIComponent(name)}/copy`, {
    method: "POST",
    body: JSON.stringify(copyName ? { name: copyName } : {}),
  });

/** Mark a copy's changed original as seen (ADMIN+): its hint goes until the original changes again. */
export const markUpstreamSeen = (id: string) => fetchApi<unknown>(`${BASE}/${encodeURIComponent(id)}/upstream-seen`, { method: "POST" });
