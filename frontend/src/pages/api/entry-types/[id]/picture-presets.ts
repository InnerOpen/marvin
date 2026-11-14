import type { APIRoute } from "astro";
import { ApiRequestError, fetchApi, getAuthToken } from "@/lib/api/client";

/** Replace an entry type's picture presets (the Picture presets section of its settings page). Takes `{ presets: [...] }` and
 *  answers `{ presets }` as stored. The server checks each step, and that every preset a template names is still there; its
 *  answer (e.g. 400 "Invalid picture presets: …") comes back with its status as `{ error }` for the page to show. Called with
 *  fetchApi: the pinned SDK has no picturePresetsJson yet. */
export const PUT: APIRoute = async ({ params, request, cookies }) => {
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  try {
    const { id } = params;
    if (!id) return json({ error: "Entry type ID required" }, 400);
    const authToken = getAuthToken(cookies);
    if (!authToken) return json({ error: "Please log in again." }, 401);

    const body = await request.json().catch(() => null);
    if (!Array.isArray(body?.presets)) return json({ error: "Expected { presets: [...] }" }, 400);

    const saved = await fetchApi<{ picturePresetsJson?: unknown[] | null }>(
      `/api/platform/entry-types/${encodeURIComponent(id)}`,
      { method: "PATCH", body: JSON.stringify({ picturePresetsJson: body.presets }) },
      authToken,
    );
    return json({ presets: saved?.picturePresetsJson ?? [] });
  } catch (error) {
    if (error instanceof ApiRequestError) return json({ error: error.message }, error.status);
    console.error("[entry-types/picture-presets] Error:", error);
    return json({ error: error instanceof Error ? error.message : "The picture presets could not be saved." }, 500);
  }
};
