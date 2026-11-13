/**
 * Authentication utilities for Astro pages
 */

import type { UserProfile } from "@inneropen/marvin-sdk/platform";
import type { AstroCookies } from "astro";
import { getAuthToken } from "./api/client";
import { readProfile } from "./api/self";
import type { RequestScope } from "./requestCache";

export type User = UserProfile;

/**
 * Check if user is authenticated and get current user data
 * @param cookies - Astro cookies object
 * @param scope - The page's `Astro.locals`, so the request asks the API once (lib/api/self.ts)
 * @returns User data if authenticated, null otherwise
 */
async function getCurrentUser(cookies: AstroCookies, scope?: RequestScope): Promise<User | null> {
  const token = getAuthToken(cookies);

  if (!token) {
    return null;
  }

  try {
    return await readProfile(token, scope);
  } catch (_error) {
    return null;
  }
}

/**
 * Require authentication - redirect to login if not authenticated
 * Use this at the top of protected pages
 *
 * @param cookies - Astro cookies object
 * @param redirect - Astro redirect function
 * @param currentPath - Current page path (for redirect after login)
 * @param scope - The page's `Astro.locals` (the signed-in user is read once per request)
 * @returns User data if authenticated, never returns if not authenticated
 *
 * @example
 * ```astro
 * ---
 * import { requireAuth } from '@/lib/auth';
 * const user = await requireAuth(Astro.cookies, Astro.redirect, Astro.url.pathname, Astro.locals);
 * ---
 * ```
 */
export async function requireAuth(
  cookies: AstroCookies,
  redirect: (path: string) => Response,
  currentPath?: string,
  scope?: RequestScope,
): Promise<User> {
  const user = await getCurrentUser(cookies, scope);

  if (!user) {
    const loginUrl = currentPath && currentPath !== "/" ? `/login?return=${encodeURIComponent(currentPath)}` : "/login";

    throw redirect(loginUrl);
  }

  return user;
}

/**
 * Require admin authentication - redirect to home if not admin
 *
 * @param cookies - Astro cookies object
 * @param redirect - Astro redirect function
 * @param currentPath - Current page path (for redirect after login)
 * @param scope - The page's `Astro.locals` (the signed-in user is read once per request)
 * @returns User data if authenticated admin, never returns otherwise
 *
 * @example
 * ```astro
 * ---
 * import { requireAdmin } from '@/lib/auth';
 * const user = await requireAdmin(Astro.cookies, Astro.redirect, Astro.url.pathname, Astro.locals);
 * ---
 * ```
 */
export async function requireAdmin(
  cookies: AstroCookies,
  redirect: (path: string) => Response,
  currentPath?: string,
  scope?: RequestScope,
): Promise<User> {
  const user = await requireAuth(cookies, redirect, currentPath, scope);

  // Platform admin section = the SUPER_ADMIN platform role, NOT the legacy `admin` boolean
  // (which marks workspace-level admins). A workspace ADMIN administers its workspace, not the platform.
  if (user.platformRole !== "SUPER_ADMIN" && !user.isSuperuser) {
    throw redirect("/");
  }

  return user;
}

/**
 * Check if user is authenticated (returns boolean)
 * Use this for conditional rendering or optional auth
 *
 * @param cookies - Astro cookies object
 * @returns true if authenticated, false otherwise
 */
export async function isAuthenticated(cookies: AstroCookies): Promise<boolean> {
  const user = await getCurrentUser(cookies);
  return user !== null;
}
