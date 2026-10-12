// A workflow's "Process an image" step (`kind: "media"`): which fields each op shows, where the picture comes from,
// and the step's fields read back from the form — checked the way the server checks them, so the editor says what's
// wrong before saving. Pure, so `npm test` covers it (mediaStep.test.mjs).

export const MEDIA_OPS: { op: string; label: string; makesImage: boolean }[] = [
  { op: "resize", label: "Resize", makesImage: true },
  { op: "crop", label: "Crop to a shape", makesImage: true },
  { op: "convert", label: "Convert the format", makesImage: true },
  { op: "grade", label: "Colour grade", makesImage: true },
  { op: "inspect", label: "Inspect (size, sharpness…)", makesImage: false },
  { op: "palette", label: "Find its main colours", makesImage: false },
  { op: "render", label: "Render a template (card, poster, quote…)", makesImage: true },
];

/** What each op takes besides the picture and Attach as (automation_definition.py: MEDIA_OP_ARGS). */
export const OP_FIELDS: Record<string, string[]> = {
  resize: ["width", "height", "fit", "format", "quality"],
  crop: ["aspect", "focus", "format", "quality"],
  convert: ["format", "quality"],
  grade: ["preset", "format", "quality"],
  inspect: [],
  palette: ["colors"],
  render: ["template", "html", "width", "height", "format", "quality"],
};

export const MEDIA_FIELDS = [
  "width",
  "height",
  "fit",
  "aspect",
  "focus",
  "format",
  "quality",
  "preset",
  "colors",
  "template",
  "html",
];
/** The largest side a render may have (services/ai/media/render.py MAX_SIDE). */
export const MAX_RENDER_SIDE = 4000;
export const ASPECTS = ["1:1", "4:5", "3:2", "16:9", "9:16"];
export const GRADE_PRESETS = ["rustic-warm", "warm", "cool", "muted"];

export type SourceMode = "current" | "step" | "role" | "asset";

export const SOURCE_LABELS: Record<SourceMode, string> = {
  current: "The asset this run is about",
  step: "The image an earlier step made",
  role: "The entry's image in a role",
  asset: "A specific asset (id, slug or URL — e.g. ${entry.image})",
};

const STEP_SOURCE = /^\$\{steps\.([^.}]+)\.output\.asset\.id\}$/;
const ASPECT = /^\s*[1-9]\d{0,2}\s*[:x/]\s*[1-9]\d{0,2}\s*$/;
const RANGES: Record<string, [number, number]> = {
  width: [1, 10000],
  height: [1, 10000],
  quality: [1, 100],
  colors: [1, 16],
};

/** A stored `source` as the form shows it: which kind of source, and its one value (a step id, a role, an asset). */
export function sourceChoice(source: unknown): { mode: SourceMode; value: string } {
  const text = typeof source === "string" ? source.trim() : "";
  if (!text || text === "${asset.id}") return { mode: "current", value: "" };
  const step = STEP_SOURCE.exec(text);
  if (step) return { mode: "step", value: step[1] };
  if (text.startsWith("role:")) return { mode: "role", value: text.slice(5).trim() };
  return { mode: "asset", value: text };
}

/** The `source` to store for a form choice, or null for the default (the run's asset). */
export function sourceFromChoice(mode: SourceMode, value: string): string | null {
  const v = value.trim();
  if (mode === "current") return null;
  if (!v)
    throw new Error(
      mode === "step"
        ? "give the earlier step's id"
        : mode === "role"
          ? "give the role, e.g. hero"
          : "give the asset's id or slug",
    );
  if (mode === "step") return `\${steps.${v}.output.asset.id}`;
  if (mode === "role") return `role:${v}`;
  return v;
}

/**
 * The op's fields from the form's text values: numbers as numbers, blanks dropped, the op's rules checked (the same
 * ones the server applies). Throws an Error saying what to fix.
 */
export function mediaFields(op: string, values: Record<string, string | undefined>): Record<string, string | number> {
  const takes = OP_FIELDS[op];
  if (!takes) throw new Error(`unknown image op “${op}”`);
  const out: Record<string, string | number> = {};
  for (const key of takes) {
    const raw = (values[key] ?? "").trim();
    if (!raw) continue;
    if (key in RANGES) {
      const n = Number(raw);
      const [lo, hi] = RANGES[key];
      if (!Number.isInteger(n) || n < lo || n > hi)
        throw new Error(`${key} must be a whole number from ${lo} to ${hi}`);
      out[key] = n;
    } else {
      out[key] = raw;
    }
  }
  if (op === "resize" && !(out.width || out.height)) throw new Error("resize needs a width or a height");
  if (op === "resize" && out.fit === "cover" && !(out.width && out.height))
    throw new Error("“fill the box” needs both a width and a height");
  if (op === "resize" && out.fit === "inside") delete out.fit; // the default
  if (op === "crop" && !ASPECT.test(String(out.aspect ?? "")))
    throw new Error("crop needs a shape like 1:1, 4:5 or 16:9");
  if (op === "crop" && out.focus === "center") delete out.focus; // the default
  if (op === "convert" && !out.format) throw new Error("convert needs a format");
  if (op === "grade" && !out.preset) throw new Error("grade needs a preset");
  if (op === "render") {
    if (Boolean(out.template) === Boolean(out.html))
      throw new Error("render needs a template, or your own HTML — one of them");
    if (Number(out.width) > MAX_RENDER_SIDE || Number(out.height) > MAX_RENDER_SIDE)
      throw new Error(`a render is at most ${MAX_RENDER_SIDE} px on a side`);
  }
  return out;
}

export interface RenderTemplate {
  label: string;
  description: string;
  width: number;
  height: number;
  fields: Record<string, { label: string; required?: boolean }>;
  images: Record<string, { label: string; required?: boolean }>;
}

/** A render step's text or pictures as rows: the template's own names first (blank when unset), then any others the
 * step already has — so choosing a template shows what it takes. */
export function templateRows(names: string[], current: Record<string, unknown> | undefined): Record<string, unknown> {
  const rows: Record<string, unknown> = {};
  for (const name of names) rows[name] = current?.[name] ?? "";
  for (const [name, value] of Object.entries(current ?? {})) if (!(name in rows)) rows[name] = value;
  return rows;
}

/** Drop rows left blank: a render step stores only what it fills in. */
export function filledRows(rows: Record<string, unknown>): Record<string, unknown> | null {
  const kept = Object.fromEntries(Object.entries(rows).filter(([, v]) => v !== "" && v !== null && v !== undefined));
  return Object.keys(kept).length ? kept : null;
}
