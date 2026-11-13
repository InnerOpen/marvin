/**
 * Theme API
 * Migrated to use @inneropen/marvin-sdk
 */

import type { AppTheme } from "@inneropen/marvin-sdk/platform";
import { type RequestScope, readOnce } from "../requestCache";
import { createSdkClient } from "../sdk";

export type { AppTheme };

/**
 * Get application theme colors; `scope` (the page's `Astro.locals`) reads them once per request.
 */
export async function getTheme(authToken: string, scope?: RequestScope): Promise<AppTheme> {
  return readOnce(scope, "/api/app/about/theme", authToken, () => createSdkClient(authToken).theme.getTheme());
}
