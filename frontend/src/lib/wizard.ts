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
  kind: "option" | "choose" | "form" | "upload" | "list" | "review";
  title: string;
  help?: string;
  when?: When;
  [key: string]: any;
}

export interface WizardDefinition {
  title: string;
  description?: string;
  steps: Step[];
}

export const STEP_PARAM = "step";
const CTX_NAME = /^[a-z][a-z0-9_]{0,39}$/;
const MAX_VALUE = 200;
const REF = /\$\{([^}]*)\}/g;

/** The choices so far, from the address: every parameter but `step` whose name is a context name. */
export function readCtx(params: URLSearchParams): Ctx {
  const ctx: Ctx = {};
  for (const [key, value] of params.entries()) {
    if (key !== STEP_PARAM && CTX_NAME.test(key) && value.trim()) ctx[key] = value.trim().slice(0, MAX_VALUE);
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

/** The step the address names, else the first one shown. */
export function currentStep(def: WizardDefinition, ctx: Ctx, id: string | null): Step | null {
  return shownSteps(def, ctx).find((s) => s.id === id) ?? shownSteps(def, ctx)[0] ?? null;
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

/** The entries query behind a `list` step: those whose `parent_field` holds the parent's slug. */
export function listSpec(step: Step, ctx: Ctx): Record<string, unknown> {
  return { entry_type: step.entry_type, fields: { [step.parent_field]: ctx[step.parent] } };
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
