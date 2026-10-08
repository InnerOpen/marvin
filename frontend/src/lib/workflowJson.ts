/**
 * The workflow editor's JSON view (pages/automation/workflows.astro), kept pure so `npm test` covers it
 * (see workflowJson.test.mjs).
 *
 * The JSON view takes either shape:
 *  - a bare definition: `{"trigger": {…}, "conditions": […], "actions": […]}`
 *  - a whole workflow document: `{"name": "…", "slug": "…", "definition": {…}}` — what "Copy JSON" on a
 *    workflow gives you, and close to what the API returns (ids and other read-only keys are ignored).
 *
 * `enabled` is never taken from pasted JSON: a new workflow stays disabled until someone ticks Enabled.
 */

type Json = Record<string, unknown>;

export type ParsedWorkflowJson =
  | {
      ok: true;
      /** What to put in the editor (and save as the workflow's `definition`). */
      definition: Json;
      /** The workflow name, when the JSON carried one. */
      name?: string;
      /** The slug, when the JSON carried one (only a new workflow can use it). */
      slug?: string;
      /** Top-level keys that were dropped (e.g. `enabled`, `id`). */
      ignored: string[];
    }
  | { ok: false; error: string };

/** The shape hint shown with every "this isn't a workflow" error. */
export const ACCEPTED_SHAPES =
  'Paste a definition like {"trigger": {…}, "actions": […]} or a whole workflow like {"name": "…", "definition": {…}}.';

// Keys of a whole workflow document that the editor uses; every other top-level key is ignored.
const DOCUMENT_KEYS = new Set(["name", "slug", "definition"]);
// Keys a bare definition can carry by mistake that belong to the workflow, not the definition (someone
// writing `{"name": …, "trigger": …, "actions": …}` means the workflow's name). The definition has none
// of these (schemas/group/automation_definition.py).
const WORKFLOW_KEYS_IN_DEFINITION = ["name", "slug", "enabled"];

const isObject = (v: unknown): v is Json => typeof v === "object" && v !== null && !Array.isArray(v);

/** Read the JSON view's text as a workflow (see the module doc for the shapes it takes). */
export function parseWorkflowJson(text: string): ParsedWorkflowJson {
  const raw = text.trim();
  if (!raw) return { ok: false, error: `The JSON is empty. ${ACCEPTED_SHAPES}` };
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch (e) {
    return { ok: false, error: `Invalid JSON: ${e instanceof Error ? e.message : String(e)}` };
  }
  if (!isObject(parsed)) return { ok: false, error: `The JSON must be an object. ${ACCEPTED_SHAPES}` };

  let definition: Json;
  let ignored: string[];
  if ("definition" in parsed) {
    if (!isObject(parsed.definition)) return { ok: false, error: '"definition" must be an object.' };
    definition = parsed.definition;
    ignored = Object.keys(parsed).filter((key) => !DOCUMENT_KEYS.has(key));
  } else {
    if (!("trigger" in parsed) && !("actions" in parsed)) {
      return {
        ok: false,
        error: `This doesn't look like a workflow — it has no "trigger" or "actions". ${ACCEPTED_SHAPES}`,
      };
    }
    definition = { ...parsed };
    for (const key of WORKFLOW_KEYS_IN_DEFINITION) delete definition[key];
    ignored = "enabled" in parsed ? ["enabled"] : [];
  }

  for (const key of ["name", "slug"]) {
    if (parsed[key] !== undefined && parsed[key] !== null && typeof parsed[key] !== "string") {
      return { ok: false, error: `"${key}" must be a string.` };
    }
  }
  const shapeError = definitionShapeError(definition);
  if (shapeError) return { ok: false, error: shapeError };

  const name = typeof parsed.name === "string" && parsed.name.trim() ? parsed.name.trim() : undefined;
  const slug = typeof parsed.slug === "string" && parsed.slug.trim() ? parsed.slug.trim() : undefined;
  return { ok: true, definition, ...(name ? { name } : {}), ...(slug ? { slug } : {}), ignored };
}

/** The obvious type mistakes, caught before the builder tries to show them (the API checks the rest). */
function definitionShapeError(def: Json): string | null {
  if (def.trigger !== undefined && def.trigger !== null && !isObject(def.trigger)) {
    return '"trigger" must be an object such as {"type": "event", "event": "entry_published"}.';
  }
  if (def.actions !== undefined && !Array.isArray(def.actions)) return '"actions" must be a list of steps.';
  if (Array.isArray(def.actions) && def.actions.some((a) => !isObject(a)))
    return 'Each step in "actions" must be an object.';
  if (
    def.conditions !== undefined &&
    def.conditions !== null &&
    !Array.isArray(def.conditions) &&
    !isObject(def.conditions)
  ) {
    return '"conditions" must be a list of conditions.';
  }
  return null;
}

/** A workflow as portable JSON — name and definition, no ids or enabled state — to paste into another workspace. */
export function workflowDocument(wf: { name: string; definition?: Json | null }): { name: string; definition: Json } {
  return { name: wf.name, definition: wf.definition ?? {} };
}

const isAbsent = (v: unknown) =>
  v === undefined ||
  v === null ||
  v === false ||
  v === "" ||
  (Array.isArray(v) && !v.length) ||
  (isObject(v) && !Object.keys(v).length);

/**
 * Where two definitions differ, as readable paths (`actions[0].op`). Used to check that the guided builder
 * can show a definition: load it, read it back, and compare. A key missing on one side matches an empty value
 * on the other (`[]`, `{}`, `""`, `false`, `null`), since the builder writes those defaults; any other
 * difference — a changed value, a dropped key, a number read back as text — is reported.
 */
export function definitionDifferences(a: unknown, b: unknown, path = ""): string[] {
  if (a == null || b == null) return isAbsent(a) && isAbsent(b) ? [] : [path || "(definition)"];
  if (Array.isArray(a) && Array.isArray(b)) {
    const out: string[] = [];
    for (let i = 0; i < Math.max(a.length, b.length); i++) {
      // A missing element never matches: a dropped step is a difference even if the step was empty.
      if (i >= a.length || i >= b.length) out.push(`${path}[${i}]`);
      else out.push(...definitionDifferences(a[i], b[i], `${path}[${i}]`));
    }
    return out;
  }
  if (isObject(a) && isObject(b)) {
    const keys = [...new Set([...Object.keys(a), ...Object.keys(b)])];
    return keys.flatMap((key) => definitionDifferences(a[key], b[key], path ? `${path}.${key}` : key));
  }
  return Object.is(a, b) ? [] : [path || "(definition)"];
}
