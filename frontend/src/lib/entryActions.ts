/**
 * The quick links at the top of an entry's page: the things a person opens an entry *for* (a story's timeline, a guided setup, the live page,
 * its filmstrip, its video), kept out of the details sidebar where they were lost under the slug. The pure part: the page hands in what the
 * entry has and gets back the buttons in the order to draw them.
 */

export interface ActionLink {
  label: string;
  href: string;
  /** primary: what the entry is mostly opened for (views, guided setups); secondary: the rest. */
  tone: "primary" | "secondary";
  /** Opens in a new tab (a live page, a file). */
  external?: boolean;
  /** A link that cannot be followed yet, and why (the site link before the entry is published). */
  disabled?: string;
}

interface AttachedAsset {
  role?: string | null;
  name?: string | null;
  publicUrl?: string | null;
  mimeType?: string | null;
}

/** Files a person wants to *open*, not manage: a web page (the filmstrip, the script page), a PDF, a video. Pictures and audio have their own previews. */
const OPENABLE = [/^text\/html/, /^application\/pdf/, /^video\//];

const isOpenable = (mime: string | null | undefined): boolean => OPENABLE.some((re) => re.test(mime ?? ""));

/** The field labels of a schema by key, for naming an attached file by the field it fills ("Filmstrip (web page)" rather than a file name). */
function labelsOf(schema: { fields?: { key?: string; label?: string }[] } | null | undefined): Map<string, string> {
  return new Map((schema?.fields ?? []).flatMap((f) => (f.key && f.label ? [[f.key, f.label] as const] : [])));
}

/** A label without its parenthetical: "Filmstrip (web page)" reads "Filmstrip" on a button. */
const short = (label: string): string => label.replace(/\s*\([^)]*\)\s*$/, "").trim() || label;

export function entryActions(input: {
  views: { slug: string; name: string }[];
  viewHref: (slug: string) => string;
  setups: { label: string; href: string }[];
  site: { href: string } | { disabled: true; hint: string } | null;
  assets: AttachedAsset[];
  schema: { fields?: { key?: string; label?: string }[] } | null | undefined;
}): ActionLink[] {
  const out: ActionLink[] = [];
  for (const v of input.views) out.push({ label: v.name, href: input.viewHref(v.slug), tone: "primary" });
  for (const s of input.setups) out.push({ label: s.label, href: s.href, tone: "primary" });
  const labels = labelsOf(input.schema);
  const seen = new Set<string>();
  for (const a of input.assets) {
    if (!a.publicUrl || !isOpenable(a.mimeType) || seen.has(a.publicUrl)) continue;
    seen.add(a.publicUrl);
    const label = short((a.role ? labels.get(a.role) : undefined) ?? a.name ?? "File");
    out.push({ label, href: a.publicUrl, tone: "secondary", external: true });
  }
  if (input.site) {
    out.push("href" in input.site ? { label: "View on site", href: input.site.href, tone: "secondary", external: true } : { label: "View on site", href: "#", tone: "secondary", external: true, disabled: input.site.hint });
  }
  return out;
}
