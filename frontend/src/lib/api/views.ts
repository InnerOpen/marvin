import { fetchApi } from "./client";
import type { TimelineSpec } from "../timeline";

export interface ViewSummary {
  slug: string;
  name: string;
  /** How it draws the entry: `timeline` is the one kind so far. */
  kind: string;
  /** Slug of the entry type it is a view of. */
  entryType: string;
  package: string;
  packageName: string;
}

export interface ViewRead extends ViewSummary {
  definition: TimelineSpec;
}

/** The views this workspace's packages bring; `entryType` keeps only the views of that type (what an entry's page offers). */
export const listViews = (authToken: string, entryType?: string): Promise<ViewSummary[]> =>
  fetchApi<ViewSummary[]>(`/api/groups/views${entryType ? `?entry_type=${encodeURIComponent(entryType)}` : ""}`, {}, authToken);

/** One view with its definition, or null when there is none of that name. */
export async function getView(slug: string, authToken: string): Promise<ViewRead | null> {
  try {
    return await fetchApi<ViewRead>(`/api/groups/views/${encodeURIComponent(slug)}`, {}, authToken);
  } catch (e) {
    if (/404|No such view/i.test(e instanceof Error ? e.message : String(e))) return null;
    throw e;
  }
}

/** Where an entry opens in a view. */
export const viewHref = (view: string, entrySlug: string): string => `/workspace/views/${encodeURIComponent(view)}?entry=${encodeURIComponent(entrySlug)}`;
