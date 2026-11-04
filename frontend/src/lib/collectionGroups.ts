// The sidebar: the collections a package installed get a section of their own (like Audience), named for the package.
// "Screenplay Studio: Cast" and "Screenplay Studio: Script" become "Screenplay Studio" with Cast and Script inside.
// A person's own collections, and an integration's (their own grouping), stay as they are.

export interface GroupableCollection {
  id: string;
  name: string;
  integrationId: string | null;
  /** the slug of the package that installed it */
  packageSlug: string | null;
}

export interface PackageGroup<T extends GroupableCollection> {
  slug: string;
  name: string;
  items: T[];
}

/** A package's title: what its collections' names say before the colon ("Screenplay Studio: Cast"), else the slug in words. */
export function packageTitle(slug: string, names: string[]): string {
  const prefixes = names.map((n) => (n.includes(":") ? n.split(":")[0].trim() : "")).filter(Boolean);
  const first = prefixes[0];
  if (first && prefixes.every((p) => p === first)) return first;
  const words = slug.replace(/[-_]+/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : "Package";
}

/** A collection's name inside its group: the group's own "Name:" is dropped, since the group already says it. */
export function nameWithin(name: string, group: string): string {
  const rest = name.toLowerCase().startsWith(`${group.toLowerCase()}:`) ? name.slice(group.length + 1).trim() : name;
  return rest ? rest[0].toUpperCase() + rest.slice(1) : name;
}

/** Split the collections into the ones no package owns (listed as they are) and one group per package, A to Z. A package's lone
 *  collection stays in the plain list: a group of one is a folder for nothing. Integration collections are left to their own grouping. */
export function groupByPackage<T extends GroupableCollection>(collections: T[]): { loose: T[]; groups: PackageGroup<T>[] } {
  const byPackage = new Map<string, T[]>();
  const loose: T[] = [];
  for (const c of collections) {
    if (c.packageSlug && !c.integrationId) byPackage.set(c.packageSlug, [...(byPackage.get(c.packageSlug) ?? []), c]);
    else loose.push(c);
  }
  const groups: PackageGroup<T>[] = [];
  for (const [slug, items] of byPackage) {
    if (items.length < 2) loose.push(...items);
    else groups.push({ slug, name: packageTitle(slug, items.map((c) => c.name)), items });
  }
  groups.sort((a, b) => a.name.localeCompare(b.name));
  return { loose, groups };
}
