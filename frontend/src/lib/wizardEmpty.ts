/**
 * What a guided setup's step says when it has nothing to show, and where it points: why it is empty in plain words (the package's own
 * `empty`, or a default every kind of step shares), the place that fills it (`empty_next`), the earlier choices that narrow it, and, for
 * a run step whose `requires` is not met, which earlier step fills what is missing. Pure, so it runs under `node --test`: the page fetches.
 */
import { type Ctx, type Step, type WizardDefinition, isSetupLink, isShown, setupLinkHref, stepHref } from "./wizard.ts";

const REF = /\$\{([^}]*)\}/g;

export interface EmptyLink {
  label: string;
  href: string;
}

function refsIn(value: unknown): string[] {
  if (typeof value === "string") return [...value.matchAll(REF)].map((m) => m[1]);
  if (Array.isArray(value)) return value.flatMap(refsIn);
  if (value && typeof value === "object") return Object.values(value).flatMap(refsIn);
  return [];
}

const stepsBefore = (def: WizardDefinition, step: Step): Step[] => def.steps.slice(0, Math.max(def.steps.findIndex((s) => s.id === step.id), 0));

/** “World” and “Story”: the titles of some steps, as a sentence names them. */
function named(steps: Step[]): string {
  const titles = steps.map((s) => `“${s.title}”`);
  return titles.length > 1 ? `${titles.slice(0, -1).join(", ")} and ${titles[titles.length - 1]}` : (titles[0] ?? "");
}

/** The earlier steps whose answer narrows what this one lists: the choices it reads as `${name}` (in its `scope`, `assets`, `where` or
 *  `or_where`) and the entry it hangs under (`parent`). Only the ones answered: a choice that was skipped narrows nothing. */
export function narrowedBy(def: WizardDefinition, ctx: Ctx, step: Step): Step[] {
  const names = new Set([...refsIn([step.scope, step.assets, step.where, step.or_where]), ...(typeof step.parent === "string" ? [step.parent] : [])]);
  return stepsBefore(def, step).filter((s) => typeof s.as === "string" && names.has(s.as) && !!ctx[s.as]);
}

/** The step looks for something particular whatever was chosen: conditions, an assets filter, or a scope with a value of its own. */
function filters(step: Step): boolean {
  const literal = Object.values(step.scope ?? {}).some((v) => refsIn(v).length === 0);
  return literal || (step.where ?? []).length > 0 || (step.or_where ?? []).length > 0 || Object.keys(step.assets ?? {}).length > 0;
}

/** The line an empty step shows: the package's words (`empty`), or plainly why there is nothing. `owner` is the title of the entry the
 *  list hangs under ("The Tin Soldier has no cast member yet."), `narrowed` the earlier choices that narrow it (`narrowedBy`), and
 *  `todo` what to do about it on this step ("Add the first one below."). */
export function emptyLine(step: Step, noun: string, about: { owner?: string | null; narrowed?: Step[]; todo?: string } = {}): string {
  const own = typeof step.empty === "string" ? step.empty.trim() : "";
  if (own) return own;
  const what = noun.trim().toLowerCase() || "entry";
  const narrowed = about.narrowed ?? [];
  const why = about.owner?.trim()
    ? `${about.owner.trim()} has no ${what} yet.`
    : narrowed.length
      ? `No ${what} belongs to what you chose in ${named(narrowed)} yet.`
      : filters(step)
        ? `No ${what} fits what this step looks for right now.`
        : `This workspace has no ${what} yet.`;
  return about.todo ? `${why} ${about.todo}` : why;
}

/** A path inside the app, never a full address (the definition is checked when its package is installed; this is the page's own check). */
const inApp = (href: unknown): href is string => typeof href === "string" && href.startsWith("/") && !href.startsWith("//");

/** Where an empty step points. First the place its package names (`empty_next`: `{step}`, an earlier step of the setup, `{text, setup,
 *  step?, carry?}`, another setup opened with the choices it carries and the way back here, or `{text, href}`, a path in the app), then
 *  each earlier choice in `change`, to pick something else there. `entries` are the chosen entries, for a carry of `key.field`. */
export function emptyLinks(
  def: WizardDefinition,
  ctx: Ctx,
  step: Step,
  slug: string,
  change: Step[] = [],
  entries: Record<string, { dataJson?: Record<string, unknown> | null } | undefined> = {},
): EmptyLink[] {
  const links: EmptyLink[] = [];
  const next = step.empty_next as { step?: string; href?: string; text?: string; setup?: string } | undefined;
  const words = typeof next?.text === "string" ? next.text.trim() : "";
  const elsewhere = isSetupLink(next) ? next : null;
  const to = next?.step && !elsewhere ? stepsBefore(def, step).find((s) => s.id === next.step && isShown(s, ctx)) : undefined;
  if (elsewhere) links.push({ label: words, href: setupLinkHref(elsewhere, { def, slug, step: step.id, ctx, entries }) });
  else if (to) links.push({ label: words || `Go to “${to.title}”`, href: stepHref(slug, ctx, to.id) });
  else if (inApp(next?.href) && words) links.push({ label: words, href: next.href });
  for (const s of change) if (s.id !== to?.id) links.push({ label: `Change “${s.title}”`, href: stepHref(slug, ctx, s.id) });
  return links;
}

/** The earlier step that fills `field` of the entry chosen as `entry`: a form that shows the field, an upload into it, or a run that
 *  writes it (its `report`). When the entry itself was not chosen, the step that picks it. Null when no step of the setup does. */
export function fillerOf(def: WizardDefinition, ctx: Ctx, step: Step, needs: { entry: string; field: string }): Step | null {
  const before = stepsBefore(def, step).filter((s) => isShown(s, ctx));
  if (!ctx[needs.entry]) return before.find((s) => s.kind === "choose" && s.as === needs.entry) ?? null;
  const fills = (s: Step) =>
    (s.kind === "form" && s.entry === needs.entry && ((s.fields ?? []) as string[]).includes(needs.field)) ||
    (s.kind === "upload" && s.entry === needs.entry && s.field === needs.field) ||
    (s.kind === "run" && s.report?.entry === needs.entry && s.report?.field === needs.field);
  return before.find(fills) ?? null;
}

/** What a run step says when what it `requires` is missing, and where to fill it: the earlier step that does (`fillerOf`), else the
 *  entry's own page. `label` is the field's name as its type says it, `entry` the chosen entry (none when it was never chosen). */
export function lackingOf(
  def: WizardDefinition,
  ctx: Ctx,
  step: Step,
  slug: string,
  found: { label?: string | null; entry?: { id: string; title: string } | null },
): { text: string; link: (EmptyLink & { out?: boolean }) | null } {
  const needs = step.requires as { entry: string; field: string };
  const filler = fillerOf(def, ctx, step, needs);
  const go = filler ? { label: `Go to “${filler.title}”`, href: stepHref(slug, ctx, filler.id) } : null;
  if (!found.entry) return { text: `This step needs the ${needs.entry} chosen first.`, link: go };
  const name = (found.label ?? "").replace(/\s*\(.*\)\s*$/, "").trim() || needs.field;
  return {
    text: `“${name}” on ${found.entry.title} is empty, and this step needs it.`,
    link: go ?? { label: `Open ${found.entry.title} to fill it in`, href: `/workspace/entries/${found.entry.id}`, out: true },
  };
}
