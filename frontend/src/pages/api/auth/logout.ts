/**
 * Logout endpoint - clears authentication cookie
 */

import type { APIRoute } from "astro";
import { getCookieName } from "@/lib/api/config";

export const POST: APIRoute = async ({ cookies, redirect }) => {
  // Delete the access token cookie
  cookies.delete(getCookieName(), {
    path: "/",
  });

  // Redirect to login page
  return redirect("/login", 303);
};
