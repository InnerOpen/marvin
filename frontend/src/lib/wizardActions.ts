/** What posting a wizard step does. Returns the choices after it and whether to stay on the step (a list can add one after another). */

import { acceptKind, isKind } from "./acceptKind";
import { type Ctx, type Step, StepError, type WizardDefinition, entryTypeOf, fieldRole, galleryAccept, generateAsRun, hasValue, listSpec, missingForNewRow, runInputs, sameValue, suppliedData, titleFor, withoutLater } from "./wizard";
import { MAX_TEXT_UPLOAD_BYTES, askedKeys, createOf, entryBySlug, entryOfType, findEntries, postedData, requiredFields, runWorkflow, setData, typeBySlug, uploadAsset, withAutoSlug } from "./wizardApi";

export interface Outcome {
  ctx: Ctx;
  stay: boolean;
  /** A line to show on the next page (a run was started). */
  notice?: string;
}

const text = (form: FormData, name: string): string => String(form.get(name) ?? "").trim();

async function entryFor(def: WizardDefinition, step: Step, ctx: Ctx, authToken: string) {
  const entry = await entryBySlug(ctx[step.entry], authToken);
  if (!entry) throw new Error(`The ${step.entry} you chose is not there any more.`);
  return { entry, type: await typeBySlug(entryTypeOf(def, step.entry), authToken) };
}

async function choose(def: WizardDefinition, step: Step, form: FormData, ctx: Ctx, authToken: string): Promise<Outcome> {
  const action = text(form, "action"); // which button: pick | create | skip (each form has one, so a ticked radio can't beat Create)
  let value: string | undefined;
  if (action === "create") {
    const up = step.create?.upload as { field: string; accept?: string } | undefined; // the new one starts from a file
    const file = form.get("file");
    const given = up && file instanceof File && file.size > 0 ? file : null;
    const title = titleFor(text(form, "create_title"), given?.name ?? "");
    const type = await typeBySlug(step.entry_type, authToken);
    if (!title) throw new StepError(up ? "Upload a file, or give the new one a name." : "Give the new one a name.", up ? ["file", "create_title"] : ["create_title"]);
    if (!type) throw new Error(`This workspace has no “${step.entry_type}” entry type yet.`);
    const supplied = suppliedData(step, ctx);
    const fromFile: Record<string, string> = {};
    if (up && given) {
      const kind = acceptKind(up.accept ?? "image/*");
      const words = UPLOAD_WORDS[kind];
      if (!isKind(given, kind)) throw new StepError(words.notOne, ["file"]);
      if (given.size > MAX_UPLOAD_BYTES) throw new StepError(`That ${words.noun} is too big (25 MB at most).`, ["file"]);
      const ending = /\.[a-z0-9]{1,5}$/i.exec(given.name)?.[0] ?? "";
      fromFile[up.field] = await uploadAsset(given, `${step.entry_type}-${title}`, authToken, `${title}${ending}`);
    }
    const data = withAutoSlug(type, { ...supplied, ...postedData(form, type, askedKeys(type, step.create?.fields, Object.keys(supplied))), ...fromFile }, title);
    value = (await createOf(type, title, data, authToken)).slug;
  } else if (action === "pick") {
    const picked = text(form, "pick");
    if (!picked) throw new Error("Pick one from the list, or make a new one.");
    if (!(await entryOfType(step.entry_type, picked, authToken))) throw new Error("That one is not there any more. Pick again.");
    value = picked;
  } else if (action !== "skip") {
    throw new Error("Pick one, make a new one, or skip.");
  }
  // A changed choice drops what later steps chose on the strength of the old one.
  const next = value === ctx[step.as] ? { ...ctx } : withoutLater(def, ctx, step.id);
  if (value) next[step.as] = value;
  else delete next[step.as];
  return { ctx: next, stay: false };
}

async function upload(def: WizardDefinition, step: Step, form: FormData, ctx: Ctx, authToken: string): Promise<Outcome> {
  const file = form.get("file");
  if (!(file instanceof File) || file.size === 0) throw new StepError("Choose a file to upload.", ["file"]);
  const { entry, type } = await entryFor(def, step, ctx, authToken);
  // An upload replaces what the field holds, and a script is work someone did: it only goes ahead when they said so. A picture attached
  // under the field's role counts too (a work whose photo was attached by hand has an empty field).
  const role = fieldRole(type, step.field);
  const held = hasValue(entry.dataJson?.[step.field]) || ((entry as { assets?: { role?: string }[] }).assets ?? []).some((a) => a.role === role);
  if (held && text(form, "replace") !== "1") {
    throw new StepError(`“${step.field}” on ${entry.title} already has content. Tick “Replace it” to upload over it.`, ["replace"]);
  }
  if (step.mode === "text") {
    if (file.size > MAX_TEXT_UPLOAD_BYTES) throw new Error("That file is too long to read in as text (1 MB at most).");
    await setData(entry, { [step.field]: await file.text() }, authToken);
  } else {
    await setData(entry, { [step.field]: await uploadAsset(file, `${entry.slug}-${step.field}`, authToken) }, authToken);
  }
  return { ctx, stay: false };
}

async function editList(step: Step, form: FormData, ctx: Ctx, authToken: string): Promise<Outcome> {
  const type = await typeBySlug(step.entry_type, authToken);
  if (!type) throw new Error(`This workspace has no “${step.entry_type}” entry type yet.`);
  const rows = (await findEntries(listSpec(step, ctx), authToken)).entries;
  const columns = askedKeys(type, step.columns, Object.keys(suppliedData(step, ctx)));
  for (const row of rows) {
    // Only what the person changed on the page is written: compared with what the page showed (`__was`), not with the row now, so a
    // field something else filled in the meantime is kept.
    const was = JSON.parse(text(form, `row.${row.id}.__was`) || "null");
    if (was === null) continue; // the row was not on the page they posted
    const changes = postedData(form, type, columns, `row.${row.id}.`);
    const changed = Object.fromEntries(Object.entries(changes).filter(([k, v]) => !sameValue(v, was[k])));
    if (Object.keys(changed).length) await setData(row, changed, authToken);
  }
  const title = text(form, "new.title");
  const fresh = postedData(form, type, columns, "new.");
  const wanted = !!text(form, "again");
  const missing = missingForNewRow(title, fresh, requiredFields(type), wanted);
  if (missing.length) {
    const labels = missing.map((m) => m.label).join(", ");
    throw new StepError(`The new row needs ${labels}.${wanted && !title ? " Fill it in, or use Continue to go on without adding one." : ""}`, missing.map((m) => `new.${m.key}`));
  }
  if (title) {
    await createOf(type, title, { ...fresh, ...suppliedData(step, ctx) }, authToken);
  }
  return { ctx, stay: !!title && !!text(form, "again") };
}

const MAX_UPLOAD_BYTES = 25_000_000;
const UPLOAD_WORDS = {
  image: { noun: "picture", notOne: "That is not a picture." },
  audio: { noun: "sound", notOne: "That is not a sound." },
  file: { noun: "file", notOne: "That file cannot go here." },
} as const;

/** A gallery's actions: add (a form), upload (a picture or a sound becomes a new entry named for the file), generate (a run with a typed prompt). */
async function gallery(step: Step, form: FormData, ctx: Ctx, authToken: string): Promise<Outcome> {
  const action = text(form, "action");
  const type = await typeBySlug(step.entry_type, authToken);
  if (!type) throw new Error(`This workspace has no “${step.entry_type}” entry type yet.`);
  const seed = () => suppliedData(step, ctx);
  if (action === "add") {
    const title = text(form, "add_title");
    if (!title) throw new StepError("Give it a name.", ["add_title"]);
    const data = withAutoSlug(type, { ...seed(), ...postedData(form, type, askedKeys(type, step.add?.fields, Object.keys(seed()))) }, title);
    await createOf(type, title, data, authToken);
    return { ctx, stay: true, notice: "added" };
  }
  if (action === "upload") {
    const file = form.get("file");
    const kind = acceptKind(galleryAccept(step));
    const words = UPLOAD_WORDS[kind];
    if (!(file instanceof File) || file.size === 0) throw new Error(`Choose a ${words.noun} to upload.`);
    if (!isKind(file, kind)) throw new Error(words.notOne);
    if (file.size > MAX_UPLOAD_BYTES) throw new Error(`That ${words.noun} is too big (25 MB at most).`);
    const title = text(form, "upload_title") || file.name.replace(/\.[a-z0-9]+$/i, "").replace(/[-_]+/g, " ").trim() || "Untitled";
    // The asset carries the name the person gave it (with the file's own ending), not whatever the file was called ("recording.webm").
    const ending = /\.[a-z0-9]{1,5}$/i.exec(file.name)?.[0] ?? "";
    const assetId = await uploadAsset(file, `${step.entry_type}-${title}`, authToken, `${title}${ending}`);
    await createOf(type, title, withAutoSlug(type, { ...seed(), [step.upload.field]: assetId }, title), authToken);
    return { ctx, stay: true, notice: "added" };
  }
  if (action === "generate") {
    const { run, extra } = generateAsRun(step, text(form, "prompt"));
    if (step.generate?.prompt && !extra[step.generate.prompt.name]) throw new Error(`Say ${step.generate.prompt.label.toLowerCase()} first.`);
    await runWorkflow(run.workflow, runInputs(run, { ...ctx, ...extra }), authToken);
    return { ctx, stay: true, notice: "started" };
  }
  throw new Error("Add one, upload one, or generate one.");
}

/** Do what the posted step asks. Throws an Error whose message the page shows. */
export async function runStep(def: WizardDefinition, step: Step, form: FormData, ctx: Ctx, authToken: string): Promise<Outcome> {
  if (step.kind === "option") {
    const value = text(form, "value");
    if (!step.options.some((o: { value: string }) => o.value === value)) throw new Error("Pick one of the choices.");
    return { ctx: { ...ctx, [step.as]: value }, stay: false };
  }
  if (step.kind === "choose") return choose(def, step, form, ctx, authToken);
  if (step.kind === "upload") return upload(def, step, form, ctx, authToken);
  if (step.kind === "run") {
    const name = await runWorkflow(step.workflow, runInputs(step, ctx), authToken);
    void name;
    return { ctx, stay: true, notice: "started" };
  }
  if (step.kind === "list") return editList(step, form, ctx, authToken);
  if (step.kind === "gallery") return gallery(step, form, ctx, authToken);
  if (step.kind === "form") {
    const { entry, type } = await entryFor(def, step, ctx, authToken);
    await setData(entry, postedData(form, type, step.fields), authToken);
  }
  return { ctx, stay: false };
}
