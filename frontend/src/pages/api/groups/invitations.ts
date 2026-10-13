import { PlatformClient } from "@inneropen/marvin-sdk/platform";
import type { APIRoute } from "astro";
import { getCookieName, getServerApiBaseUrl } from "@/lib/api/config";

export const POST: APIRoute = async ({ request, cookies }) => {
  try {
    const body = await request.json();
    const authToken = cookies.get(getCookieName())?.value;

    if (!authToken) {
      return new Response(JSON.stringify({ detail: "Not authenticated" }), {
        status: 401,
        headers: {
          "Content-Type": "application/json",
        },
      });
    }

    // Use SDK to create invitation
    const platformClient = new PlatformClient({
      apiUrl: getServerApiBaseUrl(),
      userToken: authToken,
    });

    const invitation = await platformClient.invites.create({
      usesLeft: body.uses_left,
      workspace_role: body.workspace_role || "EDITOR",
    });

    return new Response(JSON.stringify(invitation), {
      status: 201,
      headers: {
        "Content-Type": "application/json",
      },
    });
  } catch (error: any) {
    console.error("[invitations] Error:", error);

    const errorResponse = error.body || { detail: error.message || "Failed to create invitation" };
    const status = error.status || 500;

    return new Response(JSON.stringify(errorResponse), {
      status,
      headers: {
        "Content-Type": "application/json",
      },
    });
  }
};
