import type { APIRoute } from "astro";
import { getAuthToken } from "@/lib/api/client";
import { getApiUrl } from "@/lib/api/config";

export const GET: APIRoute = async ({ params, cookies }) => {
  const authToken = getAuthToken(cookies);
  if (!authToken) {
    return new Response(JSON.stringify({ error: "Unauthorized" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  }

  const filename = params.filename ?? "";
  const backendUrl = getApiUrl(`/api/admin/backups/${encodeURIComponent(filename)}`);
  const res = await fetch(backendUrl, {
    headers: { Authorization: `Bearer ${authToken}` },
  });

  if (!res.ok) {
    const text = await res.text();
    return new Response(text, { status: res.status, headers: { "Content-Type": "application/json" } });
  }

  const contentDisposition = res.headers.get("Content-Disposition") ?? `attachment; filename="${filename}"`;
  return new Response(res.body, {
    status: 200,
    headers: {
      "Content-Type": "application/zip",
      "Content-Disposition": contentDisposition,
    },
  });
};
