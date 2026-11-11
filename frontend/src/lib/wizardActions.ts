/** What posting a wizard step does. Returns the choices after it and whether to stay on the step (a list can add one after another). */

import { acceptKind, isKind } from "./acceptKind";
import { type Ctx, type Step, StepError, type WizardDefinition, entryTypeOf, fieldRole, galleryAccept, generateAsRun, hasValue, listSpec, measuredSeconds, missingForNewRow, numberedTitle, runInputs, sameValue, suppliedData, titleFor, withoutLater } from "./wizard";
import { MAX_TEXT_UPLOAD_BYTES, trashEntry, askedKeys, createOf, entryBySlug, entryOfType, findEntries, postedData, requiredFields, runWorkflow, setData, typeBySlug, uploadAsset, withAutoSlug } from "./wizardApi";

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
  /** The name a gallery gives a new entry when none was typed: its parent's title, the noun and the next number. */
  const named = async (): Promise<string> => {
    const from = step.name as { from: string; noun: string } | undefined;
    if (!from) return "";
    const parent = await entryBySlug(ctx[from.from], authToken);
    const count = (await findEntries(listSpec(step, ctx), authToken)).entries.length;
    return numberedTitle(parent?.title ?? "", from.noun, count);
  };
  if (action === "add") {
    const add = step.add as { buttons?: { label: string; data?: Record<string, unknown>; file?: string }[]; file?: { field: string; accept?: string; seconds?: string } } | undefined;
    const button = add?.buttons ? add.buttons[Number(text(form, "do")) || 0] : undefined; // which way of saving was pressed
    const file = form.get("file");
    const given = add?.file && file instanceof File && file.size > 0 ? file : null;
    if (button?.file === "required" && !given) throw new StepError("Record or upload the take first, or use the other button.", ["file"]);
    if (button?.file === "none" && given) throw new StepError("A recording is attached. Use the button that saves it, or remove it to have one made.", ["file"]);
    const title = text(form, "add_title") || (await named());
    if (!title) throw new StepError("Give it a name.", ["add_title"]);
    const fromFile: Record<string, unknown> = {};
    if (add?.file && given) {
      const words = UPLOAD_WORDS[acceptKind(add.file.accept ?? "audio/*")];
      if (!isKind(given, acceptKind(add.file.accept ?? "audio/*"))) throw new StepError(words.notOne, ["file"]);
      if (given.size > MAX_UPLOAD_BYTES) throw new StepError(`That ${words.noun} is too big (25 MB at most).`, ["file"]);
      const ending = /\.[a-z0-9]{1,5}$/i.exec(given.name)?.[0] ?? "";
      // The file is named for the entry it belongs to ("… · take 2.webm"), never left as "recording".
      fromFile[add.file.field] = await uploadAsset(given, `${step.entry_type}-${title}`, authToken, `${title}${ending}`);
      const seconds = add.file.seconds ? measuredSeconds(text(form, "upload_seconds")) : null;
      if (add.file.seconds && seconds !== null) fromFile[add.file.seconds] = seconds;
    }
    const posted = postedData(form, type, askedKeys(type, step.add?.fields, Object.keys(seed())));
    const data = withAutoSlug(type, { ...seed(), ...posted, ...fromFile, ...(button?.data ?? {}) }, title);
    await createOf(type, title, data, authToken);
    return { ctx, stay: true, notice: "added" };
  }
  if (action === "card") {
    // A button on a card sets fields on that entry (Use this one: status in_use). The entry must be one this gallery lists, and the button
    // one the step declares: nothing else is taken from the form.
    const acts = (step.card_actions ?? []) as { set: Record<string, unknown> }[];
    const chosen = acts[Number(text(form, "card_do"))];
    const entry = (await findEntries(listSpec(step, ctx), authToken)).entries.find((e) => e.id === text(form, "card_id"));
    if (!chosen || !entry) throw new Error("That one is not in this list any more.");
    await setData(entry, chosen.set, authToken);
    return { ctx, stay: true, notice: "changed" };
  }
  if (action === "trash") {
    // Only what this gallery lists can be trashed from it: the id is checked against its own entries, never taken on trust.
    const id = text(form, "trash_id");
    const listed = (await findEntries(listSpec(step, ctx), authToken)).entries;
    if (!step.trash || !listed.some((e) => e.id === id)) throw new Error("That one is not in this list any more.");
    await trashEntry(id, authToken);
    return { ctx, stay: true, notice: "trashed" };
  }
  if (action === "upload") {
    const file = form.get("file");
    const kind = acceptKind(galleryAccept(step));
    const words = UPLOAD_WORDS[kind];
    if (!(file instanceof File) || file.size === 0) throw new Error(`Choose a ${words.noun} to upload.`);
    if (!isKind(file, kind)) throw new Error(words.notOne);
    if (file.size > MAX_UPLOAD_BYTES) throw new Error(`That ${words.noun} is too big (25 MB at most).`);
    const title = text(form, "upload_title") || (await named()) || file.name.replace(/\.[a-z0-9]+$/i, "").replace(/[-_]+/g, " ").trim() || "Untitled";
    // The asset carries the name the person gave it (with the file's own ending), not whatever the file was called ("recording.webm").
    const ending = /\.[a-z0-9]{1,5}$/i.exec(file.name)?.[0] ?? "";
    const assetId = await uploadAsset(file, `${step.entry_type}-${title}`, authToken, `${title}${ending}`);
    // A sound's length is measured in the browser as it is picked (a file's own length is not stored anywhere else) and kept on the new entry.
    const seconds = step.upload.seconds ? measuredSeconds(text(form, "upload_seconds")) : null;
    const lengthData = step.upload.seconds && seconds !== null ? { [step.upload.seconds]: seconds } : {};
    await createOf(type, title, withAutoSlug(type, { ...seed(), [step.upload.field]: assetId, ...lengthData }, title), authToken);
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
    if (step.optional && text(form, "action") === "skip") {
      const { [step.as]: _dropped, ...rest } = withoutLater(def, ctx, step.id); // skipped: nothing is chosen, so what a choice here made shown stays hidden
      return { ctx: rest, stay: false };
    }
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
