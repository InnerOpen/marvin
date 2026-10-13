import type { APIRoute } from "astro";
import { getAuthToken } from "@/lib/api/client";
import { createSdkClient } from "@/lib/sdk";

export const POST: APIRoute = async ({ params, redirect, cookies }) => {
  try {
    const authToken = getAuthToken(cookies);
    if (!authToken) return new Response("Unauthorized", { status: 401 });
    const { id } = params;
    if (!id) throw new Error("Asset ID required");

    const sdk = createSdkClient(authToken);
    await sdk.assets.delete(id);
    return redirect("/workspace/assets", 303);
  } catch (error) {
    console.error("[assets/delete] Error:", error);
    return new Response(JSON.stringify({ error: error instanceof Error ? error.message : "Failed to delete asset" }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
};
