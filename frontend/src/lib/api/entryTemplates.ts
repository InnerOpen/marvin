/**
 * Filling entries with one of their type's templates (backend: services/entries/templates.py, POST
 * /entries/apply-template). The preview is the default and changes nothing; only empty values are filled unless
 * `replace`. Browser calls go through the same-origin proxy (fetchApi with no token); SSR passes the cookie token.
 */

import { fetchApi } from "./client";
import type { TemplatePreview } from "./workflowRuns";

export interface ApplyTemplateRequest {
  /** The entry type's slug or id. */
  entryType: string;
  /** The template's slug. */
  template: string;
  /** Entry ids or slugs, at most 200. */
  entries: string[];
  /** Overwrite the values the entries already have (off: only what is empty is filled). */
  replace?: boolean;
}

/** What the call answers: the preview's rows and counts and, once done, how many were filled. */
export interface ApplyTemplateResult extends TemplatePreview {
  preview: boolean;
  text: string;
  updated?: number;
  entryIds?: string[];
  /** With a picture preset: the background job treating the pictures still to be made. */
  treatmentJob?: string | null;
}

/** What applying the template would do to these entries (nothing is changed), or with `preview: false` do it. */
export async function applyTemplate(request: ApplyTemplateRequest, preview: boolean, authToken?: string): Promise<ApplyTemplateResult> {
  return fetchApi<ApplyTemplateResult>(
    "/api/platform/entries/apply-template",
    { method: "POST", body: JSON.stringify({ ...request, replace: request.replace === true, preview }) },
    authToken,
  );
}
