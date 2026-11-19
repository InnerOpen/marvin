// The sidebar's links to a package's views (a story's Timeline). A view asks for one with `sidebar` in its definition
// (services/blueprints/views.py): `true`, or `{label?, icon?}`. The link opens the view's page, which first lists the entries
// to open in it. It sits at the top of its package's group in the sidebar, or, when the package has no group there, under Guided setups.

/** A view's `sidebar` key: true, or the link's own label and icon. */
export type SidebarSpec = boolean | { label?: string; icon?: string };

export interface SidebarViewLink {
  slug: string;
  /** The slug of the package that brings the view: the sidebar group it goes in. */
  package: string;
  label: string;
  icon: string;
  href: string;
}

/** What the views list gives (only the `sidebar` key of a definition comes with it). */
export interface ListedView {
  slug: string;
  name: string;
  package: string;
  definition?: { sidebar?: SidebarSpec | null } | null;
}

const DEFAULT_ICON = "🎞";

/** The views that ask for a sidebar link, as links: the label is the view's title unless the view names one. */
export function sidebarViewLinks(views: ListedView[]): SidebarViewLink[] {
  const links: SidebarViewLink[] = [];
  for (const v of views) {
    const spec = v.definition?.sidebar;
    if (!spec) continue;
    const own = typeof spec === "object" ? spec : {};
    links.push({
      slug: v.slug,
      package: v.package,
      label: own.label?.trim() || v.name,
      icon: own.icon?.trim() || DEFAULT_ICON,
      href: `/workspace/views/${encodeURIComponent(v.slug)}`,
    });
  }
  return links;
}

/** Split the links by the package groups the sidebar draws: a link whose package has a group goes in it; the rest are loose. */
export function placeViewLinks(
  links: SidebarViewLink[],
  groupSlugs: string[],
): { byGroup: Map<string, SidebarViewLink[]>; loose: SidebarViewLink[] } {
  const groups = new Set(groupSlugs);
  const byGroup = new Map<string, SidebarViewLink[]>();
  const loose: SidebarViewLink[] = [];
  for (const link of links) {
    if (groups.has(link.package)) byGroup.set(link.package, [...(byGroup.get(link.package) ?? []), link]);
    else loose.push(link);
  }
  return { byGroup, loose };
}
