/** What posting a wizard step does. Returns the choices after it and whether to stay on the step (a list can add one after another). */

import { type Ctx, type Step, StepError, type WizardDefinition, entryTypeOf, generateAsRun, hasValue, listSpec, missingForNewRow, runInputs, sameValue, suppliedData, withoutLater } from "./wizard";
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
    const title = text(form, "create_title");
    const type = await typeBySlug(step.entry_type, authToken);
    if (!title) throw new StepError("Give the new one a name.", ["create_title"]);
    if (!type) throw new Error(`This workspace has no “${step.entry_type}” entry type yet.`);
    const supplied = suppliedData(step, ctx);
    const data = withAutoSlug(type, { ...supplied, ...postedData(form, type, askedKeys(type, step.create?.fields, Object.keys(supplied))) }, title);
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
  const { entry } = await entryFor(def, step, ctx, authToken);
  // An upload replaces what the field holds, and a script is work someone did: it only goes ahead when they said so.
  if (hasValue(entry.dataJson?.[step.field]) && text(form, "replace") !== "1") {
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

const MAX_PICTURE_BYTES = 25_000_000;

/** A gallery's actions: add (a form), upload (a picture becomes a new entry named for the file), generate (a run with a typed prompt). */
async function gallery(step: Step, form: FormData, ctx: Ctx, authToken: string): Promise<Outcome> {
  const action = text(form, "action");
  const type = await typeBySlug(step.entry_type, authToken);
  if (!type) throw new Error(`This workspace has no “${step.entry_type}” entry type yet.`);
  const seed = () => suppliedData(step, ctx);
  if (action === "add") {
    const title = text(form, "add_title");
    if (!title) throw new StepError("Give it a name.", ["add_title"]);
    const data = withAutoSlug(type, { ...seed(), ...postedData(form, type, askedKeys(type, step.add?.fields, Object.keys(seed())), "add.") }, title);
    await createOf(type, title, data, authToken);
    return { ctx, stay: true, notice: "added" };
  }
  if (action === "upload") {
    const file = form.get("file");
    if (!(file instanceof File) || file.size === 0) throw new Error("Choose a picture to upload.");
    if (!file.type.startsWith("image/")) throw new Error("That is not a picture.");
    if (file.size > MAX_PICTURE_BYTES) throw new Error("That picture is too big (25 MB at most).");
    const title = text(form, "upload_title") || file.name.replace(/\.[a-z0-9]+$/i, "").replace(/[-_]+/g, " ").trim() || "Untitled";
    const assetId = await uploadAsset(file, `${step.entry_type}-${title}`, authToken);
    await createOf(type, title, withAutoSlug(type, { ...seed(), [step.upload.field]: assetId }, title), authToken);
    return { ctx, stay: true, notice: "added" };
  }
  if (action === "generate") {
    const { run, extra } = generateAsRun(step, text(form, "prompt"));
    if (step.generate?.prompt && !extra[step.generate.prompt.name]) throw new Error(`Say ${step.generate.prompt.label.toLowerCase()} first.`);
    await runWorkflow(run.workflow, runInputs(run, { ...ctx, ...extra }), authToken);
    return { ctx, stay: true, notice: "started" };
  }
  throw new Error("Add one, upload a picture, or generate one.");
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
