/**
 * OIDC callback endpoint - receives JWT from backend OIDC flow,
 * validates it, sets the session cookie, and redirects to the app.
 */

import type { APIRoute } from "astro";
import { getCookieName, getCookieSecure } from "@/lib/api/config";
import { createSdkClient } from "@/lib/sdk";
import { cookieMaxAge } from "@/lib/session";

export const GET: APIRoute = async ({ url, cookies, redirect }) => {
  const token = url.searchParams.get("token");

  if (!token) {
    return redirect("/login?error=oidc", 303);
  }

  try {
    const sdk = createSdkClient(token);
    await sdk.user.getProfile();
  } catch {
    return redirect("/login?error=oidc", 303);
  }

  cookies.set(getCookieName(), token, {
    path: "/",
    httpOnly: true,
    secure: getCookieSecure(), // HTTPS deploys secure; HTTP (homelab NodePort) must not, or the cookie is dropped
    sameSite: "lax",
    maxAge: cookieMaxAge(token), // as long as the token itself (lib/session.ts)
  });

  return redirect("/", 303);
};
