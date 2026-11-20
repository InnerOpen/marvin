// The sidebar: where the collections and view links a package brings are listed. Each installed package has a place, chosen on the
// Packages page (GET /api/groups/packages/sidebar): a group folded inside Collections, named for the package (the default), a section of
// its own like Audience, or nowhere. "Screenplay Studio: Cast" and "Screenplay Studio: Script" become "Screenplay Studio" with Cast and
// Script inside. A person's own collections, and an integration's (their own grouping), stay as they are.

import type { SidebarViewLink } from "./viewLinks";

export interface GroupableCollection {
  id: string;
  name: string;
  integrationId: string | null;
  /** the slug of the package that installed it */
  packageSlug: string | null;
}

/** `collections`: a group inside the Collections fold. `section`: a section of its own. `hidden`: left out of the sidebar. */
export type SidebarPlace = "collections" | "section" | "hidden";

/** Where the sidebar puts one installed package. */
export interface PackagePlace {
  slug: string;
  name: string;
  sidebar: SidebarPlace;
}

export interface PackageGroup<T extends GroupableCollection> {
  slug: string;
  name: string;
  /** Its view links, listed first. */
  views: SidebarViewLink[];
  items: T[];
}

export interface PlacedPackages<T extends GroupableCollection> {
  /** Listed as they are under Collections: a person's own and an integration's. */
  loose: T[];
  /** Groups folded inside Collections, A to Z. */
  nested: PackageGroup<T>[];
  /** Sections of their own, A to Z. */
  sections: PackageGroup<T>[];
}

/** A package's title: what its collections' names say before the colon ("Screenplay Studio: Cast"), else its own name, else the slug in words. */
export function packageTitle(slug: string, names: string[], packageName?: string): string {
  const prefixes = names.map((n) => (n.includes(":") ? n.split(":")[0].trim() : "")).filter(Boolean);
  const first = prefixes[0];
  if (first && prefixes.every((p) => p === first)) return first;
  if (packageName?.trim()) return packageName.trim();
  const words = slug.replace(/[-_]+/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : "Package";
}

/** A collection's name inside its group: the group's own "Name:" is dropped, since the group already says it. */
export function nameWithin(name: string, group: string): string {
  const rest = name.toLowerCase().startsWith(`${group.toLowerCase()}:`) ? name.slice(group.length + 1).trim() : name;
  return rest ? rest[0].toUpperCase() + rest.slice(1) : name;
}

const byName = (a: { name: string }, b: { name: string }) => a.name.localeCompare(b.name);

/** Place each package's collections and view links where its choice says: always under the package's name, even when it brings one
 *  thing, so a collection is found under the package that made it. A package missing from `places` is under Collections, the
 *  default. Hidden ones are left out. Integration collections are left to their own grouping. */
export function placePackages<T extends GroupableCollection>(collections: T[], views: SidebarViewLink[], places: PackagePlace[]): PlacedPackages<T> {
  const placeOf = new Map(places.map((p) => [p.slug, p]));
  const byPackage = new Map<string, { items: T[]; views: SidebarViewLink[] }>();
  const bucket = (slug: string) => byPackage.get(slug) ?? byPackage.set(slug, { items: [], views: [] }).get(slug)!;
  const placed: PlacedPackages<T> = { loose: [], nested: [], sections: [] };
  for (const c of collections) {
    if (c.packageSlug && !c.integrationId) bucket(c.packageSlug).items.push(c);
    else placed.loose.push(c);
  }
  for (const v of views) bucket(v.package).views.push(v);
  for (const [slug, { items, views: links }] of byPackage) {
    const place = placeOf.get(slug)?.sidebar ?? "collections";
    if (place === "hidden") continue;
    const group = { slug, name: packageTitle(slug, items.map((c) => c.name), placeOf.get(slug)?.name), views: links, items };
    (place === "section" ? placed.sections : placed.nested).push(group);
  }
  placed.nested.sort(byName);
  placed.sections.sort(byName);
  return placed;
}
