import type { APIRoute } from "astro";
import { getAuthToken } from "@/lib/api/client";
import { getServerApiBaseUrl } from "@/lib/api/config";

/**
 * Catch-all same-origin proxy for browser API calls.
 *
 * The whole admin UI is standardized on the proxy pattern (see lib/api/config.ts getApiBaseUrl):
 * in the browser the SDK targets this frontend's own origin, so every `/api/*` call it makes that
 * isn't handled by a more specific route (Astro matches specific routes before this spread route)
 * lands here. We read the httpOnly session cookie server-side and forward it to the backend as a
 * Bearer token. Being same-origin, this is immune to the split UI/API problem where the host-only
 * session cookie never reaches a separate API host.
 *
 * The forward is transparent: method, query string, request/response bodies (streamed, so multipart
 * uploads and binary downloads pass through), and content-type/disposition are preserved.
 */

// Headers that are connection-specific and must not be forwarded verbatim.
const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
]);

// Response headers worth passing back to the browser.
const PASS_RESPONSE_HEADERS = ["content-type", "content-disposition", "cache-control", "etag", "last-modified", "location"];

const proxy: APIRoute = async ({ request, params, cookies }) => {
  const path = params.path ?? "";
  const search = new URL(request.url).search;
  const backendUrl = `${getServerApiBaseUrl()}/api/${path}${search}`;

  const headers = new Headers();
  for (const [key, value] of request.headers) {
    const lower = key.toLowerCase();
    // Drop the cookie (translated to a Bearer token below) and any inbound Authorization; forward
    // everything else so the backend sees the real Accept, Content-Type, boundary, etc.
    if (HOP_BY_HOP.has(lower) || lower === "cookie" || lower === "authorization") continue;
    headers.set(key, value);
  }

  const authToken = getAuthToken(cookies);
  if (authToken) headers.set("Authorization", `Bearer ${authToken}`);

  const method = request.method.toUpperCase();
  const hasBody = method !== "GET" && method !== "HEAD";

  const init: RequestInit & { duplex?: "half" } = {
    method,
    headers,
    redirect: "manual",
  };
  if (hasBody) {
    init.body = request.body;
    init.duplex = "half"; // required by undici when streaming a request body
  }

  const res = await fetch(backendUrl, init);

  const responseHeaders = new Headers();
  for (const name of PASS_RESPONSE_HEADERS) {
    const value = res.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }

  return new Response(res.body, { status: res.status, headers: responseHeaders });
};

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const HEAD = proxy;
