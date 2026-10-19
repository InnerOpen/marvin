// The Resources page's view, kept in the URL: the name search, the type button, the option rows (tag, has a link,
// has an external id), the sort, and the Trash. The list API takes no filters, so the page loads them all and this
// picks. Pure, so `npm test` covers it (resourceView.test.mjs).

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

interface ResourceLike {
  name: string;
  resourceType: string;
  description?: string | null;
  url?: string | null;
  externalId?: string | null;
  tags?: string[];
}

const matchesYesNo = (want: string, has: boolean) => !want || (want === "yes") === has;

/** The resources this view shows, sorted. The name search also looks in the description. */
export function filterResources<T extends ResourceLike>(resources: T[], view: ResourceView): T[] {
  const q = view.q.toLowerCase();
  const shown = resources.filter(
    (r) =>
      (!q || r.name.toLowerCase().includes(q) || (r.description ?? "").toLowerCase().includes(q)) &&
      (!view.type || r.resourceType === view.type) &&
      (!view.tag || (r.tags ?? []).includes(view.tag)) &&
      matchesYesNo(view.link, Boolean(r.url)) &&
      matchesYesNo(view.external, Boolean(r.externalId)),
  );
  const byName = (a: T, b: T) => a.name.localeCompare(b.name);
  return shown.sort(view.sort === "type" ? (a, b) => a.resourceType.localeCompare(b.resourceType) || byName(a, b) : byName);
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
