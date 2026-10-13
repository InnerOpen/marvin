import type { APIRoute } from "astro";
import { getAuthToken } from "@/lib/api/client";
import { deleteEntryType } from "@/lib/api/entryTypes";

export const POST: APIRoute = async ({ params, redirect, cookies }) => {
  try {
    const { id } = params;
    if (!id) throw new Error("Entry type ID required");

    const authToken = await getAuthToken(cookies);
    await deleteEntryType(id, authToken);
    return redirect("/workspace/entry-types", 303);
  } catch (error) {
    console.error("[entry-types/delete] Error:", error);
    return new Response(
      JSON.stringify({ error: error instanceof Error ? error.message : "Failed to delete entry type" }),
      {
        status: 500,
        headers: { "Content-Type": "application/json" },
      },
    );
  }
};
