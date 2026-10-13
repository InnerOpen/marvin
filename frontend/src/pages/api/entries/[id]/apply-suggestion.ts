import type { APIRoute } from "astro";
import { getAuthToken } from "@/lib/api/client";
import { applyEntrySuggestion } from "@/lib/api/entries";

export const POST: APIRoute = async ({ params, cookies }) => {
  try {
    const { id } = params;
    if (!id) return new Response("Entry ID required", { status: 400 });
    const authToken = await getAuthToken(cookies);
    if (!authToken) return new Response("Unauthorized", { status: 401 });

    const entry = await applyEntrySuggestion(id, authToken);
    return new Response(JSON.stringify(entry), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    console.error("[entries/apply-suggestion] Error:", error);
    return new Response(
      JSON.stringify({ error: error instanceof Error ? error.message : "Failed to apply suggestion" }),
      { status: 500, headers: { "Content-Type": "application/json" } },
    );
  }
};
