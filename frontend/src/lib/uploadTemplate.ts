// "Make an entry for each" on the upload page: after the files are up, each picture is named (AI, else its cleaned file
// name), treated with the template's picture preset when it has one (in the background, POST /assets/apply-preset), and
// then made into an Inbox entry with the template (POST /entries/from-template, previewed first). The choice "none" (the
// default) changes nothing about an upload. Pure, so `npm test` covers it (uploadTemplate.test.mjs).

export interface TemplateChoice {
  /** "<entry type slug>/<template slug>": the dropdown's value. */
  value: string;
  entryType: string;
  entryTypeName: string;
  template: string;
  templateName: string;
  /** The picture preset the template names, and its name (the preset's own, else its slug). */
  picturePreset: string | null;
  presetName: string | null;
  label: string;
}

interface TypeLike {
  slug?: string | null;
  name?: string | null;
  templatesJson?: unknown;
  picturePresetsJson?: unknown;
}

const record = (v: unknown): Record<string, unknown> => (v && typeof v === "object" ? (v as Record<string, unknown>) : {});
const text = (v: unknown): string => (typeof v === "string" ? v : "");

/** Every template of every entry type, as the dropdown lists them ("Artwork: Ornament, treated with Ornament look"). */
export function templateChoices(types: readonly TypeLike[]): TemplateChoice[] {
  const out: TemplateChoice[] = [];
  for (const t of types) {
    const typeSlug = text(t.slug);
    if (!typeSlug || !Array.isArray(t.templatesJson)) continue;
    const presets = new Map<string, string>();
    for (const p of Array.isArray(t.picturePresetsJson) ? t.picturePresetsJson : []) {
      const slug = text(record(p).slug);
      if (slug) presets.set(slug, text(record(p).name) || slug);
    }
    for (const raw of t.templatesJson) {
      const tpl = record(raw);
      const slug = text(tpl.slug);
      if (!slug) continue;
      const preset = text(tpl.picturePreset ?? tpl.picture_preset) || null;
      const presetName = preset ? (presets.get(preset) ?? preset) : null;
      const typeName = text(t.name) || typeSlug;
      const name = text(tpl.name) || slug;
      out.push({
        value: `${typeSlug}/${slug}`,
        entryType: typeSlug,
        entryTypeName: typeName,
        template: slug,
        templateName: name,
        picturePreset: preset,
        presetName,
        label: `${typeName}: ${name}${presetName ? `, treated with ${presetName}` : ""}`,
      });
    }
  }
  return out;
}

/** The choice a dropdown value names; null for "none" (or a value no template has: nothing is made). */
export function chosen(choices: readonly TemplateChoice[], value: string | null | undefined): TemplateChoice | null {
  if (!value) return null;
  return choices.find((c) => c.value === value) ?? null;
}

/** A file's name as a picture's name when nothing better is known: "IMG_4491.jpeg" → "IMG 4491". */
export function cleanFileName(fileName: string): string {
  const base = fileName.replace(/\.[a-z0-9]{2,5}$/i, "");
  const cleaned = base.replace(/[_\s]+/g, " ").replace(/\s*-\s*/g, " ").replace(/\s+/g, " ").trim();
  return cleaned || base || fileName;
}

/** What a picture is called after describing: the AI's short name, else its cleaned file name (`named: false`: the
 *  entry is then tagged "Needs a name" by the server, as its title is only a file name). */
export function pictureName(described: { name?: unknown } | null | undefined, fileName: string): { name: string; named: boolean } {
  const fromAi = typeof described?.name === "string" ? described.name.trim().replace(/^["']|["']$/g, "").slice(0, 120) : "";
  return fromAi ? { name: fromAi, named: true } : { name: cleanFileName(fileName), named: false };
}

/** The upload page's batch options that would treat a picture a second time: off while a template with a preset is
 *  chosen (its preset does the treating, and the original is kept as the treated picture's source anyway). */
export function batchAdjustAllowed(choice: TemplateChoice | null): boolean {
  return !choice?.picturePreset;
}

export interface JobLike {
  state?: string;
  done?: number;
  total?: number;
  failed?: number;
  errors?: string[];
  text?: string;
}

/** A treatment job in words, for the progress line. */
export function jobLine(job: JobLike | null | undefined): string {
  if (!job) return "";
  const total = job.total ?? 0;
  if (job.state === "queued") return `Waiting for another treatment to finish before these ${total}…`;
  if (job.state === "running") return `Treating ${Math.min((job.done ?? 0) + 1, total)} of ${total}…`;
  if (job.state === "failed") return `The treatment stopped: ${job.errors?.[0] ?? "unknown error"}`;
  const failed = job.failed ?? 0;
  return failed ? `Treated ${total - failed} of ${total}; ${failed} could not be: ${job.errors?.[0] ?? ""}` : `Treated all ${total}.`;
}

/** Whether a job is over (done or failed). */
export function jobOver(job: JobLike | null | undefined): boolean {
  return job?.state === "done" || job?.state === "failed";
}
