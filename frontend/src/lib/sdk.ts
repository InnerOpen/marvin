/**
 * Marvin SDK Factory for Frontend
 *
 * Creates Platform API clients for use in both SSR and browser contexts.
 * The SDK handles all HTTP communication, retry logic, and error handling.
 *
 * ## Authentication Modes
 *
 * The SDK supports two authentication modes:
 *
 * ### 1. Browser Cookie Auth (Admin UI, SSR pages)
 * - Backend sets `marvin.access_token` as HttpOnly cookie
 * - JavaScript cannot and should not read this token (security feature)
 * - Browser sends cookie automatically when `credentials: 'include'` is set
 * - Usage: `const sdk = createSdkClient()` (no token needed)
 *
 * ### 2. Explicit Token Auth (CLI, server-side tools, scripts)
 * - Token comes from environment variable, CLI credentials file, or explicit config
 * - Sets `Authorization: Bearer <token>` header
 * - Usage: `const sdk = createSdkClient(authToken)`
 *
 * **Important:** Never try to read an HttpOnly cookie from JavaScript.
 * If authToken is provided, the SDK uses Bearer auth.
 * If authToken is not provided, the SDK relies on cookie-based auth with credentials: 'include'.
 */

import type { PlatformClient } from "@inneropen/marvin-sdk/platform";
import { createPlatformClient } from "@inneropen/marvin-sdk/platform";
import { getApiUrl } from "./api/config";

/**
 * Create a Platform API client
 *
 * @param authToken - Optional authentication token. If not provided, relies on HttpOnly cookies.
 * @returns Configured Platform API client
 *
 * @example
 * ```typescript
 * // Browser/Admin UI (cookie-based auth):
 * import { createSdkClient } from '../lib/sdk';
 * const sdk = createSdkClient(); // No token - uses HttpOnly cookie
 * const entries = await sdk.entries.list();
 *
 * // SSR context (with explicit token from SSR cookies):
 * import { getAuthToken } from '../lib/api/client';
 * const authToken = getAuthToken(Astro.cookies);
 * const sdk = createSdkClient(authToken);
 *
 * // CLI/Server (with explicit token):
 * const sdk = createSdkClient(process.env.MARVIN_TOKEN);
 * ```
 */
export function createSdkClient(authToken?: string): PlatformClient {
  // Get base API URL (strip any trailing path)
  const apiUrl = getApiUrl("");
  const baseUrl = (typeof apiUrl === "string" ? apiUrl : apiUrl.toString()).replace(/\/+$/, "");

  return createPlatformClient({
    apiUrl: baseUrl,
    userToken: authToken,
    credentials: "include", // Always include cookies for HttpOnly session auth
  });
}
