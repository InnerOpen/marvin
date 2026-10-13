import type { APIRoute } from "astro";
import { getAuthToken } from "@/lib/api/client";
import { createCollection } from "@/lib/api/collections";

export const POST: APIRoute = async ({ request, redirect, cookies }) => {
  try {
    const authToken = getAuthToken(cookies);
    if (!authToken) {
      return new Response("Unauthorized", { status: 401 });
    }

    const formData = await request.formData();

    await createCollection(
      {
        name: formData.get("name") as string,
        // slug is auto-generated from name on the backend
        icon: (formData.get("icon") as string) || null,
        color: (formData.get("color") as string) || null,
        description: (formData.get("description") as string) || null,
        sortOrder: parseInt(formData.get("sort_order") as string, 10) || 0,
        isSmart: formData.get("is_smart") === "true",
      },
      authToken,
    );

    return redirect("/collections", 303);
  } catch (error) {
    console.error("[collections/create] Error:", error);
    return new Response(
      JSON.stringify({ error: error instanceof Error ? error.message : "Failed to create collection" }),
      {
        status: 500,
        headers: { "Content-Type": "application/json" },
      },
    );
  }
};
