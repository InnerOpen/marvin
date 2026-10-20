// Where the entry editor's Back link (and its after-save and after-trash navigation) goes. Pure, so `npm test` covers it
// (entryBack.test.mjs).
//
// A page that opens an entry in the editor can say where it came from with `?return=<path on this site>`: the Social network
// page does, so a rule opened from a network's Rules tab comes back to that tab. Without one, a Social rule (an internal entry
// type, hidden from All entries) goes back to Social: its network's Rules tab when it names exactly one network, else the
// Social page. Everything else goes back to All entries. Only same-site paths are ever followed (`safeReturnPath`).

import { networkPath } from "./socialSpace.ts";
import { SOCIAL_INBOX_PATH } from "./socialInbox.ts";
import { safeReturnPath } from "./session.ts";

export const ENTRIES_PATH = "/workspace/entries";
export const RULE_TYPE_SLUG = "social-auto-reply";

/** The `return` value as a same-site path, or null when there is none or it could leave the site. */
export function returnPathOf(value: string | null | undefined): string | null {
  if (!value || /[\u0000-\u001f\u007f]/.test(value)) return null;
  return safeReturnPath(value) === value ? value : null;
}

/** An editor link that remembers where it was opened from. */
export function withReturn(href: string, returnTo: string | null | undefined): string {
  const back = returnPathOf(returnTo);
  if (!back) return href;
  return `${href}${href.includes("?") ? "&" : "?"}return=${encodeURIComponent(back)}`;
}

/** A rule's editor link from a network's Rules tab: Back, save and Move to Trash come back to that tab. */
export function ruleEditorHref(path: string, slug: string): string {
  return withReturn(path, networkPath(slug, "rules"));
}

/** The network slugs a rule's `networks` field names (a string of words, or a list; none means every network). */
export function ruleNetworks(value: unknown): string[] {
  const words = Array.isArray(value) ? value.map(String) : typeof value === "string" ? value.split(/[\s,;]+/) : [];
  return [...new Set(words.map((w) => w.trim().toLowerCase().replace(/^@/, "")).filter(Boolean))];
}

export interface BackInput {
  /** The `?return=` query value, if the page was opened with one. */
  returnTo?: string | null;
  /** The entry's type slug. */
  typeSlug?: string | null;
  /** The entry's data (a rule's `networks`). */
  data?: Record<string, unknown> | null;
}

/** The Back target: the page it was opened from, else Social for a Social rule, else All entries. */
export function entryBackPath({ returnTo, typeSlug, data }: BackInput): string {
  const asked = returnPathOf(returnTo);
  if (asked) return asked;
  if (typeSlug !== RULE_TYPE_SLUG) return ENTRIES_PATH;
  const networks = ruleNetworks(data?.networks);
  return networks.length === 1 ? networkPath(networks[0], "rules") : SOCIAL_INBOX_PATH;
}
