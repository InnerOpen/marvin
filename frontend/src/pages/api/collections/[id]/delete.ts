import type { APIRoute } from "astro";
import { getAuthToken } from "@/lib/api/client";
import { deleteCollection } from "@/lib/api/collections";

/**
 * Pull the human-readable message out of an SDK error. Marvin API errors carry a
 * `responseBody` JSON string like `{"detail": "..."}`; prefer that over the verbose
 * wrapped message (e.g. "Marvin API error: 409 Conflict at /api/... {...}").
 */
function extractErrorMessage(error: unknown): string {
  const body = (error as { responseBody?: string })?.responseBody;
  if (body) {
    try {
      const parsed = JSON.parse(body);
      if (typeof parsed?.detail === "string") return parsed.detail;
    } catch {
      // fall through to the generic message
    }
  }
  if (error instanceof Error) return error.message;
  return "Failed to delete collection";
}

export const POST: APIRoute = async ({ params, cookies }) => {
  try {
    const authToken = getAuthToken(cookies);
    if (!authToken) {
      return new Response(JSON.stringify({ error: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      });
    }
    const { id } = params;
    if (!id) {
      return new Response(JSON.stringify({ error: "Collection ID required" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    await deleteCollection(id, authToken);
    return new Response(null, { status: 204 });
  } catch (error) {
    console.error("[collections/delete] Error:", error);
    const status = (error as { statusCode?: number })?.statusCode ?? 500;
    return new Response(JSON.stringify({ error: extractErrorMessage(error) }), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }
};
