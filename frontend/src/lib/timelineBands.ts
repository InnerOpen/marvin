/**
 * What a band row of a timeline can do besides draw (views.py, `spine.bands`): `run` drafts every item of one band at once, `assign` puts the
 * selected items in a band. Pure: the page reads and writes.
 */

import type { Band, Item } from "./timeline.ts";
import { narrowOptions, type RefOption } from "./refFields.ts";

/**
 * The `spine.run` values (a beat's number) of every item that holds the band's value, in timeline order: all its stretches, not only the one
 * clicked (a band set on beats 1 and 3 is two strips with a gap, and both draft "1,3"). A card, or an item with no value, is left out.
 */
export function bandItemKeys(items: Item[], stretches: Band[], slug: string): string[] {
  const inBand = new Set(stretches.filter((b) => b.slug === slug).flatMap((b) => b.items));
  return items.filter((i) => !i.card && i.key && inBand.has(i.id)).map((i) => i.key);
}

/** What a band's run button says it will do: "Draft the 2 beats of Test Band" (one: "Draft the beat of Test Band"). */
export function bandRunWords(label: string, noun: string, count: number, band: string): string {
  return count === 1 ? `${label} the ${noun} of ${band}` : `${label} the ${count} ${noun}s of ${band}`;
}

/**
 * The bands the selected items can be put in: those the entry form offers each of them (`narrowOptions` on its `ref_match`, with its own
 * fields as `ctxs` gives them), so only the ones every selected item may hold, in the options' order (by title).
 */
export function bandChoices(
  options: RefOption[],
  match: Record<string, string>,
  ctxs: Record<string, string>[],
): RefOption[] {
  const fitting = ctxs.map((ctx) => new Set(narrowOptions(options, match, ctx, "").map((o) => o.slug)));
  return options.filter((o) => fitting.every((slugs) => slugs.has(o.slug)));
}

/** One selected item, by its key ("4"), and why it was not changed when it was not. */
export interface Written {
  key: string;
  problem?: string;
}

/** The line the page shows once a band has been written on the selected items ("beat" as `noun`): what changed, and each item that did
 * not, with why. */
export function assignWords(title: string, chosen: string | null, noun: string, done: Written[]): string {
  const these = (list: Written[]) => `${noun}${list.length === 1 ? "" : "s"} ${list.map((w) => w.key).join(", ")}`;
  const changed = done.filter((w) => !w.problem);
  const failed = done.filter((w) => w.problem);
  const head = !changed.length
    ? `${title} not changed.`
    : chosen
      ? `${title} set to ${chosen} on ${these(changed)}.`
      : `${title} cleared on ${these(changed)}.`;
  return failed.length
    ? `${head} Not changed: ${failed.map((w) => `${noun} ${w.key} (${w.problem})`).join("; ")}.`
    : head;
}
