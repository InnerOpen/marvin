/**
 * Workspace activation endpoint
 * Handles POST requests to switch the active workspace
 */

import type { APIRoute } from "astro";
import { getAuthToken } from "@/lib/api/client";
import { activateWorkspace } from "@/lib/api/workspaces";

export const POST: APIRoute = async ({ request, cookies, redirect }) => {
  try {
    const formData = await request.formData();
    const workspaceId = formData.get("workspace_id");

    if (!workspaceId || typeof workspaceId !== "string") {
      return new Response(JSON.stringify({ error: "workspace_id is required" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    // Get auth token from cookies
    const authToken = getAuthToken(cookies);

    if (!authToken) {
      return redirect("/login?error=unauthorized", 303);
    }

    // Activate the workspace via backend API
    await activateWorkspace(workspaceId, authToken);

    // Back to the dashboard, or to `next` when the caller names a page of this app (a same-origin path
    // only: "/x", never "//host" or a full URL, so this can't be used as an open redirect).
    const next = formData.get("next");
    const safeNext = typeof next === "string" && /^\/(?![/\\])/.test(next) ? next : "/";
    return redirect(safeNext, 303);
  } catch (error) {
    console.error("[workspace/activate] Error:", error);

    const message = error instanceof Error ? error.message : "Failed to activate workspace";

    return new Response(JSON.stringify({ error: message }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
};
