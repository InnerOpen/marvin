// The Resources page's view, kept in the URL: the name search, the type button, the option rows (tag, has a link,
// has an external id), the sort, and the Trash. The page asks GET /api/platform/resources for exactly that view, one
// page at a time (resourceListParams). Pure, so `npm test` covers it (resourceView.test.mjs).

export interface ResourceView {
  q: string;
  type: string;
  tag: string;
  /** "" any, "yes" has a URL, "no" has none */
  link: string;
  /** "" any, "yes" has an external id, "no" has none */
  external: string;
  sort: string;
  /** "trashed": the Trash instead of the list. */
  status: string;
}

export const SORTS: Record<string, string> = { name: "Name", type: "Type" };
const YES_NO = ["yes", "no"];

export function readResourceView(params: URLSearchParams): ResourceView {
  const text = (k: string) => (params.get(k) ?? "").trim();
  return {
    q: text("q"),
    type: text("type"),
    tag: text("tag"),
    link: YES_NO.includes(text("link")) ? text("link") : "",
    external: YES_NO.includes(text("external")) ? text("external") : "",
    sort: text("sort") in SORTS ? text("sort") : "name",
    status: text("status") === "trashed" ? "trashed" : "",
  };
}

/** What to ask GET /api/platform/resources for: the view's filters and order (the search reads names, slugs and
 *  descriptions; a tag the workspace doesn't have matches nothing). The page adds `limit`/`offset`. */
export function resourceListParams(view: ResourceView): Record<string, string | boolean> {
  const out: Record<string, string | boolean> = { sort: view.sort };
  if (view.q) out.q = view.q;
  if (view.type) out.resource_type = view.type;
  if (view.tag) out.tag = view.tag;
  if (view.link) out.has_url = view.link === "yes";
  if (view.external) out.has_external_id = view.external === "yes";
  if (view.status === "trashed") out.trashed = true;
  return out;
}

/** A link to this view with some filters changed ("" drops one). */
export function resourceHref(view: ResourceView, changes: Partial<ResourceView> = {}, path = "/workspace/resources"): string {
  const next = { ...view, ...changes };
  const qs = new URLSearchParams();
  for (const key of ["q", "type", "tag", "link", "external", "status"] as const) if (next[key]) qs.set(key, next[key]);
  if (next.sort !== "name") qs.set("sort", next.sort);
  const s = qs.toString();
  return s ? `${path}?${s}` : path;
}

/** Whether anything narrows or reorders the list (shows "Clear filters"; an empty result says "nothing matches"). */
export function isFiltered(view: ResourceView): boolean {
  return Boolean(view.q || view.type || view.tag || view.link || view.external || view.status || view.sort !== "name");
}
