import type { APIRoute } from "astro";
import { rejectAssetSuggestion } from "@/lib/api/assets";
import { getAuthToken } from "@/lib/api/client";

export const POST: APIRoute = async ({ params, cookies }) => {
  try {
    const { id } = params;
    if (!id) return new Response("Asset ID required", { status: 400 });
    const authToken = await getAuthToken(cookies);
    if (!authToken) return new Response("Unauthorized", { status: 401 });

    const result = await rejectAssetSuggestion(id, authToken);
    return new Response(JSON.stringify(result), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    console.error("[assets/reject-suggestion] Error:", error);
    return new Response(
      JSON.stringify({ error: error instanceof Error ? error.message : "Failed to reject suggestion" }),
      { status: 500, headers: { "Content-Type": "application/json" } },
    );
  }
};
