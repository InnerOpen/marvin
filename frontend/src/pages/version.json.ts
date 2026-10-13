/**
 * The live version pair (frontend build, backend version). Open tabs poll this and compare it
 * with the pair they were rendered with; a difference means a deploy landed and a reload is due.
 * No auth: it reveals a commit hash and a version string, both already public in the image tags.
 */
import type { APIRoute } from "astro";

import { getAppVersion } from "@/lib/version";

export const GET: APIRoute = async () =>
  new Response(JSON.stringify(await getAppVersion()), {
    status: 200,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
