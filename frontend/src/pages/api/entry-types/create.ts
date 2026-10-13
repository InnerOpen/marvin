import type { APIRoute } from "astro";
import { getAuthToken } from "@/lib/api/client";
import { createEntryType } from "@/lib/api/entryTypes";

export const POST: APIRoute = async ({ request, redirect, cookies }) => {
  try {
    const formData = await request.formData();
    const authToken = await getAuthToken(cookies);

    // Parse JSON fields if provided
    const parseJson = (field: string) => {
      const raw = formData.get(field) as string;
      if (!raw) return undefined;
      try {
        return JSON.parse(raw);
      } catch (e) {
        console.error(`[entry-types/create] Invalid ${field}:`, e);
        return undefined;
      }
    };

    await createEntryType(
      {
        name: formData.get("name") as string,
        icon: (formData.get("icon") as string) || undefined,
        color: (formData.get("color") as string) || undefined,
        description: (formData.get("description") as string) || undefined,
        sortOrder: parseInt(formData.get("sort_order") as string, 10) || 0,
        isRendered: formData.get("is_rendered") === "on",
        schemaJson: parseJson("schema_json"),
        renderingJson: parseJson("rendering_json"),
        capabilitiesJson: parseJson("capabilities_json"),
        recipeJson: parseJson("recipe_json"),
        pageUrlPattern: ((formData.get("page_url_pattern") as string) || "").trim() || undefined,
      },
      authToken,
    );

    return redirect("/workspace/entry-types", 303);
  } catch (error) {
    console.error("[entry-types/create] Error:", error);
    return new Response(
      JSON.stringify({ error: error instanceof Error ? error.message : "Failed to create entry type" }),
      {
        status: 500,
        headers: { "Content-Type": "application/json" },
      },
    );
  }
};
