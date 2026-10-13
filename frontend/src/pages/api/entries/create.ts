import type { APIRoute } from "astro";
import { getAuthToken } from "@/lib/api/client";
import { createEntry } from "@/lib/api/entries";

export const POST: APIRoute = async ({ request, redirect, cookies }) => {
  try {
    const formData = await request.formData();
    const authToken = await getAuthToken(cookies);

    const entry = await createEntry(
      {
        entryTypeId: formData.get("entry_type_id") as string,
        title: formData.get("title") as string,
        // slug is auto-generated from title on the backend
        summary: (formData.get("summary") as string) || undefined,
        description: (formData.get("description") as string) || undefined,
        status: (formData.get("status") as string) || "draft",
      },
      authToken,
    );

    return redirect(`/workspace/entries/${entry.id}`, 303);
  } catch (error) {
    console.error("[entries/create] Error:", error);

    // Check for unique constraint violation
    if (
      error instanceof Error &&
      (error.message.includes("unique constraint") || error.message.includes("already exists"))
    ) {
      return new Response(
        JSON.stringify({
          error: "An entry with this slug already exists. Please choose a different title.",
        }),
        {
          status: 400,
          headers: { "Content-Type": "application/json" },
        },
      );
    }

    return new Response(JSON.stringify({ error: error instanceof Error ? error.message : "Failed to create entry" }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
};
