/**
 * Automation results (routes/groups/automation_results_controller.py): the work Marvin handed to another system, whether it came
 * back, and what a person can do about a failure (retry, dismiss). Reading is EDITOR and above; retry and dismiss are ADMIN and
 * above (the summary's `can.act`). Plain fetchApi until the SDK release carries them. Pass authToken in SSR (from
 * Astro.cookies); omit it in the browser.
 */

import type { ResultConnection, ResultItem, ResultsSummary } from "../automationResults";
import { fetchApi } from "./client";

const BASE = "/api/groups/automation-results";

export interface ResultList {
  items: ResultItem[];
  total: number;
  limit: number;
  offset: number;
  /** The whole workspace's counts, whatever the filters (the tiles' numbers). */
  counts: ResultsSummary;
  /** Every connection that has a result: the connection filter's options. */
  connections: ResultConnection[];
}

export interface ResultOne {
  result: ResultItem;
}

export const getSummary = (authToken?: string) => fetchApi<ResultsSummary>(`${BASE}/summary`, {}, authToken);

export const listResults = (query: string, authToken?: string) => fetchApi<ResultList>(`${BASE}?${query}`, {}, authToken);

export const getResult = (id: string) => fetchApi<ResultOne>(`${BASE}/${id}`);

/** Run the hand-off step again. 409 (an ApiRequestError whose message is the reason) when it can't be done honestly. */
export const retry = (id: string) => fetchApi<ResultOne>(`${BASE}/${id}/retry`, { method: "POST" });

/** Mark a failure dealt with. */
export const dismiss = (id: string) => fetchApi<ResultOne>(`${BASE}/${id}/dismiss`, { method: "POST" });
