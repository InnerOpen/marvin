// Picture presets on the entry type page (pages/workspace/entry-types/[id].astro): the form <-> preset mapping, the steps in
// words, the sliders' scales and the approximate preview. The shapes and ranges follow the server
// (schemas/platform/picture_presets.py, services/ai/media/transforms.py), which checks a preset again when it is saved.
// No imports: `npm test` loads this file with plain `node --test`.

export const PRESET_OPS = ["crop", "resize", "grade", "convert"] as const;
export const MAX_PRESET_STEPS = 12;
export const ASPECTS = ["1:1", "4:5", "3:4", "2:3", "16:9", "3:2"] as const;
export const FORMATS = ["jpeg", "webp", "png"] as const;
/** The built-in named grades (transforms.GRADE_PRESETS): what each sets, for the preview. */
export const GRADES: Record<string, Partial<Record<GradeSetting, number>>> = {
  warm: { warmth: 1.08, contrast: 1.05, saturation: 1.0, brightness: 1.0, vignette: 0 },
  cool: { warmth: 0.92, contrast: 1.05, saturation: 0.98, brightness: 1.0, vignette: 0 },
  muted: { warmth: 1.0, contrast: 0.96, saturation: 0.82, brightness: 1.0, vignette: 0.1 },
  "rustic-warm": { warmth: 1.1, contrast: 1.12, saturation: 0.92, brightness: 0.98, vignette: 0.18 },
};

export type GradeSetting = "brightness" | "contrast" | "saturation" | "warmth" | "vignette";
export const GRADE_SETTINGS: GradeSetting[] = ["brightness", "contrast", "saturation", "warmth", "vignette"];

/** Each grade slider: its range in the form's units (percent) and the factor at 0. brightness, contrast and saturation go
 *  -50%..+100% (factor 0.5..2), warmth -50..+50 (0.5..1.5, above 1 warmer), vignette 0..100% (0..1). */
export const SLIDERS: Record<GradeSetting, { min: number; max: number; neutral: number }> = {
  brightness: { min: -50, max: 100, neutral: 1 },
  contrast: { min: -50, max: 100, neutral: 1 },
  saturation: { min: -50, max: 100, neutral: 1 },
  warmth: { min: -50, max: 50, neutral: 1 },
  vignette: { min: 0, max: 100, neutral: 0 },
};

const SLUG = /^[a-z0-9][a-z0-9-]*$/;
const ASPECT = /^\s*([1-9]\d{0,2})\s*[:x/]\s*([1-9]\d{0,2})\s*$/;
const FOCUS_POINT = /^\s*([01](?:\.\d+)?|\.\d+)\s*,\s*([01](?:\.\d+)?|\.\d+)\s*$/;

/** One treatment as stored (camelCase over the API; every key is one word). */
export interface PresetStep {
  op: string;
  aspect?: string;
  focus?: string;
  width?: number;
  height?: number;
  fit?: "inside" | "cover";
  preset?: string;
  brightness?: number;
  contrast?: number;
  saturation?: number;
  warmth?: number;
  vignette?: number;
  format?: string;
  quality?: number;
  [key: string]: unknown;
}

export interface PicturePreset {
  slug: string;
  name: string;
  description?: string | null;
  steps: PresetStep[];
}

/** The editor's values, as the inputs hold them. Sliders hold the form's units (percent); a box left empty is "". */
export interface PresetForm {
  slug: string;
  name: string;
  description: string;
  crop: boolean;
  /** One of ASPECTS, or "other" (then `aspectOther` holds it). */
  aspect: string;
  aspectOther: string;
  focus: "center" | "subject" | "point";
  focusX: number;
  focusY: number;
  resize: boolean;
  width: string;
  height: string;
  fit: "inside" | "cover";
  grade: boolean;
  /** A named grade, or "" for none. */
  gradePreset: string;
  brightness: number;
  contrast: number;
  saturation: number;
  warmth: number;
  vignette: number;
  /** "" keeps the picture's own format. */
  format: string;
  quality: string;
}

const round2 = (n: number) => Math.round(n * 100) / 100;
const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));

/** A slider's value (percent) as the factor the server takes: 0% is 1 (vignette: 0), +10% is 1.1, vignette 18% is 0.18. */
export function sliderToFactor(setting: GradeSetting, percent: number): number {
  return round2(SLIDERS[setting].neutral + percent / 100);
}

/** A factor as the slider shows it: snapped to whole percent and kept in the slider's range, as a range input would. */
export function factorToSlider(setting: GradeSetting, factor: number): number {
  const { min, max, neutral } = SLIDERS[setting];
  return clamp(Math.round((factor - neutral) * 100), min, max);
}

/** A slider's value for its label: "+10%", "-5%", "0%" (vignette "18%"). */
export function sliderLabel(setting: GradeSetting, percent: number): string {
  return setting === "vignette" || percent <= 0 ? `${percent}%` : `+${percent}%`;
}

/** An aspect as "w:h" ("4x5" and " 4 / 5" read as 4:5), or null when it is not one. */
export function normalAspect(text: string): string | null {
  const m = ASPECT.exec(text ?? "");
  return m ? `${Number(m[1])}:${Number(m[2])}` : null;
}

/** A fixed focus point "x,y" as numbers (0..1 from the left and from the top), or null for center, subject or not a point. */
export function focusPoint(text: string | undefined): [number, number] | null {
  const m = FOCUS_POINT.exec(text ?? "");
  if (!m) return null;
  const x = Number(m[1]);
  const y = Number(m[2]);
  return x <= 1 && y <= 1 ? [x, y] : null;
}

/** The editor's values for a new preset: every treatment off, sliders at 0. */
export function blankForm(): PresetForm {
  return {
    slug: "",
    name: "",
    description: "",
    crop: false,
    aspect: "1:1",
    aspectOther: "",
    focus: "center",
    focusX: 0.5,
    focusY: 0.5,
    resize: false,
    width: "",
    height: "",
    fit: "inside",
    grade: false,
    gradePreset: "",
    brightness: 0,
    contrast: 0,
    saturation: 0,
    warmth: 0,
    vignette: 0,
    format: "",
    quality: "",
  };
}

/** The editor's values for a preset, or a new one (`null`). A step the form has no place for is not shown: check `formFits`. */
export function formFromPreset(preset: PicturePreset | null): PresetForm {
  const form = blankForm();
  if (!preset) return form;
  form.slug = preset.slug ?? "";
  form.name = preset.name ?? "";
  form.description = preset.description ?? "";
  for (const step of preset.steps ?? []) {
    if (step.op === "crop") {
      form.crop = true;
      const aspect = normalAspect(String(step.aspect ?? ""));
      if (aspect && (ASPECTS as readonly string[]).includes(aspect)) form.aspect = aspect;
      else {
        form.aspect = "other";
        form.aspectOther = String(step.aspect ?? "");
      }
      const focus = String(step.focus ?? "center").trim();
      const point = focusPoint(focus);
      if (focus === "subject") form.focus = "subject";
      else if (point) {
        form.focus = "point";
        [form.focusX, form.focusY] = point.map(round2);
      }
    } else if (step.op === "resize") {
      form.resize = true;
      form.width = step.width == null ? "" : String(step.width);
      form.height = step.height == null ? "" : String(step.height);
      form.fit = step.fit === "cover" ? "cover" : "inside";
    } else if (step.op === "grade") {
      form.grade = true;
      form.gradePreset = (step.preset ?? "").trim();
      for (const s of GRADE_SETTINGS) {
        if (typeof step[s] === "number") form[s] = factorToSlider(s, step[s] as number);
      }
    } else if (step.op === "convert") {
      form.format = String(step.format ?? "");
      form.quality = step.quality == null ? "" : String(step.quality);
    }
  }
  return form;
}

/** The step as compared: no empty keys, the defaults left out (focus center, fit inside, a neutral setting on a grade with no
 *  named grade), the aspect and focus written one way, the keys in order. Two steps with the same canonical form treat a
 *  picture the same way. */
function canonical(step: PresetStep): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  const named = typeof step.preset === "string" && step.preset.trim() !== "";
  for (const key of Object.keys(step).sort()) {
    let value = step[key];
    if (value == null || value === "") continue;
    if (key === "preset") value = String(value).trim();
    if (key === "aspect") value = normalAspect(String(value)) ?? value;
    if (key === "focus") {
      const point = focusPoint(String(value));
      value = point ? point.join(",") : String(value).trim();
      if (value === "center") continue;
    }
    if (key === "fit" && value === "inside") continue;
    if (step.op === "grade" && !named && (GRADE_SETTINGS as string[]).includes(key) && value === SLIDERS[key as GradeSetting].neutral) continue;
    out[key] = value;
  }
  return out;
}

const sameStep = (a: PresetStep, b: PresetStep) => JSON.stringify(canonical(a)) === JSON.stringify(canonical(b));

/** The steps for the editor's values, in the form's order (crop, resize, grade, format); only what is switched on, and a grade
 *  slider at 0 left out. `stored` is the preset being edited: a step that treats a picture as its stored one does is kept as
 *  stored ("4x5" stays "4x5"), so the pictures made with it before are reused rather than made again. */
export function stepsFromForm(form: PresetForm, stored?: PicturePreset | null): PresetStep[] {
  const steps: PresetStep[] = [];
  if (form.crop) {
    const step: PresetStep = { op: "crop", aspect: form.aspect === "other" ? form.aspectOther.trim() : form.aspect };
    if (form.focus === "subject") step.focus = "subject";
    else if (form.focus === "point") step.focus = `${round2(form.focusX)},${round2(form.focusY)}`;
    steps.push(step);
  }
  if (form.resize) {
    const step: PresetStep = { op: "resize" };
    const size = (s: string) => (s.trim() === "" ? undefined : Number(s.trim()));
    const width = size(form.width);
    const height = size(form.height);
    if (width !== undefined) step.width = width;
    if (height !== undefined) step.height = height;
    if (form.fit === "cover") step.fit = "cover";
    steps.push(step);
  }
  if (form.grade) {
    const step: PresetStep = { op: "grade" };
    if (form.gradePreset.trim()) step.preset = form.gradePreset.trim();
    for (const s of GRADE_SETTINGS) {
      if (form[s] !== 0) step[s] = sliderToFactor(s, form[s]);
    }
    steps.push(step);
  }
  if (form.format) {
    const step: PresetStep = { op: "convert", format: form.format };
    if (form.quality.trim() !== "") step.quality = Number(form.quality.trim());
    steps.push(step);
  }
  const before = stored?.steps ?? [];
  return steps.map((step) => before.find((s) => s.op === step.op && sameStep(s, step)) ?? step);
}

/** The preset for the editor's values (see stepsFromForm). */
export function presetFromForm(form: PresetForm, stored?: PicturePreset | null): PicturePreset {
  return {
    slug: form.slug.trim(),
    name: form.name.trim(),
    description: form.description.trim() || null,
    steps: stepsFromForm(form, stored),
  };
}

/** True when the form shows these steps as they are: each treatment at most once, in the form's order, no format on a crop,
 *  resize or grade, and every value one the form's inputs can hold (a slider snaps to whole percent and stops at its ends).
 *  Otherwise the page edits the steps as JSON instead of changing them. */
export function formFits(steps: PresetStep[]): boolean {
  if (!Array.isArray(steps)) return false;
  const order = steps.map((s) => (PRESET_OPS as readonly string[]).indexOf(s?.op));
  if (order.some((i, n) => i < 0 || (n > 0 && i <= order[n - 1]))) return false;
  const after = stepsFromForm(formFromPreset({ slug: "", name: "", steps }));
  return after.length === steps.length && after.every((step, i) => sameStep(step, steps[i]));
}

/** One step in words, as the server names it: "crop 1:1 at 0.25,0.5", "resize 800×auto", "grade warm brightness 1.2", "webp". */
export function stepWords(step: PresetStep): string {
  const format = step.format ? ` ${step.format}` : "";
  if (step.op === "resize") return `resize ${step.width || "auto"}×${step.height || "auto"}${format}`;
  if (step.op === "crop") {
    const focus = String(step.focus || "center").trim();
    return `crop ${step.aspect}${focus === "center" ? "" : focus === "subject" ? " subject" : ` at ${focus}`}${format}`;
  }
  if (step.op === "grade") {
    const settings = GRADE_SETTINGS.filter((s) => step[s] != null).map((s) => `${s} ${step[s]}`);
    return [["grade", step.preset, ...settings].filter(Boolean).join(" "), step.format].filter(Boolean).join(" ");
  }
  if (step.op === "convert") return String(step.format ?? "convert");
  return String(step.op);
}

/** The steps in words: "crop 1:1, grade brightness 1.2, webp". */
export function stepsWords(steps: PresetStep[]): string {
  return (steps ?? []).map(stepWords).join(", ");
}

const isWhole = (s: string, lo: number, hi: number) => /^\d+$/.test(s.trim()) && Number(s) >= lo && Number(s) <= hi;

/** What is wrong with the editor's values, in words; empty when the preset can be saved (the server checks it again). */
export function validateForm(form: PresetForm): string[] {
  const errors: string[] = [];
  if (!form.name.trim()) errors.push("Give the preset a name.");
  const slug = form.slug.trim();
  if (!SLUG.test(slug) || slug.length > 64) errors.push("The slug is lower-case letters, digits and dashes (it starts with a letter or digit).");
  if (!form.crop && !form.resize && !form.grade && !form.format) {
    errors.push("Switch on at least one treatment: crop, resize, colour or a format.");
  }
  if (form.crop) {
    const aspect = form.aspect === "other" ? form.aspectOther : form.aspect;
    if (!normalAspect(aspect)) errors.push("Crop: the shape is two numbers like 4:5 or 16:9.");
    if (form.focus === "point" && ![form.focusX, form.focusY].every((n) => Number.isFinite(n) && n >= 0 && n <= 1)) {
      errors.push("Crop: the point is from 0 to 1 across and down.");
    }
  }
  if (form.resize) {
    const width = form.width.trim();
    const height = form.height.trim();
    if (!width && !height) errors.push("Resize: give a width, a height or both.");
    if ((width && !isWhole(width, 1, 10000)) || (height && !isWhole(height, 1, 10000))) {
      errors.push("Resize: a width or height is a whole number of pixels, 1 to 10000.");
    }
    if (form.fit === "cover" && !(width && height)) errors.push("Resize: filling the box needs both a width and a height.");
  }
  if (form.grade && !form.gradePreset.trim() && GRADE_SETTINGS.every((s) => form[s] === 0)) {
    errors.push("Colour: pick a named look or move a slider.");
  }
  if (form.format && form.quality.trim() && !isWhole(form.quality, 1, 100)) errors.push("Quality is a whole number from 1 to 100.");
  return errors;
}

/** The steps typed as JSON (a list, in order), or what is wrong with them. The server checks each step's settings. */
export function parseSteps(text: string): { steps: PresetStep[] } | { error: string } {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return { error: "The steps are not valid JSON." };
  }
  if (!Array.isArray(value) || value.length === 0) return { error: "The steps are a list with at least one step, like [{\"op\": \"crop\", \"aspect\": \"1:1\"}]." };
  if (value.length > MAX_PRESET_STEPS) return { error: `A preset has at most ${MAX_PRESET_STEPS} steps.` };
  for (const [i, step] of value.entries()) {
    if (!step || typeof step !== "object" || Array.isArray(step) || !(PRESET_OPS as readonly string[]).includes((step as PresetStep).op)) {
      return { error: `Step ${i + 1} needs an "op": crop, resize, grade or convert.` };
    }
  }
  return { steps: value as PresetStep[] };
}

/** The list with `preset` in place of the one with slug `replacing` (or added at the end when `replacing` is null). */
export function putPreset(list: PicturePreset[], preset: PicturePreset, replacing: string | null): PicturePreset[] {
  const at = replacing == null ? -1 : list.findIndex((p) => p.slug === replacing);
  return at < 0 ? [...list, preset] : list.map((p, i) => (i === at ? preset : p));
}

/** How the preview shows the steps with CSS (approximate): the crop's shape and where it sits, the grade as filters, a warm or
 *  cool tint and a vignette. A named grade the page doesn't know (a workspace's) shows only its own settings. */
export interface PreviewLook {
  aspectRatio: string | null;
  objectPosition: string;
  filter: string;
  tint: { color: string; opacity: number } | null;
  vignette: number;
}

export function previewLook(steps: PresetStep[]): PreviewLook {
  const look: PreviewLook = { aspectRatio: null, objectPosition: "50% 50%", filter: "none", tint: null, vignette: 0 };
  const grade: Record<GradeSetting, number> = { brightness: 1, contrast: 1, saturation: 1, warmth: 1, vignette: 0 };
  for (const step of steps ?? []) {
    if (step.op === "crop") {
      const aspect = normalAspect(String(step.aspect ?? ""));
      if (aspect) look.aspectRatio = aspect.replace(":", " / ");
      const point = focusPoint(String(step.focus ?? ""));
      look.objectPosition = point ? `${Math.round(point[0] * 100)}% ${Math.round(point[1] * 100)}%` : "50% 50%";
    } else if (step.op === "grade") {
      const values = { ...(step.preset ? GRADES[step.preset.trim()] ?? {} : {}) };
      for (const s of GRADE_SETTINGS) if (typeof step[s] === "number") values[s] = step[s] as number;
      // Grades stack: each multiplies what the one before did (vignette: the stronger one).
      for (const s of GRADE_SETTINGS) {
        const v = values[s];
        if (v == null) continue;
        grade[s] = s === "vignette" ? Math.max(grade[s], v) : grade[s] * v;
      }
    }
  }
  const filters = [
    grade.brightness !== 1 && `brightness(${round2(grade.brightness)})`,
    grade.contrast !== 1 && `contrast(${round2(grade.contrast)})`,
    grade.saturation !== 1 && `saturate(${round2(grade.saturation)})`,
  ].filter(Boolean);
  look.filter = filters.length ? filters.join(" ") : "none";
  if (grade.warmth !== 1) {
    look.tint = { color: grade.warmth > 1 ? "rgb(255 140 40)" : "rgb(40 120 255)", opacity: round2(Math.min(0.6, Math.abs(grade.warmth - 1) * 1.5)) };
  }
  look.vignette = round2(clamp(grade.vignette, 0, 1));
  return look;
}
