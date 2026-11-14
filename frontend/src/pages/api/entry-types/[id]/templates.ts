import type { APIRoute } from "astro";
import { ApiRequestError, fetchApi, getAuthToken } from "@/lib/api/client";

/** Replace an entry type's templates (the Templates section of its settings page). Takes `{ templates: [...] }` and answers
 *  `{ templates }` as stored. The server checks them against the type's schema; its answer (e.g. 400 "Invalid templates: …")
 *  comes back with its status as `{ error }` for the page to show. Called with fetchApi: the pinned SDK has no templatesJson yet. */
export const PUT: APIRoute = async ({ params, request, cookies }) => {
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  try {
    const { id } = params;
    if (!id) return json({ error: "Entry type ID required" }, 400);
    const authToken = getAuthToken(cookies);
    if (!authToken) return json({ error: "Please log in again." }, 401);

    const body = await request.json().catch(() => null);
    if (!Array.isArray(body?.templates)) return json({ error: "Expected { templates: [...] }" }, 400);

    const saved = await fetchApi<{ templatesJson?: unknown[] | null }>(
      `/api/platform/entry-types/${encodeURIComponent(id)}`,
      { method: "PATCH", body: JSON.stringify({ templatesJson: body.templates }) },
      authToken,
    );
    return json({ templates: saved?.templatesJson ?? [] });
  } catch (error) {
    if (error instanceof ApiRequestError) return json({ error: error.message }, error.status);
    console.error("[entry-types/templates] Error:", error);
    return json({ error: error instanceof Error ? error.message : "The templates could not be saved." }, 500);
  }
};
