import type { APIRoute } from "astro";
import { getAuthToken } from "@/lib/api/client";
import { updateEntryType } from "@/lib/api/entryTypes";

export const POST: APIRoute = async ({ params, request, redirect, cookies }) => {
  try {
    const { id } = params;
    if (!id) throw new Error("Entry type ID required");

    const formData = await request.formData();
    const authToken = await getAuthToken(cookies);

    // Parse JSON fields if provided
    const parseJson = (field: string) => {
      const raw = formData.get(field) as string;
      if (!raw) return undefined;
      try {
        return JSON.parse(raw);
      } catch (e) {
        console.error(`[entry-types/update] Invalid ${field}:`, e);
        return undefined;
      }
    };

    await updateEntryType(
      id,
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
        // Blank clears the pattern (null), unlike the optional fields above that keep their value.
        pageUrlPattern: formData.has("page_url_pattern")
          ? ((formData.get("page_url_pattern") as string) || "").trim() || null
          : undefined,
      },
      authToken,
    );

    return redirect("/workspace/entry-types", 303);
  } catch (error) {
    console.error("[entry-types/update] Error:", error);
    return new Response(
      JSON.stringify({ error: error instanceof Error ? error.message : "Failed to update entry type" }),
      {
        status: 500,
        headers: { "Content-Type": "application/json" },
      },
    );
  }
};
