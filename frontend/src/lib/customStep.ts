// A workflow's custom AI step (`op: "custom"`): the editor shows its output schema as a list of answer fields — name,
// kind, what it's for — and builds the JSON Schema back from them. Pure, so `npm test` covers it (customStep.test.mjs).
// A schema the list can't show (nested objects, enums…) stays editable as JSON instead.

export interface AnswerField {
  name: string;
  kind: AnswerKind;
  description: string;
}

export type AnswerKind = "text" | "number" | "whole number" | "yes/no" | "list of text";

export const ANSWER_KINDS: AnswerKind[] = ["text", "number", "whole number", "yes/no", "list of text"];

const KIND_SCHEMA: Record<AnswerKind, Record<string, unknown>> = {
  text: { type: "string" },
  number: { type: "number" },
  "whole number": { type: "integer" },
  "yes/no": { type: "boolean" },
  "list of text": { type: "array", items: { type: "string" } },
};

/** What the AI may see besides the prompt (the step's `see`), in the editor's words. */
export const SEE_LABELS: Record<string, string> = {
  item: "The entry, asset or resource it runs on",
  attachments: "The entry's attached assets and linked resources",
  images: "The pictures (needs a model that can see images)",
  persona: "The workspace persona and tone",
};

const NAME = /^[a-z][a-z0-9_]*$/;

function kindOf(prop: any): AnswerKind | null {
  if (!prop || typeof prop !== "object") return null;
  const extra = Object.keys(prop).filter((k) => !["type", "items", "description"].includes(k));
  if (extra.length) return null; // limits, enums…: keep the JSON
  if (prop.type === "array")
    return prop.items?.type === "string" && Object.keys(prop.items).length === 1 ? "list of text" : null;
  return (
    (Object.entries(KIND_SCHEMA).find(([, s]) => s.type === prop.type && prop.type !== "array")?.[0] as AnswerKind) ??
    null
  );
}

/** The schema as answer fields, or null when it uses more than the list can show (edit it as JSON then). */
export function fieldsFromSchema(schema: any): AnswerField[] | null {
  if (!schema) return [];
  if (schema.type !== "object" || typeof schema.properties !== "object") return null;
  const required = new Set<string>(schema.required ?? []);
  const fields: AnswerField[] = [];
  for (const [name, prop] of Object.entries<any>(schema.properties)) {
    const kind = kindOf(prop);
    if (!kind || !required.has(name)) return null; // every listed field is asked for
    fields.push({ name, kind, description: prop.description ?? "" });
  }
  const others = Object.keys(schema).filter((k) => !["type", "properties", "required"].includes(k));
  return others.length ? null : fields;
}

/** The JSON Schema for these answer fields (each required). Throws with a message when a field is unusable. */
export function schemaFromFields(fields: AnswerField[]): Record<string, unknown> {
  const named = fields.filter((f) => f.name.trim());
  if (!named.length) throw new Error("Add at least one answer field.");
  const properties: Record<string, unknown> = {};
  for (const f of named) {
    const name = f.name.trim();
    if (!NAME.test(name))
      throw new Error(`Answer field “${name}”: lower-case letters, digits and _ (e.g. caption, tempo_bpm).`);
    if (name in properties) throw new Error(`Answer field “${name}” is listed twice.`);
    properties[name] = {
      ...KIND_SCHEMA[f.kind],
      ...(f.description.trim() ? { description: f.description.trim() } : {}),
    };
  }
  return { type: "object", properties, required: Object.keys(properties) };
}
