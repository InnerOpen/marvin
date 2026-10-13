import type { APIRoute } from "astro";
import { getAuthToken } from "@/lib/api/client";
import { updateCollection } from "@/lib/api/collections";

export const POST: APIRoute = async ({ params, request, redirect, cookies }) => {
  try {
    const { id } = params;
    if (!id) throw new Error("Collection ID required");

    const formData = await request.formData();
    const authToken = await getAuthToken(cookies);

    await updateCollection(
      id,
      {
        name: formData.get("name") as string,
        // slug is auto-regenerated from name on the backend
        icon: (formData.get("icon") as string) || null,
        color: (formData.get("color") as string) || null,
        description: (formData.get("description") as string) || null,
        sortOrder: parseInt(formData.get("sort_order") as string, 10) || 0,
      },
      authToken,
    );

    return redirect(`/collections/${id}`, 303);
  } catch (error) {
    console.error("[collections/update] Error:", error);
    return new Response(
      JSON.stringify({ error: error instanceof Error ? error.message : "Failed to update collection" }),
      {
        status: 500,
        headers: { "Content-Type": "application/json" },
      },
    );
  }
};
