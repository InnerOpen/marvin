/**
 * The web app manifest that makes the admin installable (lib/pwa.ts buildManifest). Served per request, not
 * as a static file, because a non-production instance (ENVIRONMENT_LABEL) installs under its own name, icons
 * and colour. No auth: it holds nothing but the app's name and icons.
 */
import type { APIRoute } from "astro";

import { getEnvironmentLabel } from "@/lib/environmentLabel";
import { buildManifest } from "@/lib/pwa";

export const GET: APIRoute = async () =>
  new Response(JSON.stringify(buildManifest(await getEnvironmentLabel())), {
    status: 200,
    headers: { "content-type": "application/manifest+json; charset=utf-8", "cache-control": "no-cache" },
  });
