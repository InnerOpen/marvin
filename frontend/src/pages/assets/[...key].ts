import type { APIRoute } from "astro";
import { getServerApiBaseUrl } from "@/lib/api/config";

// Serve stored media through the frontend instead of pointing browsers at the backend.
//
// With local storage the backend serves files at /assets/*, and AssetRead.public_url is a relative
// "/assets/{key}" — which the browser resolves against the page's origin, i.e. the frontend. So the
// frontend has to serve /assets/*. It proxies to the backend over the server-side API URL
// (getServerApiBaseUrl → MARVIN_API_URL), which in split mode is the in-cluster backend Service, so
// the backend never needs a public route. For S3 storage public_url is an absolute S3 URL, the
// browser goes straight there, and this route is simply never hit.
export const prerender = false;

// Forwarded so range requests (video seeking, large images) stream as partial content instead of
// buffering the whole file.
const REQUEST_PASSTHROUGH = ["range", "if-none-match", "if-modified-since", "accept"];
const RESPONSE_PASSTHROUGH = [
  "content-type",
  "content-length",
  "content-range",
  "accept-ranges",
  "cache-control",
  "etag",
  "last-modified",
];

export const GET: APIRoute = async ({ params, request }) => {
  const key = params.key ?? "";
  if (!key) {
    return new Response("Not found", { status: 404 });
  }

  // The key is already URL-safe path segments from the router; encode each so a stray space or #
  // in a filename doesn't break the upstream URL, while keeping the slashes.
  const encoded = key
    .split("/")
    .map((s) => encodeURIComponent(s))
    .join("/");
  const upstreamUrl = `${getServerApiBaseUrl()}/assets/${encoded}`;

  const headers = new Headers();
  for (const h of REQUEST_PASSTHROUGH) {
    const v = request.headers.get(h);
    if (v) headers.set(h, v);
  }

  let upstream: Response;
  try {
    upstream = await fetch(upstreamUrl, { headers });
  } catch (e) {
    console.error(`[assets] upstream fetch failed for ${key}:`, e);
    return new Response("Bad gateway", { status: 502 });
  }

  const outHeaders = new Headers();
  for (const h of RESPONSE_PASSTHROUGH) {
    const v = upstream.headers.get(h);
    if (v) outHeaders.set(h, v);
  }

  // Stream the body straight through — never buffer a media file into memory.
  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: outHeaders,
  });
};

export const HEAD = GET;
