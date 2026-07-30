import type { APIRoute } from "astro";
import { getAuthToken } from "@/lib/api/client";
import { getApiUrl } from "@/lib/api/config";

// Same-origin proxy for creating a system scheduled task. Client-side mutations must go through
// here (not the SDK direct-to-API): the auth cookie is httpOnly, so browser JS can't read it, and
// it is scoped to the frontend origin, so it wouldn't reach the API origin cross-origin either.
export const POST: APIRoute = async ({ request, cookies }) => {
  const authToken = getAuthToken(cookies);
  if (!authToken) {
    return new Response(JSON.stringify({ error: "Unauthorized" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  }

  const body = await request.text();
  const backendUrl = getApiUrl("/api/admin/scheduled-tasks");
  const res = await fetch(backendUrl, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${authToken}`,
      "Content-Type": "application/json",
    },
    body,
  });

  const text = await res.text();
  return new Response(text, {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
};
