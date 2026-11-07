/** What posting a wizard step does. Returns the choices after it and whether to stay on the step (a list can add one after another). */

import { type Ctx, type Step, type WizardDefinition, createData, entryTypeOf, hasValue, listSpec } from "./wizard";
import { MAX_TEXT_UPLOAD_BYTES, createOf, entryBySlug, findEntries, postedData, setData, typeBySlug, uploadAsset } from "./wizardApi";

export interface Outcome {
  ctx: Ctx;
  stay: boolean;
}

const text = (form: FormData, name: string): string => String(form.get(name) ?? "").trim();

async function entryFor(def: WizardDefinition, step: Step, ctx: Ctx, authToken: string) {
  const entry = await entryBySlug(ctx[step.entry], authToken);
  if (!entry) throw new Error(`The ${step.entry} you chose is not there any more.`);
  return { entry, type: await typeBySlug(entryTypeOf(def, step.entry), authToken) };
}

async function choose(step: Step, form: FormData, ctx: Ctx, authToken: string): Promise<Outcome> {
  const next = { ...ctx };
  if (text(form, "skip")) {
    delete next[step.as];
  } else if (text(form, "pick")) {
    next[step.as] = text(form, "pick");
  } else {
    const title = text(form, "create_title");
    const type = await typeBySlug(step.entry_type, authToken);
    if (!title) throw new Error("Give it a name, or pick one from the list.");
    if (!type) throw new Error(`This workspace has no “${step.entry_type}” entry type yet.`);
    const data = { ...createData(step, ctx), ...postedData(form, type, step.create?.fields ?? []) };
    next[step.as] = (await createOf(type, title, data, authToken)).slug;
  }
  return { ctx: next, stay: false };
}

async function upload(def: WizardDefinition, step: Step, form: FormData, ctx: Ctx, authToken: string): Promise<Outcome> {
  const file = form.get("file");
  if (!(file instanceof File) || file.size === 0) throw new Error("Choose a file to upload.");
  const { entry } = await entryFor(def, step, ctx, authToken);
  // An upload replaces what the field holds, and a script is work someone did: it only goes ahead when they said so.
  if (hasValue(entry.dataJson?.[step.field]) && text(form, "replace") !== "1") {
    throw new Error(`“${step.field}” on ${entry.title} already has content. Tick “Replace it” to upload over it.`);
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
  for (const row of rows) {
    const changes = postedData(form, type, step.columns, `row.${row.id}.`);
    const changed = Object.fromEntries(Object.entries(changes).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(row.dataJson?.[k] ?? null)));
    if (Object.keys(changed).length) await setData(row, changed, authToken);
  }
  const title = text(form, "new.title");
  if (title) {
    await createOf(type, title, { ...postedData(form, type, step.columns, "new."), ...createData({ ...step, create: { data: step.create_data } } as Step, ctx), [step.parent_field]: ctx[step.parent] }, authToken);
  }
  return { ctx, stay: !!title && !!text(form, "again") };
}

/** Do what the posted step asks. Throws an Error whose message the page shows. */
export async function runStep(def: WizardDefinition, step: Step, form: FormData, ctx: Ctx, authToken: string): Promise<Outcome> {
  if (step.kind === "option") {
    const value = text(form, "value");
    if (!step.options.some((o: { value: string }) => o.value === value)) throw new Error("Pick one of the choices.");
    return { ctx: { ...ctx, [step.as]: value }, stay: false };
  }
  if (step.kind === "choose") return choose(step, form, ctx, authToken);
  if (step.kind === "upload") return upload(def, step, form, ctx, authToken);
  if (step.kind === "list") return editList(step, form, ctx, authToken);
  if (step.kind === "form") {
    const { entry, type } = await entryFor(def, step, ctx, authToken);
    await setData(entry, postedData(form, type, step.fields), authToken);
  }
  return { ctx, stay: false };
}
