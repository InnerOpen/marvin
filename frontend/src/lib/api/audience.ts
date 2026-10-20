/**
 * Audience (routes/groups/audience_controller.py): the forms whose submissions go to the Audience, their submissions with the
 * spam verdict and source, and a person's actions on one (mark handled, not spam / reopen, delete). EDITOR and above. Plain
 * fetchApi until the SDK release carries them. Pass authToken in SSR (from Astro.cookies); omit it in the browser.
 */

import type { AudienceSummary, Submission } from "../audience";
import { fetchApi } from "./client";

const BASE = "/api/groups/audience";

export interface SubmissionList {
  items: Submission[];
  total: number;
  limit: number;
  offset: number;
  /** New plus suspicious for the form (or every form), whatever the other filters. */
  new: number;
}

export interface SubmissionResult {
  /** The submission afterwards; null once it is deleted (in the Trash). */
  submission: Submission | null;
}

export const getSummary = (authToken?: string) => fetchApi<AudienceSummary>(`${BASE}/summary`, {}, authToken);

export const listSubmissions = (query: string, authToken?: string) => fetchApi<SubmissionList>(`${BASE}/submissions?${query}`, {}, authToken);

export const markHandled = (id: string) => fetchApi<SubmissionResult>(`${BASE}/submissions/${id}/handled`, { method: "POST" });

export const reopen = (id: string) => fetchApi<SubmissionResult>(`${BASE}/submissions/${id}/reopen`, { method: "POST" });

export const remove = (id: string) => fetchApi<SubmissionResult>(`${BASE}/submissions/${id}`, { method: "DELETE" });
