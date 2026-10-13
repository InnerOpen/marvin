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
  { op: "extract_text", label: "Read its text (a PDF, a scan or a photo)", makesImage: false },
  { op: "pages", label: "Save PDF pages as pictures", makesImage: true },
  { op: "find_sensitive", label: "Find faces, plates and personal details", makesImage: false },
  { op: "redact", label: "Blur faces, plates and personal details", makesImage: true },
  { op: "zip", label: "Bundle files into a ZIP (with a manifest)", makesImage: true },
  { op: "watermark", label: "Add a watermark (text or a logo)", makesImage: true },
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
  extract_text: ["ocr"],
  pages: ["page", "count", "width", "format", "quality"],
  find_sensitive: ["find"],
  redact: ["boxes", "find", "format", "quality"],
  zip: ["files", "name"],
  watermark: ["text", "logo", "position", "opacity", "size", "format", "quality"],
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
  "ocr",
  "page",
  "count",
  "find",
  "boxes",
  "files",
  "name",
  "text",
  "logo",
  "position",
  "opacity",
  "size",
];
/** Where a watermark goes (services/ai/media/watermark.py POSITIONS). */
export const WATERMARK_POSITIONS: [string, string][] = [
  ["bottom-right", "Bottom right"],
  ["bottom-left", "Bottom left"],
  ["top-right", "Top right"],
  ["top-left", "Top left"],
  ["center", "In the middle"],
  ["tiled", "Tiled across the picture (can't be cropped away)"],
];
/** What find_sensitive / redact can look for (capability.SENSITIVE_KINDS). */
export const SENSITIVE_KINDS = ["face", "plate", "text"];
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
  page: [1, 10000],
  count: [1, 10],
  opacity: [1, 100],
  size: [1, 100],
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
export function mediaFields(op: string, values: Record<string, string | undefined>): Record<string, unknown> {
  const takes = OP_FIELDS[op];
  if (!takes) throw new Error(`unknown image op “${op}”`);
  const out: Record<string, unknown> = {};
  for (const key of takes) {
    const raw = (values[key] ?? "").trim();
    if (!raw) continue;
    if (key in RANGES) {
      const n = Number(raw);
      const [lo, hi] = RANGES[key];
      if (!Number.isInteger(n) || n < lo || n > hi)
        throw new Error(`${key} must be a whole number from ${lo} to ${hi}`);
      out[key] = n;
    } else if (key === "boxes" && raw.startsWith("[")) {
      try {
        out.boxes = JSON.parse(raw);
      } catch {
        throw new Error("what to blur is a list of boxes, e.g. [[0.1, 0.2, 0.3, 0.3]], or a ${steps.<id>.output.regions}");
      }
    } else if (key === "find") {
      const kinds = raw.split(",").map((k) => k.trim().toLowerCase()).filter(Boolean);
      const wrong = kinds.filter((k) => !SENSITIVE_KINDS.includes(k));
      if (wrong.length) throw new Error(`look for ${SENSITIVE_KINDS.join(", ")} — not ${wrong.join(", ")}`);
      if (kinds.length < SENSITIVE_KINDS.length) out.find = kinds; // all of them is the default
    } else {
      out[key] = raw;
    }
  }
  if (op === "extract_text" && out.ocr === "auto") delete out.ocr; // the default
  if (out.format === "pdf" && op !== "render") throw new Error("PDF is for a render (printed); pictures are JPEG, PNG or WebP");
  if (op === "zip" && !out.files) throw new Error("zip needs files, e.g. ${steps.<id>.output.rows}");
  if (op === "watermark" && !out.text && !out.logo) throw new Error("a watermark needs text or a logo");
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
