/**
 * The entry type's recipe on its pages: the authoring instructions (`instructions`) and the drafts' voice
 * (`enrichment.voice`) get boxes of their own; the JSON textarea holds the rest of the structured contract.
 * `splitRecipe` takes them out for the edit page, `foldRecipe` puts them back on save (and on create, where
 * the New page has a Voice box but no instructions box).
 */

type Json = Record<string, unknown>;

const isObject = (v: unknown): v is Json => v != null && typeof v === "object" && !Array.isArray(v);

/** The stored recipe as the page shows it: the two boxes, and the JSON for the rest ("" when nothing is left). */
export function splitRecipe(recipe: Json | null | undefined): { instructions: string; voice: string; json: string } {
  const { instructions, ...rest } = recipe ?? {};
  let voice = "";
  if (isObject(rest.enrichment) && typeof rest.enrichment.voice === "string") {
    const { voice: v, ...enrichment } = rest.enrichment;
    voice = v as string;
    if (Object.keys(enrichment).length) rest.enrichment = enrichment;
    else delete rest.enrichment;
  }
  return {
    instructions: typeof instructions === "string" ? instructions : "",
    voice,
    json: Object.keys(rest).length ? JSON.stringify(rest, null, 2) : "",
  };
}

/**
 * The recipe JSON to save: `raw` (the textarea) with the boxes folded back in; a blank box removes its key.
 * `instructions` null means the page has no instructions box, so any typed in `raw` stay as they are.
 * Null when `raw` isn't valid JSON — the page then sends it as typed so the server rejects it rather than the
 * edit being silently dropped. A non-object `enrichment` is left alone for the same reason.
 */
export function foldRecipe(raw: string, instructions: string | null, voice: string): string | null {
  let obj: Json = {};
  if (raw.trim()) {
    try {
      obj = JSON.parse(raw);
    } catch {
      return null;
    }
    if (!isObject(obj)) return null;
  }
  if (instructions !== null) {
    const instr = instructions.trim();
    if (instr) obj.instructions = instr;
    else delete obj.instructions;
  }
  if (obj.enrichment == null || isObject(obj.enrichment)) {
    const enrichment: Json = { ...((obj.enrichment as Json) ?? {}) };
    const v = voice.trim();
    if (v) enrichment.voice = v;
    else delete enrichment.voice;
    if (Object.keys(enrichment).length) obj.enrichment = enrichment;
    else delete obj.enrichment;
  }
  return Object.keys(obj).length ? JSON.stringify(obj, null, 2) : "";
}
