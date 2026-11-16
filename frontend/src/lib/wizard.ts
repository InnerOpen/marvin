/**
 * Wizards: the pure part. A package ships a wizard as data (see the backend's services/blueprints/wizards.py); this decides which steps
 * show, what the next one is, and what each step asks the entries API. Where the person is rides in the page's address (`?step=…&world=…`):
 * the context is the set of choices so far, so a wizard keeps nothing of its own and can be left and picked up again.
 */

import type { ApprovalField } from "./approvalFields";

export type Ctx = Record<string, string>;

export interface When {
  ctx: string;
  op: "eq" | "neq" | "set" | "unset";
  value?: string;
}

export interface Step {
  id: string;
  kind: "option" | "choose" | "form" | "upload" | "list" | "gallery" | "run" | "review";
  title: string;
  help?: string;
  when?: When;
  [key: string]: any;
}

export interface NextLine {
  text: string;
  href?: string;
}

export interface WizardDefinition {
  title: string;
  description?: string;
  steps: Step[];
  /** What to do once the wizard is done, shown at the end. */
  next?: NextLine[];
  /** The button at the end that opens what was made: `entry` is a key a choose step set; `view` a view (the same package's) it opens in. */
  open?: { entry: string; label: string; view?: string };
  /** The button at the end that goes round once more: back to `step`, the choices from there on forgotten. */
  again?: { label: string; step: string };
}

/** Entries by title as people count: "2" before "10", ignoring case, so a long list of numbered lines runs from the lowest to the highest. */
export function naturalByTitle<T extends { title?: string | null }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => (a.title ?? "").localeCompare(b.title ?? "", undefined, { numeric: true, sensitivity: "base" }));
}

/** The name a new entry gets from a gallery's `name`: its parent's title, then the noun and the next number ("01 Granny: People say… · take 3"). */
export function numberedTitle(base: string, noun: string, existing: number): string {
  return `${base.trim() || "Untitled"} · ${noun.trim()} ${existing + 1}`;
}

/** What a step's `show` card reads out: each wanted field of the entry that has a value, labelled by the entry type's own label. */
export function shownLines(
  entryData: Record<string, unknown> | null | undefined,
  schema: { fields?: { key?: string; label?: string }[] | null } | null | undefined,
  fields: string[],
): { key: string; label: string; value: string }[] {
  const labels = new Map((schema?.fields ?? []).map((f) => [f.key, f.label] as const));
  return fields.flatMap((key) => {
    const raw = entryData?.[key];
    const value = typeof raw === "string" ? raw.trim() : typeof raw === "number" ? String(raw) : "";
    return value ? [{ key, label: labels.get(key) || key, value }] : [];
  });
}

/**
 * The fields of a gallery's add form, of the type's `fields` those `asked` (askedKeys: the step's `add.fields` and what the type requires).
 * When the step lists its fields in the type's own order, the form is as the type draws it, groups and all. When it lists them in another
 * order, that order is the form's: the listed fields come first, as listed and outside their groups (a group folds its fields together where
 * its first one is, which would undo the order and hide a field the step asks for: a line's Direction under its words), then whatever else
 * the type requires, in its order and groups.
 */
export function addFormFields<F extends { key: string; group?: unknown }>(typeFields: F[], listed: string[] | undefined, asked: string[]): F[] {
  const inType = typeFields.filter((f) => asked.includes(f.key));
  const named = (listed ?? []).flatMap((k) => inType.filter((f) => f.key === k));
  const at = named.map((f) => inType.indexOf(f));
  if (at.every((n, i) => i === 0 || n > at[i - 1])) return inType;
  return [...named.map((f) => ({ ...f, group: undefined })), ...inType.filter((f) => !named.includes(f))];
}

/** What a gallery's add form starts with (`add.prefill`: {field: "key.field"}): the chosen entries' own values, so a take starts from its line's words. */
export function prefillOf(
  add: { prefill?: Record<string, string> } | undefined,
  entries: Record<string, { dataJson?: Record<string, unknown> | null }>,
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [field, from] of Object.entries(add?.prefill ?? {})) {
    for (const option of from.split("|")) { // "line.delivery_text|line.text": the first that has a value
      const [key, source] = option.split(".");
      const value = entries[key]?.dataJson?.[source];
      if (typeof value === "string" && value.trim()) out[field] = value;
      else if (typeof value === "number") out[field] = String(value);
      if (field in out) break;
    }
  }
  return out;
}

/** A card action (`card_actions`) shows on a card when its `when` (field eq/neq value) holds, or always without one. */
export function cardActionShown(action: { when?: { field: string; op: "eq" | "neq"; value: string } }, data: Record<string, unknown> | null | undefined): boolean {
  const w = action.when;
  if (!w) return true;
  const same = String(data?.[w.field] ?? "") === w.value;
  return w.op === "eq" ? same : !same;
}

/** How a file box can be filled, as the start of a sentence: "Choose, upload or record", "Upload or record", "Upload". A box offers the
 *  workspace's assets only where the step says so, and a recording only where it takes sounds. */
export function fileWays(choose: boolean, record: boolean): string {
  const ways = [choose && "choose", "upload", record && "record"].filter((w): w is string => !!w);
  const said = ways.length > 2 ? `${ways.slice(0, -1).join(", ")} or ${ways[ways.length - 1]}` : ways.join(" or ");
  return said.charAt(0).toUpperCase() + said.slice(1);
}

/** Whether a save button of the add form is off for now (`add.buttons[].file`): one that needs the file box filled ("required"), or one
 *  that must find it empty ("none"). Neither can then post an error. */
export function fileButtonOff(needs: string | null | undefined, has: boolean): boolean {
  return needs === "required" ? !has : needs === "none" ? has : false;
}

/** The line under the add form's buttons that says why one is off, so nobody has to guess; empty when none is. `ways` is `fileWays`. */
export function fileButtonNote(buttons: { label: string; needs?: string | null }[], has: boolean, noun: string, ways: string): string {
  const off = buttons.filter((b) => fileButtonOff(b.needs, has)).map((b) => `“${b.label}”`);
  if (!off.length) return "";
  return has ? `A ${noun} is chosen. Remove it to use ${off.join(" or ")}.` : `${ways} a ${noun} to use ${off.join(" or ")}.`;
}

/** What a step's `subtitle` shows under a title: one field, or up to three joined with " · " (a line's words, then its status). Fields with nothing in
 *  them are left out, and each is cut at `max` characters (the whole thing is wanted where there is room: a pick list). */
export function subtitleOf(subtitle: unknown, data: Record<string, unknown> | null | undefined, max = 60): string {
  const keys = Array.isArray(subtitle) ? subtitle : typeof subtitle === "string" && subtitle ? [subtitle] : [];
  return keys
    .slice(0, 3)
    .map((k) => String(data?.[String(k)] ?? "").replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .map((s) => (s.length > max ? `${s.slice(0, max - 1).trimEnd()}…` : s))
    .join(" · ");
}

/** What a card being made says before its run does, when the step names no words for its status. */
export const WORKING_LINE = "Being made…";

/** A gallery's `working`: the `status` values that mean something is being made for the card (queued, redo), each with the line the card
 *  shows meanwhile. A step that shows approvals and names none watches `queued`, as it always has. */
function workingSays(step: Step): Record<string, string> {
  return (step.working as Record<string, string> | undefined) ?? (step.approve ? { queued: WORKING_LINE } : {});
}

/** The line a gallery card shows while something is being made for it, or null when nothing is. */
export function workingOf(step: Step, data: Record<string, unknown> | null | undefined): string | null {
  const status = String(data?.status ?? "");
  const says = workingSays(step);
  return status && Object.hasOwn(says, status) ? says[status] || WORKING_LINE : null;
}

/** Whether the cards a page drew as being made (id → status) stand differently now: one's status moved on, or it is gone. The page is
 *  drawn again then, so the card shows its sound (or what failed) without a refresh. */
export function workingChanged(drawn: Record<string, string>, now: { id: string; dataJson?: Record<string, unknown> | null }[]): boolean {
  const status = new Map(now.map((r) => [r.id, String(r.dataJson?.status ?? "")]));
  return Object.entries(drawn).some(([id, was]) => status.get(id) !== was);
}

/** The label a gallery's `highlight` puts on a card whose field has the wanted value (the take in use), or null. */
export function highlightOf(step: Step, data: Record<string, unknown> | null | undefined): string | null {
  const h = step.highlight as { field?: string; value?: string; label: string } | undefined;
  return h?.field && data?.[h.field] === h.value ? h.label : null;
}

export interface ReferencedBy {
  entry_type: string;
  field: string;
  scope?: Record<string, string>;
}

/** The entries query that finds who points at a gallery's cards, for a `highlight` by reference (an actor cast in this story: the story's
 *  cast members whose `actor` holds its slug). Null when the step has none, or when a scope value came out empty: a story that was not
 *  chosen must not mark everyone cast in any story. */
export function referencingSpec(step: Step, ctx: Ctx): Record<string, unknown> | null {
  const by = (step.highlight as { referenced_by?: ReferencedBy } | undefined)?.referenced_by;
  if (!by) return null;
  const scope = substitute(by.scope ?? {}, ctx);
  if (Object.values(scope).some((v) => v === "" || v == null)) return null;
  return { entry_type: by.entry_type, fields: scope };
}

/** The mark on each card that an entry of the query above points at: card slug → the highlight's label, followed by the pointing
 *  entries' `label_field` values when it names one ("Cast as" + "Granny, Old Granny": one actor may play a role at several ages). */
export function referenceMarks(step: Step, referencing: { dataJson?: Record<string, unknown> | null }[]): Map<string, string> {
  const h = step.highlight as { referenced_by?: ReferencedBy; label: string; label_field?: string } | undefined;
  const found = new Map<string, string[]>();
  if (!h?.referenced_by) return new Map();
  for (const r of referencing) {
    const slug = String(r.dataJson?.[h.referenced_by.field] ?? "").trim();
    if (!slug) continue;
    const said = h.label_field ? String(r.dataJson?.[h.label_field] ?? "").trim() : "";
    const list = found.get(slug) ?? [];
    if (said && !list.includes(said)) list.push(said);
    found.set(slug, list);
  }
  return new Map([...found].map(([slug, said]) => [slug, said.length ? `${h.label} ${said.join(", ")}` : h.label]));
}

/** The seconds a browser measured for an upload, when they are a real positive number (a field a form posts is text). */
export function measuredSeconds(raw: unknown): number | null {
  const n = typeof raw === "string" && raw.trim() !== "" ? Number(raw) : NaN;
  return Number.isFinite(n) && n > 0 && n < 36000 ? Math.round(n * 1000) / 1000 : null;
}

/** A step is done when the data says so: a choice or option that is set. Other kinds have no mark of their own (they can be redone). */
export function isDone(step: Step, ctx: Ctx): boolean {
  return (step.kind === "choose" || step.kind === "option") && !!ctx[step.as];
}

export const STEP_PARAM = "step";
/** What a page says after a step did something: a code in the address, never free text (a link could not spoof a message). */
export const NOTICES: Record<string, string> = {
  // Only when the server could not name the run it started: a run that has an id is followed instead (RUN_PARAM).
  started: "Started. Anything the workflow asks you appears below as it runs; when it is done, go on to the next step.",
  approved: "Approved. The workflow goes on; anything else it asks appears here.",
  denied: "Denied. The workflow stops there; run it again if you change your mind.",
  chosen: "Your choice was taken. The workflow goes on; anything else it asks appears here.",
  again: "Started again. Anything it asks appears below as it runs.",
  added: "Added.",
  trashed: "Moved to the Trash. You can bring it back from the Trash.",
  changed: "Done.",
  saved: "Saved.",
};
/** Address parameters that are not choices: the step asked for, and the line to show after a step that started something. */
export const NOTICE_PARAM = "notice";
/** The run a step started (its execution id): the step says where that run stands until it is over. */
export const RUN_PARAM = "run";
const RUN_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** The run named in the address, when it is an id (it goes into an API path). */
export function runIdOf(params: URLSearchParams): string | null {
  const value = (params.get(RUN_PARAM) ?? "").trim().toLowerCase();
  return RUN_ID.test(value) ? value : null;
}
const CTX_NAME = /^[a-z][a-z0-9_]{0,39}$/;
const MAX_VALUE = 200;
const REF = /\$\{([^}]*)\}/g;
/** The page of a multi-select step's cards (`page`, `per`): the page's own, never a choice. */
export const PAGE_PARAM = "page";
export const PER_PARAM = "per";
/** A list step without a parent: its filter, the facet value shown and the search (lib/wizardScopedList.ts). */
export const FILTER_PARAM = "filter";
export const FACET_PARAM = "facet";
export const SEARCH_PARAM = "q";
const OWN_PARAMS = new Set([STEP_PARAM, NOTICE_PARAM, RUN_PARAM, PAGE_PARAM, PER_PARAM, FILTER_PARAM, FACET_PARAM, SEARCH_PARAM]);

/**
 * A multi-select step (`choose` with `multiple`) keeps its picks in the context as ONE value: the slugs of the entries (or the ids of the
 * assets) joined with commas, "nell,granny,the-young-man". Neither a slug nor an id has a comma in it. At most MAX_PICKS of them, so the
 * address stays short enough for every server on the way (100 slugs of 80 characters are about 8 KB): a longer list is refused with
 * a message, never cut short in silence, and a link that carries more than that is read as its first MAX_PICKS.
 */
export const MAX_PICKS = 100;
export const LIST_SEP = ",";
const PICK = /^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/;

/** The picks a list value holds, in order, each once; anything that is not a slug or an id is left out. */
export function listOf(value: string | null | undefined): string[] {
  const out: string[] = [];
  for (const part of String(value ?? "").split(LIST_SEP)) {
    const item = part.trim();
    if (PICK.test(item) && !out.includes(item)) out.push(item);
  }
  return out;
}

/** The value that carries these picks ("" for none). */
export function joinList(items: string[]): string {
  return listOf(items.join(LIST_SEP)).join(LIST_SEP);
}

/** What to say when a selection is longer than MAX_PICKS, or "" when it is not. */
export function picksProblem(count: number): string {
  return count > MAX_PICKS ? `${count} are selected; at most ${MAX_PICKS} can go on at once. Untick ${count - MAX_PICKS}, or do the rest in another round.` : "";
}

/**
 * The selection after a page of cards was posted: what was picked on other pages stays, in its order; of the cards on this page
 * (`onPage`), exactly the ticked ones are in, the new ones after the rest. So a page move keeps every pick and can also drop one.
 */
export function mergePicks(prior: string[], onPage: string[], ticked: string[]): string[] {
  const shown = new Set(onPage);
  const kept = prior.filter((p) => !shown.has(p) || ticked.includes(p));
  return [...kept, ...onPage.filter((p) => ticked.includes(p) && !kept.includes(p))];
}

/** The live line under a multi-select's buttons: how many are selected, and the cap once it is passed. */
export function pickedLine(count: number): string {
  if (count > MAX_PICKS) return `${count} selected: at most ${MAX_PICKS} can go on at once. Untick ${count - MAX_PICKS}.`;
  return count === 0 ? "Nothing selected yet" : `${count} selected`;
}

/** The context keys whose value is a list: those a multi-select step sets. */
export function listKeys(def: WizardDefinition): Set<string> {
  return new Set(def.steps.filter((s) => s.kind === "choose" && s.multiple === true && typeof s.as === "string").map((s) => s.as as string));
}

/** The choices so far, from the address: every parameter the page does not use itself (`step`, `notice`, `run`, `page`, `per`, `filter`, `facet`, `q`) whose name
 *  is a context name. A list key (`lists`) is read as its picks, at most MAX_PICKS of them; any other value is cut at 200 characters. */
export function readCtx(params: URLSearchParams, lists: Set<string> = new Set()): Ctx {
  const ctx: Ctx = {};
  for (const [key, value] of params.entries()) {
    if (OWN_PARAMS.has(key) || !CTX_NAME.test(key) || !value.trim()) continue;
    if (lists.has(key)) {
      const picks = listOf(value).slice(0, MAX_PICKS);
      if (picks.length) ctx[key] = picks.join(LIST_SEP);
    } else ctx[key] = value.trim().slice(0, MAX_VALUE);
  }
  return ctx;
}

export function holds(when: When | undefined, ctx: Ctx): boolean {
  if (!when) return true;
  const have = ctx[when.ctx];
  if (when.op === "set") return !!have;
  if (when.op === "unset") return !have;
  if (when.op === "eq") return have === when.value;
  return have !== when.value;
}

/** A step is shown when its `when` holds and the entry it works on has been chosen (a skipped optional choice hides what depends on it). */
export function isShown(step: Step, ctx: Ctx): boolean {
  if (!holds(step.when, ctx)) return false;
  const needs = [step.entry, step.parent].filter((k): k is string => typeof k === "string");
  return needs.every((key) => !!ctx[key]);
}

/** The context keys the steps after `stepId` set: a changed choice drops them, so nothing later acts on a stale pick. */
export function keysAfter(def: WizardDefinition, stepId: string): string[] {
  const index = def.steps.findIndex((s) => s.id === stepId);
  return def.steps.slice(index + 1).map((s) => s.as).filter((k): k is string => typeof k === "string");
}

/** The context without the keys the step `stepId` and the steps after it set: the setup as it stands on coming back to that step to go again. */
export function withoutFrom(def: WizardDefinition, ctx: Ctx, stepId: string): Ctx {
  const index = def.steps.findIndex((s) => s.id === stepId);
  const drop = new Set(def.steps.slice(Math.max(index, 0)).map((s) => s.as).filter((k): k is string => typeof k === "string"));
  return Object.fromEntries(Object.entries(ctx).filter(([k]) => !drop.has(k)));
}

/** The context without the keys the steps after `stepId` set. */
export function withoutLater(def: WizardDefinition, ctx: Ctx, stepId: string): Ctx {
  const drop = new Set(keysAfter(def, stepId));
  return Object.fromEntries(Object.entries(ctx).filter(([k]) => !drop.has(k)));
}

/** Where "Skip without saving" goes from an optional choice or option: on, with nothing chosen there (and what later steps chose on the
 *  strength of it dropped, as a changed choice drops it), to the next step shown without it. Null for a choice that is not optional
 *  (the steps after it wait for it) or when nothing comes after. */
export function skipTo(def: WizardDefinition, ctx: Ctx, step: Step): { ctx: Ctx; step: Step } | null {
  if ((step.kind !== "option" && step.kind !== "choose") || !step.optional) return null;
  const { [step.as]: _dropped, ...rest } = withoutLater(def, ctx, step.id);
  const then = nextStep(def, rest, step.id);
  return then ? { ctx: rest, step: then } : null;
}

/** The option step that sets `key`, if any. */
export function optionStepOf(def: WizardDefinition, key: string): Step | undefined {
  return def.steps.find((s) => s.kind === "option" && s.as === key);
}

/** One choice of an option step: its value, its words and, for a template, what it is for. */
export interface OptionChoice {
  value: string;
  label: string;
  description?: string;
}

/** The choices of an option step with `templates`: the entry type's templates as it has them now (each one's name, and what it is
 *  for), in the type's order. None when the type is not there or has no template yet. */
export function templateOptions(type: { templatesJson?: unknown } | null | undefined): OptionChoice[] {
  const stored = Array.isArray(type?.templatesJson) ? (type.templatesJson as unknown[]) : [];
  return stored.flatMap((raw) => {
    const t = raw && typeof raw === "object" ? (raw as { slug?: unknown; name?: unknown; description?: unknown }) : {};
    if (typeof t.slug !== "string" || !t.slug) return [];
    return [{ value: t.slug, label: typeof t.name === "string" && t.name.trim() ? t.name : t.slug, description: typeof t.description === "string" ? t.description.trim() : "" }];
  });
}

export function shownSteps(def: WizardDefinition, ctx: Ctx): Step[] {
  return def.steps.filter((s) => isShown(s, ctx));
}

export function nextStep(def: WizardDefinition, ctx: Ctx, currentId: string): Step | null {
  const index = def.steps.findIndex((s) => s.id === currentId);
  return def.steps.slice(index + 1).find((s) => isShown(s, ctx)) ?? null;
}

/** A question not answered yet that a later step waits on, by its `when` or as the entry it works on: what follows depends on the answer,
 *  so the step is not the end even while nothing after it shows. A setup may open on one ("One work or several?", every later step being
 *  one branch or the other); a step that sets nothing, or one already answered, is the end when no step shows after it. */
export function opensMore(def: WizardDefinition, ctx: Ctx, step: Step): boolean {
  if ((step.kind !== "option" && step.kind !== "choose") || ctx[step.as]) return false;
  const index = def.steps.findIndex((s) => s.id === step.id);
  return def.steps.slice(index + 1).some((s) => s.when?.ctx === step.as || s.entry === step.as || s.parent === step.as);
}

export function previousStep(def: WizardDefinition, ctx: Ctx, currentId: string): Step | null {
  const index = def.steps.findIndex((s) => s.id === currentId);
  const before = index < 0 ? [] : def.steps.slice(0, index);
  return [...before].reverse().find((s) => isShown(s, ctx)) ?? null;
}

/** The first earlier step still waiting for an answer that this one depends on: a choice or an option that is not optional. Steps past it
 * would run without the entry it picks (a story list with no world to narrow it), so they wait. */
export function blocker(def: WizardDefinition, ctx: Ctx, stepId: string): Step | null {
  const index = def.steps.findIndex((s) => s.id === stepId);
  const before = index < 0 ? [] : def.steps.slice(0, index);
  return before.find((s) => isShown(s, ctx) && ((s.kind === "choose" || s.kind === "option") && !s.optional) && !ctx[s.as]) ?? null;
}

/** The step the address names (or the one blocking it), else the first one shown. */
export function currentStep(def: WizardDefinition, ctx: Ctx, id: string | null): Step | null {
  const shown = shownSteps(def, ctx);
  const asked = shown.find((s) => s.id === id);
  return (asked && (blocker(def, ctx, asked.id) ?? asked)) ?? shown[0] ?? null;
}

/** `${name}` replaced by the choice of that name (empty when nothing was chosen), through strings, lists and objects. */
export function substitute<T>(value: T, ctx: Ctx): T {
  if (typeof value === "string") return value.replace(REF, (_m, name: string) => ctx[name] ?? "") as T;
  if (Array.isArray(value)) return value.map((v) => substitute(v, ctx)) as T;
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, substitute(v, ctx)])) as T;
  }
  return value;
}

/** An object without the keys whose value came out empty: a choice that was skipped narrows nothing and sets nothing. */
export function withoutEmpty(obj: Record<string, unknown> | undefined): Record<string, unknown> {
  return Object.fromEntries(Object.entries(obj ?? {}).filter(([, v]) => v !== "" && v != null));
}

/** A step's `only_with` / `only_without` ({entry_type, field, scope?}) as the entries query's `referenced_by` / `not_referenced_by`:
 *  only the entries that an entry of that type points at in its field (a beat that has lines), or that none does. The query does it in
 *  one go, so a long list is not read a card at a time. A scope value that came out empty narrows nothing, as in a pick's `scope`. */
export function referenceFilter(step: Step, ctx: Ctx): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, as] of [["only_with", "referenced_by"], ["only_without", "not_referenced_by"]] as const) {
    const by = step[key] as { entry_type: string; field: string; scope?: Record<string, string> } | undefined;
    if (by) out[as] = { entry_type: by.entry_type, field: by.field, fields: withoutEmpty(substitute(by.scope, ctx)) };
  }
  return out;
}

/** The entries query behind a `choose` step: entries of its type, narrowed by the earlier choices in `scope` (and `only_with`). */
export function chooseSpec(step: Step, ctx: Ctx): Record<string, unknown> {
  return { entry_type: step.entry_type, fields: withoutEmpty(substitute(step.scope, ctx)), ...referenceFilter(step, ctx), ...ownSort(step) };
}

/** A step's own order (`sort: {by, direction?}`: `created_at`, the order they were made, or a field, numbers as numbers: a beat's
 *  number, a line's order), asked of the entries query so a long list is cut after it is ordered. `"natural"` or none: by title. */
export function ownSort(step: Step): { sort?: { by: string; direction: "asc" | "desc" } } {
  const sort = step.sort as { by?: unknown; direction?: unknown } | string | undefined;
  if (!sort || typeof sort !== "object" || typeof sort.by !== "string" || !sort.by) return {};
  return { sort: { by: sort.by, direction: sort.direction === "desc" ? "desc" : "asc" } };
}

/** What a created entry arrives holding: the step's `create.data` with the choices filled in. */
export function createData(step: Step, ctx: Ctx): Record<string, unknown> {
  return withoutEmpty(substitute(step.create?.data, ctx));
}

/**
 * What a step fills in by itself on an entry it makes: the parent's slug (a list's or gallery's `parent_field`) and its `create` / `add`
 * data with the choices filled in. A form does not ask for these again, even when the type requires them: an empty box posted back
 * would beat the step's value (an actor added to a world's troupe arrived with no world).
 */
export function suppliedData(step: Step, ctx: Ctx): Record<string, unknown> {
  const own = step.kind === "gallery" ? step.add?.data : step.kind === "list" ? step.create_data : step.create?.data;
  const parent = step.parent_field && ctx[step.parent] ? { [step.parent_field]: ctx[step.parent] } : {};
  return { ...withoutEmpty(substitute(own, ctx)), ...parent };
}

/** The entries query behind a `list` or `gallery` step: those whose `parent_field` holds the parent's slug (a gallery may be unscoped). */
export function listSpec(step: Step, ctx: Ctx): Record<string, unknown> {
  // A gallery's `where` keeps only the cards that meet it (a story's sounds of kind ambience); a list's is its scoped kind's own.
  const where = step.kind === "gallery" && Array.isArray(step.where) && step.where.length ? { where: substitute(step.where, ctx) } : {};
  if (!step.parent_field) return { entry_type: step.entry_type, ...where, ...referenceFilter(step, ctx), ...ownSort(step) };
  return { entry_type: step.entry_type, fields: { [step.parent_field]: ctx[step.parent] }, ...where, ...referenceFilter(step, ctx), ...ownSort(step) };
}

export interface AttachedAsset {
  role?: string | null;
  publicUrl?: string | null;
  mimeType?: string | null;
  name?: string | null;
}

/** The picture a card shows: the asset attached in the picture field's role (a linked asset field syncs its role to its key). */
export function cardPicture(assets: AttachedAsset[] | undefined, pictureField: string | undefined): string | null {
  if (!pictureField) return null;
  const hit = (assets ?? []).find((a) => a.role === pictureField && a.publicUrl && (a.mimeType ?? "").startsWith("image/"));
  return hit?.publicUrl ?? null;
}

/** The picture field a pick shows when its step names none: the type's first single asset field that takes pictures (its accept names
 *  images, or it says nothing). A list of pictures (`asset-list`) or a sound is no face for a card. */
export function pictureFieldOf(type: { schemaJson?: { fields?: { key?: string; type?: string; accept?: string | null }[] } | null } | null | undefined): string | undefined {
  const takesPictures = (accept: string | null | undefined) => !accept || /image/i.test(accept);
  return type?.schemaJson?.fields?.find((f) => f.type === "asset" && typeof f.key === "string" && takesPictures(f.accept))?.key;
}

/** The role an asset field's file is attached under: the field's own `role` when its type names one (the artwork `image` is role `featured`), else its key. */
export function fieldRole(type: { schemaJson?: { fields?: { key?: string; role?: string }[] } } | null | undefined, key: string | undefined): string | undefined {
  if (!key) return undefined;
  const field = type?.schemaJson?.fields?.find((f) => f.key === key);
  return typeof field?.role === "string" && field.role ? field.role : key;
}

/** The title a new entry gets: what the person typed, else the file's name without its ending, as words. */
export function titleFor(typed: string, fileName: string): string {
  const own = typed.trim();
  if (own) return own;
  return fileName.replace(/\.[a-z0-9]+$/i, "").replace(/[-_]+/g, " ").trim();
}

/** The sound a card plays: the asset attached in the audio field's role, as the picture is found. */
export function cardAudio(assets: AttachedAsset[] | undefined, audioField: string | undefined): string | null {
  if (!audioField) return null;
  const hit = (assets ?? []).find((a) => a.role === audioField && a.publicUrl && (a.mimeType ?? "").startsWith("audio/"));
  return hit?.publicUrl ?? null;
}

/** What a gallery's upload takes: its own `upload.accept`, else what the entry type's field it fills takes (the field's Accepts setting, so the step
 *  need not say it twice), else a picture. `fields` are the entry type's field definitions. */
export function galleryAccept(step: Step, fields: { key?: string; accept?: string | null }[] = []): string {
  const own = typeof step.upload?.accept === "string" ? step.upload.accept.trim() : "";
  if (own) return own;
  const held = fields.find((f) => f.key === step.upload?.field)?.accept;
  return typeof held === "string" && held.trim() ? held.trim() : "image/*";
}

/** A gallery's generate action as the run step it is: the step's own keys plus the typed prompt as a context value. */
export function generateAsRun(step: Step, promptValue: string | undefined): { run: Step; extra: Ctx } {
  const gen = step.generate ?? {};
  const run: Step = { id: `${step.id}-generate`, kind: "run", title: gen.button ?? "Generate", workflow: gen.workflow, inputs: gen.inputs ?? {}, button: gen.button };
  const extra: Ctx = gen.prompt?.name && promptValue ? { [gen.prompt.name]: promptValue } : {};
  return { run, extra };
}

export interface Check {
  label: string;
  query: Record<string, unknown>;
  op: "gt" | "gte" | "eq" | "lte" | "lt";
  value: number;
}

export function checkSpec(check: Check, ctx: Ctx): Record<string, unknown> {
  return substitute(check.query, ctx);
}

export function passes(op: Check["op"], count: number, value: number): boolean {
  if (op === "gt") return count > value;
  if (op === "gte") return count >= value;
  if (op === "lt") return count < value;
  if (op === "lte") return count <= value;
  return count === value;
}

/** The address of a step with the choices so far. */
export function stepHref(wizardSlug: string, ctx: Ctx, stepId: string | null, extra: Ctx = {}): string {
  const params = new URLSearchParams();
  if (stepId) params.set(STEP_PARAM, stepId);
  for (const [key, value] of Object.entries({ ...ctx, ...extra })) params.set(key, value);
  return `/workspace/setups/${encodeURIComponent(wizardSlug)}?${params.toString()}`;
}

/** A button an entry's page shows to open a setup on that entry (the wizard's `button`). */
export interface WizardButton {
  entryType: string;
  label: string;
  key: string;
  step?: string | null;
  also?: Record<string, string>;
}

/** Where that button goes: the setup with the entry already chosen (and what its fields carry, a line's story), on the step it names. */
export function buttonHref(wizardSlug: string, button: WizardButton, entry: { slug: string; dataJson?: Record<string, unknown> | null }): string {
  const ctx: Ctx = { [button.key]: entry.slug };
  for (const [key, field] of Object.entries(button.also ?? {})) {
    const value = entry.dataJson?.[field];
    if (typeof value === "string" && value.trim()) ctx[key] = value.trim();
  }
  return stepHref(wizardSlug, ctx, button.step ?? null);
}

/** The entry type a context key's entry is of: the `choose` step that sets it names it (an `option` choice is no entry, and neither is a
 *  multi-select step's list: `listKeys`). */
export function entryTypeOf(def: WizardDefinition, key: string): string | undefined {
  return def.steps.find((s) => s.kind === "choose" && s.as === key && s.multiple !== true)?.entry_type;
}

/** The step that sets a list key: a multi-select choose. */
export function listStepOf(def: WizardDefinition, key: string): Step | undefined {
  return def.steps.find((s) => s.kind === "choose" && s.multiple === true && s.as === key);
}

/** A multi-select step's cards come from the workspace's assets (`assets`: the Assets library's filters) instead of an entry type. */
export function picksAssets(step: Step): boolean {
  return step.kind === "choose" && step.multiple === true && !!step.assets && typeof step.assets === "object";
}

/** The Assets library's filters a multi-select step's `assets` may use, with the choices filled in; `unused` is "on no entry yet". */
export const ASSET_FILTERS = ["q", "asset_type", "tag", "collection", "unattached", "unused", "origin"] as const;
export function assetSpec(step: Step, ctx: Ctx): Record<string, string | string[]> {
  const out: Record<string, string | string[]> = {};
  for (const [key, raw] of Object.entries(withoutEmpty(substitute(step.assets ?? {}, ctx)))) {
    if (!(ASSET_FILTERS as readonly string[]).includes(key)) continue;
    out[key] = Array.isArray(raw) ? raw.map(String) : String(raw);
  }
  return out;
}

/** The field types a wizard page draws itself; anything else is edited in the entry's own editor. */
export const SIMPLE_FIELD_TYPES = ["text", "textarea", "markdown", "number", "boolean", "select", "date", "datetime"];

/** Whether a field already holds something an upload would replace (text, an asset id or a list). */
export function hasValue(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "string") return value.trim().length > 0;
  return value !== null && value !== undefined;
}

/** What a `run` step hands the workflow: its `inputs` with the choices filled in, leaving out any that came out empty. */
export function runInputs(step: Step, ctx: Ctx): Record<string, unknown> {
  return withoutEmpty(substitute(step.inputs, ctx));
}

/** A step's error with the form fields it is about (their input names), so the page can mark them. */
export class StepError extends Error {
  fields: string[];
  constructor(message: string, fields: string[] = []) {
    super(message);
    this.fields = fields;
  }
}

/** What a new list row still lacks. A row left entirely empty lacks nothing (it is no row); one with anything in it, or one the person asked to
 * add, needs its name and every required column. Returns the names of what is missing. */
export function missingForNewRow(
  title: string,
  values: Record<string, unknown>,
  required: { key: string; label: string }[],
  asked: boolean,
): { key: string; label: string }[] {
  const touched = !!title || Object.values(values).some((v) => v !== false && hasValue(v));
  if (!touched && !asked) return [];
  return [...(title ? [] : [{ key: "title", label: "Name" }]), ...required.filter((r) => !hasValue(values[r.key]))];
}

/** The context keys a run step hands its workflow (`${key}` in its inputs): the entries its approvals will be about. */
export function inputKeys(step: Step): string[] {
  return [...new Set(Object.values(step.inputs ?? {}).flatMap((v) => (typeof v === "string" ? [...v.matchAll(REF)].map((m) => m[1]) : [])))];
}

export interface ApprovalCard {
  id: string;
  automationSlug?: string | null;
  entryId?: string | null;
  message: string;
  /** The long part of the question (a whole prompt), shown folded under the message. */
  detail?: string | null;
  status: string;
  choices?: string[] | null;
  choice?: string | null;
  imageUrl?: string | null;
  note?: string | null;
  createdAt?: string | null;
  decidedAt?: string | null;
  decidedByName?: string | null;
  /** Boxes to change before approving (the prompt a paid step sends), as asked (lib/approvalFields.ts). */
  fields?: ApprovalField[] | null;
  /** The choice that makes it again: picked with a changed box, the next try starts from the change. */
  redo?: string | null;
  editedFields?: string[];
}

/** The approvals that belong to this step: raised by its workflow, about one of the entries it was given. With no entries given, only
 * the cards about no entry at all: never every card of the workflow. `asked` are the approvals the run this step started is waiting
 * on: those are its own whatever entry they are about. */
export function approvalsOf(cards: ApprovalCard[], workflowSlug: string, entryIds: string[], asked: string[] = []): ApprovalCard[] {
  return cards.filter((c) => c.automationSlug === workflowSlug && (asked.includes(c.id) || (c.entryId ? entryIds.includes(c.entryId) : true)));
}

/** Two field values are the same when they read the same: nothing, "" and null are all nothing. */
export function sameValue(a: unknown, b: unknown): boolean {
  const norm = (v: unknown) => (v === "" || v === undefined ? null : v);
  return JSON.stringify(norm(a)) === JSON.stringify(norm(b));
}
