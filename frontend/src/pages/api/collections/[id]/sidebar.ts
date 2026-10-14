import type { APIRoute } from "astro";
import { getAuthToken } from "@/lib/api/client";
import { type CollectionUpdate, updateCollection } from "@/lib/api/collections";

/** The Collections page's "Sidebar" switch: `{ inSidebar: boolean }` → PATCH the collection's `in_sidebar`. */
export const POST: APIRoute = async ({ params, request, cookies }) => {
  const authToken = getAuthToken(cookies);
  if (!authToken) return new Response("Unauthorized", { status: 401 });
  const body = await request.json().catch(() => null);
  if (!params.id || typeof body?.inSidebar !== "boolean") {
    return new Response(JSON.stringify({ error: "Expected { inSidebar: boolean }" }), { status: 400, headers: { "Content-Type": "application/json" } });
  }
  try {
    const updated = await updateCollection(params.id, { inSidebar: body.inSidebar } as CollectionUpdate, authToken);
    return new Response(JSON.stringify(updated), { status: 200, headers: { "Content-Type": "application/json" } });
  } catch (error) {
    console.error("[collections/sidebar] Error:", error);
    return new Response(JSON.stringify({ error: error instanceof Error ? error.message : "Failed to update collection" }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
};
