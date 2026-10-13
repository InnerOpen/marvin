import type { APIRoute } from "astro";
import { getAuthToken } from "@/lib/api/client";
import { getApiUrl } from "@/lib/api/config";

export const GET: APIRoute = async ({ cookies }) => {
  const authToken = getAuthToken(cookies);
  if (!authToken) {
    return new Response(JSON.stringify({ error: "Unauthorized" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  }

  const backendUrl = getApiUrl("/api/platform/workspace/backup-key");
  const res = await fetch(backendUrl, {
    method: "GET",
    headers: { Authorization: `Bearer ${authToken}` },
  });

  const text = await res.text();
  return new Response(text, {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
};
