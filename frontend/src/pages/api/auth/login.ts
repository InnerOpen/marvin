/**
 * Login endpoint - proxies authentication to backend API
 */

import type { APIRoute } from "astro";
import { getCookieName, getCookieSecure, getServerApiBaseUrl } from "@/lib/api/config";
import { cookieMaxAge, safeReturnPath } from "@/lib/session";

export const POST: APIRoute = async ({ request, cookies, redirect, url, clientAddress }) => {
  try {
    const formData = await request.formData();
    const username = formData.get("username");
    const password = formData.get("password");

    // Get return path from query param
    const returnPath = safeReturnPath(url.searchParams.get("return"));

    if (!username || !password) {
      const loginError =
        returnPath !== "/" ? `/login?error=missing&return=${encodeURIComponent(returnPath)}` : "/login?error=missing";
      return redirect(loginError, 303);
    }

    const backendUrl = `${getServerApiBaseUrl()}/api/auth/token`;

    // Call backend /api/auth/token endpoint
    const response = await fetch(backendUrl, {
      method: "POST",
      // Who is signing in, for the backend's per-IP throttling: Cloudflare's CF-Connecting-IP when the request came
      // through it (a caller can't set it), else the socket's address. Without these every sign-in would look like it
      // came from this server, and one IP's failures would throttle everyone.
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        ...clientIpHeaders(request, clientAddress),
      },
      body: new URLSearchParams({
        username: username.toString(),
        password: password.toString(),
      }),
    });

    if (response.status === 429) {
      // Too many failures for this account or IP: say for how long (the backend's Retry-After, in seconds).
      const minutes = Math.max(1, Math.ceil(Number(response.headers.get("retry-after") || 60) / 60));
      const back = returnPath !== "/" ? `&return=${encodeURIComponent(returnPath)}` : "";
      return redirect(`/login?error=throttled&minutes=${minutes}${back}`, 303);
    }

    if (!response.ok) {
      console.error("[auth/login] Backend auth failed:", response.status);
      const loginError =
        returnPath !== "/" ? `/login?error=invalid&return=${encodeURIComponent(returnPath)}` : "/login?error=invalid";
      return redirect(loginError, 303);
    }

    const data = await response.json();
    const accessToken = data.access_token;

    if (!accessToken) {
      console.error("[auth/login] No access token in response");
      const loginError =
        returnPath !== "/" ? `/login?error=invalid&return=${encodeURIComponent(returnPath)}` : "/login?error=invalid";
      return redirect(loginError, 303);
    }

    // Set the access token cookie (matching backend format)
    cookies.set(getCookieName(), accessToken, {
      path: "/",
      httpOnly: true,
      secure: getCookieSecure(), // HTTPS deploys secure; HTTP (homelab NodePort) must not, or the cookie is dropped
      sameSite: "lax",
      maxAge: cookieMaxAge(accessToken), // as long as the token itself: a dead token in a live cookie fails every page
    });

    // Successfully logged in, redirect to requested page or dashboard
    return redirect(returnPath, 303);
  } catch (error) {
    console.error("[auth/login] Error:", error);
    const returnPath = safeReturnPath(new URL(request.url).searchParams.get("return"));
    const loginError =
      returnPath !== "/" ? `/login?error=server&return=${encodeURIComponent(returnPath)}` : "/login?error=server";
    return redirect(loginError, 303);
  }
};

/** The signing-in client's address for the backend: Cloudflare's header passed on as is, and X-Forwarded-For. */
function clientIpHeaders(request: Request, clientAddress: string | undefined): Record<string, string> {
  const headers: Record<string, string> = {};
  const cf = request.headers.get("cf-connecting-ip");
  if (cf) headers["CF-Connecting-IP"] = cf;
  let socket: string | undefined;
  try {
    socket = clientAddress;
  } catch {
    // Astro throws when the adapter can't tell the address: then only Cloudflare's header (if any) goes.
  }
  const forwarded = cf || socket;
  if (forwarded) headers["X-Forwarded-For"] = forwarded;
  return headers;
}
