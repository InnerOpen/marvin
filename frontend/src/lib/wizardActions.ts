/** What posting a wizard step does. Returns the choices after it and whether to stay on the step (a list can add one after another). */

import { acceptKind, assetIsKind, isKind } from "./acceptKind";
import { type Ctx, type Step, StepError, type WizardDefinition, assetSpec, entryTypeOf, joinList, listOf, mergePicks, picksAssets, picksProblem, fieldRole, fileWays, galleryAccept, generateAsRun, hasValue, listSpec, measuredSeconds, missingForNewRow, numberedTitle, runInputs, sameValue, suppliedData, titleFor, withoutLater } from "./wizard";
import { MAX_TEXT_UPLOAD_BYTES, trashEntry, askedKeys, assetById, createOf, entryBySlug, fromTemplate, entryOfType, findAssets, findEntries, picksOf, postedData, requiredFields, runWorkflow, setData, typeBySlug, uploadAsset, withAutoSlug } from "./wizardApi";

export interface Outcome {
  ctx: Ctx;
  stay: boolean;
  /** A line to show on the next page (something was added, or a run started that the server could not name). */
  notice?: string;
  /** The run this step started: the next page follows it. */
  run?: string;
  /** The page of a multi-select step's cards to show next (a page move). */
  page?: number;
}

/** What a step that started a run hands the next page: the run to follow, or just "started" when the server named none. */
const startedRun = (ctx: Ctx, run: string | null): Outcome => (run ? { ctx, stay: true, run } : { ctx, stay: true, notice: "started" });

const text = (form: FormData, name: string): string => String(form.get(name) ?? "").trim();

async function entryFor(def: WizardDefinition, step: Step, ctx: Ctx, authToken: string) {
  const entry = await entryBySlug(ctx[step.entry], authToken);
  if (!entry) throw new Error(`The ${step.entry} you chose is not there any more.`);
  return { entry, type: await typeBySlug(entryTypeOf(def, step.entry), authToken) };
}

/**
 * A multi-select step posted: from Continue (`action` pick), a page move (`go`: the page to show) or the page's own Select all / Clear
 * (`sel`, when the browser ran no script). The form names the cards it showed (`shown`) and the ticked ones (`pick`): picks on other pages
 * stay, and of this page's exactly the ticked ones are in (`mergePicks`). Only ticked cards that are there (of the step's type, or assets
 * of the step's filters) are taken; the list is refused past MAX_PICKS rather than cut.
 */
async function chooseMany(def: WizardDefinition, step: Step, form: FormData, ctx: Ctx, authToken: string): Promise<Outcome> {
  if (step.optional && text(form, "action") === "skip") {
    const { [step.as]: _dropped, ...rest } = withoutLater(def, ctx, step.id); // skipped: nothing is picked
    return { ctx: rest, stay: false };
  }
  const shown = listOf(form.getAll("shown").map(String).join(","));
  const sel = text(form, "sel"); // all | clear (the page's own buttons, without a script)
  const cleared = sel === "clear" || text(form, "clear_all") === "1"; // Clear drops the picks on other pages too
  const ticked = sel === "all" ? shown : sel === "clear" ? [] : listOf(form.getAll("pick").map(String).join(",")).filter((p) => shown.includes(p));
  const prior = cleared ? [] : listOf(ctx[step.as]);
  const fresh = ticked.filter((p) => !prior.includes(p));
  if (fresh.length) {
    // The new ones are checked in one request: an entry of the step's type, or an asset that (still) fits the step's filters.
    const there = new Set(
      picksAssets(step)
        ? (await findAssets({ ...assetSpec(step, ctx), ids: fresh.join(",") }, authToken)).map((r) => r.slug)
        : (await picksOf(step, fresh, authToken)).map((r) => r.slug),
    );
    const gone = fresh.filter((p) => !there.has(p));
    if (gone.length) throw new StepError(`${gone.length === 1 ? "One you ticked is" : `${gone.length} you ticked are`} not there any more (or no longer fit). Tick again.`);
  }
  const picks = mergePicks(prior, shown, ticked);
  const tooMany = picksProblem(picks.length);
  if (tooMany) throw new StepError(tooMany);
  const value = joinList(picks);
  const next = value === (ctx[step.as] ?? "") ? { ...ctx } : withoutLater(def, ctx, step.id);
  if (value) next[step.as] = value;
  else delete next[step.as];
  const go = Number.parseInt(text(form, "go"), 10);
  if (Number.isFinite(go) && go >= 1) return { ctx: next, stay: true, page: go };
  if (sel) return { ctx: next, stay: true, page: Number.parseInt(text(form, "page"), 10) || 1 };
  if (!picks.length) throw new StepError(step.optional ? "Tick at least one, or skip this step." : "Tick at least one to go on.");
  return { ctx: next, stay: false };
}

async function choose(def: WizardDefinition, step: Step, form: FormData, ctx: Ctx, authToken: string): Promise<Outcome> {
  if (step.multiple === true) return chooseMany(def, step, form, ctx, authToken);
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

/** The asset a file box holds, by the id its form posts (`asset_id`: one chosen from the workspace's assets, or one uploaded or recorded in
 *  the box's own dialog). It must be in this workspace and of the kind the box takes; "" when the box is empty. */
async function heldAsset(form: FormData, accept: string | undefined, authToken: string): Promise<string> {
  const id = text(form, "asset_id");
  if (!id) return "";
  const asset = await assetById(id, authToken);
  if (!asset) throw new StepError("That file is not in your assets any more. Choose another.", ["asset_id"]);
  const kind = acceptKind(accept ?? "audio/*");
  if (!assetIsKind(asset, kind)) throw new StepError(UPLOAD_WORDS[kind].notOne, ["asset_id"]);
  return id;
}

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
    const add = step.add as { buttons?: { label: string; data?: Record<string, unknown>; file?: string }[]; file?: { field: string; accept?: string; seconds?: string; assets?: boolean } } | undefined;
    const button = add?.buttons ? add.buttons[Number(text(form, "do")) || 0] : undefined; // which way of saving was pressed
    // The file box holds an asset by now (chosen, uploaded or recorded there): the form posts its id, never the file.
    const held = add?.file ? await heldAsset(form, add.file.accept, authToken) : "";
    const kind = acceptKind(add?.file?.accept ?? "audio/*");
    if (button?.file === "required" && !held) throw new StepError(`${fileWays(!!add?.file?.assets, kind === "audio")} a ${UPLOAD_WORDS[kind].noun} first, or use the other button.`, ["asset_id"]);
    if (button?.file === "none" && held) throw new StepError(`A ${UPLOAD_WORDS[kind].noun} is chosen. Use the button that saves it, or remove it to have one made.`, ["asset_id"]);
    const title = text(form, "add_title") || (await named());
    if (!title) throw new StepError("Give it a name.", ["add_title"]);
    const fromFile: Record<string, unknown> = {};
    if (add?.file && held) {
      fromFile[add.file.field] = held;
      // A sound's length is measured in the browser as it is uploaded there (nothing else stores it) and kept on the new entry.
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
    const acts = (step.card_actions ?? []) as { set: Record<string, unknown>; file?: { field: string; accept?: string; assets?: boolean } }[];
    const chosen = acts[Number(text(form, "card_do"))];
    const entry = (await findEntries(listSpec(step, ctx), authToken)).entries.find((e) => e.id === text(form, "card_id"));
    if (!chosen || !entry) throw new Error("That one is not in this list any more.");
    const attached: Record<string, unknown> = {};
    if (chosen.file) {
      // A button that asks for a file: the card's file box posts the id of an asset, one chosen from the workspace's (where the step offers
      // them) or one uploaded or recorded there. An upload is an asset before the form posts, so its id is taken either way.
      const kind = acceptKind(chosen.file.accept ?? "audio/*");
      const held = await heldAsset(form, chosen.file.accept, authToken);
      if (!held) throw new Error(`${fileWays(!!chosen.file.assets, kind === "audio")} a ${UPLOAD_WORDS[kind].noun} first.`);
      attached[chosen.file.field] = held;
    }
    await setData(entry, { ...attached, ...chosen.set }, authToken);
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
    const kind = acceptKind(galleryAccept(step, (type.schemaJson as { fields?: { key?: string; accept?: string }[] } | undefined)?.fields ?? []));
    const words = UPLOAD_WORDS[kind];
    if (!(file instanceof File) || file.size === 0) throw new Error(`Choose a ${words.noun} to upload.`);
    if (!isKind(file, kind)) throw new Error(words.notOne);
    if (file.size > MAX_UPLOAD_BYTES) throw new Error(`That ${words.noun} is too big (25 MB at most).`);
    const title = text(form, "upload_title") || (await named()) || file.name.replace(/\.[a-z0-9]+$/i, "").replace(/[-_]+/g, " ").trim() || "Untitled";
    // The asset carries the name the person gave it (with the file's own ending), not whatever the file was called ("recording.webm").
    const ending = /\.[a-z0-9]{1,5}$/i.exec(file.name)?.[0] ?? "";
    const assetId = await uploadAsset(file, `${step.entry_type}-${title}`, authToken, `${title}${ending}`);
    if (step.upload.template) {
      // The step names one of the type's templates: the entry is made with it (and its picture preset), not from the step's own data.
      await fromTemplate(step.entry_type, step.upload.template, assetId, title, authToken);
      return { ctx, stay: true, notice: "added" };
    }
    // A sound's length is measured in the browser as it is picked (a file's own length is not stored anywhere else) and kept on the new entry.
    const seconds = step.upload.seconds ? measuredSeconds(text(form, "upload_seconds")) : null;
    const lengthData = step.upload.seconds && seconds !== null ? { [step.upload.seconds]: seconds } : {};
    await createOf(type, title, withAutoSlug(type, { ...seed(), [step.upload.field]: assetId, ...lengthData }, title), authToken);
    return { ctx, stay: true, notice: "added" };
  }
  if (action === "generate") {
    const { run, extra } = generateAsRun(step, text(form, "prompt"));
    if (step.generate?.prompt && !extra[step.generate.prompt.name]) throw new Error(`Say ${step.generate.prompt.label.toLowerCase()} first.`);
    return startedRun(ctx, await runWorkflow(run.workflow, runInputs(run, { ...ctx, ...extra }), authToken));
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
  if (step.kind === "run") return startedRun(ctx, await runWorkflow(step.workflow, runInputs(step, ctx), authToken));
  if (step.kind === "list") return editList(step, form, ctx, authToken);
  if (step.kind === "gallery") return gallery(step, form, ctx, authToken);
  if (step.kind === "form") {
    const { entry, type } = await entryFor(def, step, ctx, authToken);
    await setData(entry, postedData(form, type, step.fields), authToken);
  }
  return { ctx, stay: false };
}
