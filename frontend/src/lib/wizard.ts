/**
 * Wizards: the pure part. A package ships a wizard as data (see the backend's services/blueprints/wizards.py); this decides which steps
 * show, what the next one is, and what each step asks the entries API. Where the person is rides in the page's address (`?step=…&world=…`):
 * the context is the set of choices so far, so a wizard keeps nothing of its own and can be left and picked up again.
 */

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
  /** The button at the end that opens what was made: `entry` is a key a choose step set. */
  open?: { entry: string; label: string };
}

/** A step is done when the data says so: a choice or option that is set. Other kinds have no mark of their own (they can be redone). */
export function isDone(step: Step, ctx: Ctx): boolean {
  return (step.kind === "choose" || step.kind === "option") && !!ctx[step.as];
}

export const STEP_PARAM = "step";
/** What a page says after a step did something: a code in the address, never free text (a link could not spoof a message). */
export const NOTICES: Record<string, string> = {
  started: "Started. Anything the workflow asks you appears below as it runs; when it is done, go on to the next step.",
  approved: "Approved. The workflow goes on; anything else it asks appears here.",
  denied: "Denied. The workflow stops there; run it again if you change your mind.",
  chosen: "Your choice was taken. The workflow goes on; anything else it asks appears here.",
  added: "Added.",
};
/** Address parameters that are not choices: the step asked for, and the line to show after a step that started something. */
export const NOTICE_PARAM = "notice";
const CTX_NAME = /^[a-z][a-z0-9_]{0,39}$/;
const MAX_VALUE = 200;
const REF = /\$\{([^}]*)\}/g;

/** The choices so far, from the address: every parameter but `step` whose name is a context name. */
export function readCtx(params: URLSearchParams): Ctx {
  const ctx: Ctx = {};
  for (const [key, value] of params.entries()) {
    if (key !== STEP_PARAM && key !== NOTICE_PARAM && CTX_NAME.test(key) && value.trim()) ctx[key] = value.trim().slice(0, MAX_VALUE);
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

/** The context without the keys the steps after `stepId` set. */
export function withoutLater(def: WizardDefinition, ctx: Ctx, stepId: string): Ctx {
  const drop = new Set(keysAfter(def, stepId));
  return Object.fromEntries(Object.entries(ctx).filter(([k]) => !drop.has(k)));
}

/** The option step that sets `key`, if any. */
export function optionStepOf(def: WizardDefinition, key: string): Step | undefined {
  return def.steps.find((s) => s.kind === "option" && s.as === key);
}

export function shownSteps(def: WizardDefinition, ctx: Ctx): Step[] {
  return def.steps.filter((s) => isShown(s, ctx));
}

export function nextStep(def: WizardDefinition, ctx: Ctx, currentId: string): Step | null {
  const index = def.steps.findIndex((s) => s.id === currentId);
  return def.steps.slice(index + 1).find((s) => isShown(s, ctx)) ?? null;
}

export function previousStep(def: WizardDefinition, ctx: Ctx, currentId: string): Step | null {
  const index = def.steps.findIndex((s) => s.id === currentId);
  const before = index < 0 ? [] : def.steps.slice(0, index);
  return [...before].reverse().find((s) => isShown(s, ctx)) ?? null;
}

/** The first earlier step still waiting for an answer that this one depends on: a choice that is not optional, or an option. Steps past it
 * would run without the entry it picks (a story list with no world to narrow it), so they wait. */
export function blocker(def: WizardDefinition, ctx: Ctx, stepId: string): Step | null {
  const index = def.steps.findIndex((s) => s.id === stepId);
  const before = index < 0 ? [] : def.steps.slice(0, index);
  return before.find((s) => isShown(s, ctx) && ((s.kind === "choose" && !s.optional) || s.kind === "option") && !ctx[s.as]) ?? null;
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

/** The entries query behind a `choose` step: entries of its type, narrowed by the earlier choices in `scope`. */
export function chooseSpec(step: Step, ctx: Ctx): Record<string, unknown> {
  return { entry_type: step.entry_type, fields: withoutEmpty(substitute(step.scope, ctx)) };
}

/** What a created entry arrives holding: the step's `create.data` with the choices filled in. */
export function createData(step: Step, ctx: Ctx): Record<string, unknown> {
  return withoutEmpty(substitute(step.create?.data, ctx));
}

/** The entries query behind a `list` or `gallery` step: those whose `parent_field` holds the parent's slug (a gallery may be unscoped). */
export function listSpec(step: Step, ctx: Ctx): Record<string, unknown> {
  if (!step.parent_field) return { entry_type: step.entry_type };
  return { entry_type: step.entry_type, fields: { [step.parent_field]: ctx[step.parent] } };
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
  return `/workspace/wizards/${encodeURIComponent(wizardSlug)}?${params.toString()}`;
}

/** The entry type a context key's entries are of: the `choose` step that sets it names it (an `option` choice is no entry). */
export function entryTypeOf(def: WizardDefinition, key: string): string | undefined {
  return def.steps.find((s) => s.kind === "choose" && s.as === key)?.entry_type;
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
  status: string;
  choices?: string[] | null;
  choice?: string | null;
  imageUrl?: string | null;
  note?: string | null;
  createdAt?: string | null;
  decidedAt?: string | null;
  decidedByName?: string | null;
}

/** The approvals that belong to this step: raised by its workflow, about one of the entries it was given. With no entries given, only
 * the cards about no entry at all: never every card of the workflow. */
export function approvalsOf(cards: ApprovalCard[], workflowSlug: string, entryIds: string[]): ApprovalCard[] {
  return cards.filter((c) => c.automationSlug === workflowSlug && (c.entryId ? entryIds.includes(c.entryId) : true));
}

/** Two field values are the same when they read the same: nothing, "" and null are all nothing. */
export function sameValue(a: unknown, b: unknown): boolean {
  const norm = (v: unknown) => (v === "" || v === undefined ? null : v);
  return JSON.stringify(norm(a)) === JSON.stringify(norm(b));
}
