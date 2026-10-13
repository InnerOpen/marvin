import type { APIRoute } from "astro";
import { getAuthToken } from "@/lib/api/client";
import { reorderCollections } from "@/lib/api/collections";

export const POST: APIRoute = async ({ request, cookies }) => {
  try {
    const authToken = getAuthToken(cookies);
    if (!authToken) {
      return new Response("Unauthorized", { status: 401 });
    }

    const body = await request.json();
    const order = body?.order;
    if (!Array.isArray(order)) {
      return new Response(JSON.stringify({ error: "Expected { order: [{ id, sortOrder }] }" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    const result = await reorderCollections(order, authToken);
    return new Response(JSON.stringify(result), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    console.error("[collections/reorder] Error:", error);
    return new Response(
      JSON.stringify({ error: error instanceof Error ? error.message : "Failed to reorder collections" }),
      { status: 500, headers: { "Content-Type": "application/json" } },
    );
  }
};
