import type { APIRoute } from "astro";
import { getAuthToken } from "@/lib/api/client";
import { activateWorkspace, createWorkspace } from "@/lib/api/workspaces";

export const POST: APIRoute = async ({ request, redirect, cookies }) => {
  try {
    const formData = await request.formData();
    const authToken = await getAuthToken(cookies);

    const workspace = await createWorkspace(
      {
        name: formData.get("name") as string,
      },
      authToken,
    );

    // Auto-activate the new workspace
    await activateWorkspace(workspace.id, authToken);

    return redirect("/", 303);
  } catch (error) {
    console.error("[workspaces/create] Error:", error);
    return new Response(
      JSON.stringify({ error: error instanceof Error ? error.message : "Failed to create workspace" }),
      {
        status: 500,
        headers: { "Content-Type": "application/json" },
      },
    );
  }
};
