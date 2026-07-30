import type { APIRoute } from "astro";
import { getAuthToken } from "@/lib/api/client";
import { getApiUrl } from "@/lib/api/config";

// Same-origin proxy for manually triggering a system scheduled task. See ../index.ts for why
// client-side mutations must proxy through here rather than call the API directly.
export const POST: APIRoute = async ({ params, cookies }) => {
  const authToken = getAuthToken(cookies);
  if (!authToken) {
    return new Response(JSON.stringify({ error: "Unauthorized" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  }

  const id = params.id ?? "";
  const backendUrl = getApiUrl(`/api/admin/scheduled-tasks/${encodeURIComponent(id)}/execute`);
  const res = await fetch(backendUrl, {
    method: "POST",
    headers: { Authorization: `Bearer ${authToken}` },
  });

  const text = await res.text();
  return new Response(text, {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
};
