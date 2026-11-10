import assert from "node:assert/strict";
import { test } from "node:test";
import {
  approvalsOf, buttonHref, cardActionShown, naturalByTitle, highlightOf, measuredSeconds, prefillOf, numberedTitle, shownLines, blocker, cardAudio, cardPicture, fieldRole, galleryAccept, titleFor, generateAsRun, inputKeys, isDone, keysAfter, missingForNewRow, runInputs, sameValue, withoutLater, chooseSpec, createData, currentStep, hasValue, holds, listSpec, nextStep, passes, previousStep, readCtx, shownSteps, stepHref, substitute, suppliedData, withoutEmpty,
} from "./wizard.ts";

const def = {
  title: "Narrate",
  steps: [
    { id: "world", kind: "choose", title: "World", as: "world", entry_type: "world" },
    { id: "series", kind: "choose", title: "Series", as: "series", entry_type: "series", optional: true, scope: { world: "${world}" } },
    { id: "story", kind: "choose", title: "Story", as: "story", entry_type: "story", scope: { world: "${world}", series: "${series}" }, create: { data: { world: "${world}", series: "${series}", status: "draft" } } },
    { id: "how", kind: "option", title: "Start", as: "input", options: [] },
    { id: "script", kind: "upload", title: "Script", entry: "story", when: { ctx: "input", op: "eq", value: "script" } },
    { id: "cast", kind: "list", title: "Cast", entry_type: "cast-member", parent_field: "story", parent: "story" },
  ],
};

test("the context is the address's choices, never the step", () => {
  const ctx = readCtx(new URLSearchParams("step=story&world=w1&Bad=x&series=&story=%20s1%20"));
  assert.deepEqual(ctx, { world: "w1", story: "s1" });
});

test("a step that works on an entry waits until it is chosen, and a when hides a branch", () => {
  assert.deepEqual(shownSteps(def, {}).map((s) => s.id), ["world", "series", "story", "how"]);
  const ctx = { world: "w", story: "s", input: "script" };
  assert.deepEqual(shownSteps(def, ctx).map((s) => s.id), ["world", "series", "story", "how", "script", "cast"]);
  assert.deepEqual(shownSteps(def, { ...ctx, input: "beats" }).map((s) => s.id), ["world", "series", "story", "how", "cast"]);
});

test("next, previous and current follow what is shown", () => {
  const ctx = { world: "w", story: "s" };
  assert.equal(nextStep(def, ctx, "how")?.id, "cast");
  assert.equal(previousStep(def, ctx, "cast")?.id, "how");
  assert.equal(nextStep(def, ctx, "cast"), null);
  assert.equal(previousStep(def, ctx, "world"), null);
  assert.equal(currentStep(def, ctx, "nowhere")?.id, "world");
  assert.equal(currentStep(def, ctx, "series")?.id, "series");
});

test("when ops", () => {
  assert.equal(holds(undefined, {}), true);
  assert.equal(holds({ ctx: "a", op: "set" }, { a: "x" }), true);
  assert.equal(holds({ ctx: "a", op: "unset" }, { a: "x" }), false);
  assert.equal(holds({ ctx: "a", op: "eq", value: "x" }, { a: "x" }), true);
  assert.equal(holds({ ctx: "a", op: "neq", value: "x" }, {}), true);
});

test("substitute fills choices in and an unmade choice comes out empty", () => {
  assert.deepEqual(substitute({ a: ["${w}", "x"], b: "n-${missing}" }, { w: "world-1" }), { a: ["world-1", "x"], b: "n-" });
  assert.deepEqual(withoutEmpty({ a: "", b: "x", c: null }), { b: "x" });
});

test("a choose narrows by what was chosen before and a skipped choice narrows nothing", () => {
  const story = def.steps[2];
  assert.deepEqual(chooseSpec(story, { world: "w", series: "se" }), { entry_type: "story", fields: { world: "w", series: "se" } });
  assert.deepEqual(chooseSpec(story, { world: "w" }), { entry_type: "story", fields: { world: "w" } });
  assert.deepEqual(createData(story, { world: "w" }), { world: "w", status: "draft" });
});

test("a step supplies the parent's slug and its own create data, so a form need not ask for them", () => {
  const troupe = { id: "troupe", kind: "gallery", title: "Troupe", entry_type: "actor", parent: "world", parent_field: "world", add: { fields: ["build"] } };
  assert.deepEqual(suppliedData(troupe, { world: "w" }), { world: "w" });
  assert.deepEqual(suppliedData(troupe, {}), {}, "no world chosen yet: nothing is supplied");
  assert.deepEqual(suppliedData(def.steps[2], { world: "w" }), { world: "w", status: "draft" }, "a choose's create data, skipped choices left out");
  const cast = { ...def.steps[5], create_data: { presence: "${presence}" } };
  assert.deepEqual(suppliedData(cast, { story: "s", presence: "on" }), { presence: "on", story: "s" });
});

test("a list asks for the children of the parent", () => {
  assert.deepEqual(listSpec(def.steps[5], { story: "s" }), { entry_type: "cast-member", fields: { story: "s" } });
});

test("review comparisons", () => {
  assert.equal(passes("gte", 1, 1), true);
  assert.equal(passes("gt", 1, 1), false);
  assert.equal(passes("eq", 0, 0), true);
  assert.equal(passes("lt", 0, 1), true);
  assert.equal(passes("lte", 2, 1), false);
});

test("a step's address keeps the choices", () => {
  assert.equal(stepHref("narrate", { world: "w" }, "story", { story: "s 1" }), "/workspace/setups/narrate?step=story&world=w&story=s+1");
});

test("an upload only warns where there is something to replace", () => {
  assert.equal(hasValue(""), false);
  assert.equal(hasValue("  \n"), false);
  assert.equal(hasValue(null), false);
  assert.equal(hasValue([]), false);
  assert.equal(hasValue("INT. BOAT - DAY"), true);
  assert.equal(hasValue(["a"]), true);
  assert.equal(hasValue("0f1e"), true);
});

test("a step waits for the answers before it, so a list is never shown with nothing chosen to narrow it", () => {
  assert.equal(blocker(def, {}, "world"), null);
  assert.equal(blocker(def, {}, "series")?.id, "world");
  assert.equal(blocker(def, { world: "w" }, "series"), null); // series is optional: it never blocks
  assert.equal(blocker(def, { world: "w" }, "cast")?.id, "story");
  assert.equal(blocker(def, { world: "w", story: "s" }, "cast")?.id, "how");
  assert.equal(currentStep(def, {}, "story")?.id, "world");
  assert.equal(currentStep(def, { world: "w" }, "story")?.id, "story");
});

test("a run step hands the workflow the choices, and the notice is not a choice", () => {
  const step = { id: "cut", kind: "run", title: "Cut", workflow: "screenplay-import-beats", inputs: { story: "${story}", mode: "refresh", sheet: "${nope}" } };
  assert.deepEqual(runInputs(step, { story: "s1" }), { story: "s1", mode: "refresh" });
  assert.deepEqual(readCtx(new URLSearchParams("step=cut&story=s1&notice=Started")), { story: "s1" });
});

test("a new row left empty is no row, but one begun or asked for needs its name and required columns", () => {
  const required = [{ key: "cast_id", label: "Cast id" }];
  assert.deepEqual(missingForNewRow("", { cast_id: null, role: null }, required, false), []);
  assert.deepEqual(missingForNewRow("", { cast_id: null }, required, true).map((m) => m.label), ["Name", "Cast id"]);
  assert.deepEqual(missingForNewRow("Old cook", { cast_id: null }, required, false).map((m) => m.key), ["cast_id"]);
  assert.deepEqual(missingForNewRow("", { cast_id: "old-cook" }, required, false).map((m) => m.key), ["title"]);
  assert.deepEqual(missingForNewRow("Old cook", { cast_id: "old-cook" }, required, true), []);
  assert.deepEqual(missingForNewRow("", { presence: false }, required, false), []);
});

test("a run step's approvals are the ones its workflow raised about the entries it was given", () => {
  const step = { id: "cut", kind: "run", title: "Cut", workflow: "cut-it", inputs: { story: "${story}", mode: "add", world: "${world}" } };
  assert.deepEqual(inputKeys(step), ["story", "world"]);
  const cards = [
    { id: "a", automationSlug: "cut-it", entryId: "s1", message: "m", status: "pending" },
    { id: "b", automationSlug: "cut-it", entryId: "other", message: "m", status: "pending" },
    { id: "c", automationSlug: "else", entryId: "s1", message: "m", status: "pending" },
    { id: "d", automationSlug: "cut-it", entryId: null, message: "m", status: "pending" },
  ];
  assert.deepEqual(approvalsOf(cards, "cut-it", ["s1"]).map((c) => c.id), ["a", "d"]);
  assert.deepEqual(approvalsOf(cards, "cut-it", []).map((c) => c.id), ["d"]); // no entry given: only the cards about no entry, never all
});

test("a changed choice drops what later steps chose", () => {
  assert.deepEqual(keysAfter(def, "world"), ["series", "story", "input"]);
  assert.deepEqual(withoutLater(def, { world: "w2", series: "se", story: "s", input: "script" }, "world"), { world: "w2" });
  assert.deepEqual(withoutLater(def, { world: "w", story: "s", input: "script" }, "story"), { world: "w", story: "s" });
});

test("nothing, an empty string and null read the same; anything else compares by value", () => {
  assert.equal(sameValue("", null), true);
  assert.equal(sameValue(undefined, ""), true);
  assert.equal(sameValue("a", "a"), true);
  assert.equal(sameValue("a", ""), false);
  assert.equal(sameValue(0, null), false);
});

test("a step shows done when the data says so: a choice or option that is set", () => {
  assert.equal(isDone(def.steps[0], { world: "w" }), true);
  assert.equal(isDone(def.steps[0], {}), false);
  assert.equal(isDone(def.steps[3], { input: "script" }), true);
  assert.equal(isDone(def.steps[5], { story: "s" }), false); // a list has no mark of its own
});

test("a card's picture (and sound) is the asset in that field's role, and generate is a run step with the prompt as a choice", () => {
  const assets = [
    { role: "age_view", publicUrl: "https://x/young.png", mimeType: "image/png" },
    { role: "general_view", publicUrl: "https://x/now.png", mimeType: "image/png" },
    { role: "voice_sample", publicUrl: "https://x/v.mp3", mimeType: "audio/mpeg" },
  ];
  assert.equal(cardPicture(assets, "general_view"), "https://x/now.png");
  assert.equal(cardPicture(assets, "voice_sample"), null);
  assert.equal(cardPicture(undefined, "general_view"), null);
  assert.equal(cardAudio(assets, "voice_sample"), "https://x/v.mp3");
  assert.equal(cardAudio(assets, "general_view"), null); // a picture is not a sound
  assert.equal(cardAudio(assets, undefined), null);
  assert.equal(cardAudio(undefined, "voice_sample"), null);
  assert.equal(galleryAccept({ upload: { field: "sample", accept: "audio/*" } }), "audio/*");
  assert.equal(galleryAccept({ upload: { field: "general_view" } }), "image/*"); // a picture unless it says otherwise
  const step = { id: "troupe", kind: "gallery", title: "T", entry_type: "actor", generate: { workflow: "make-actor", inputs: { world: "${world}", brief: "${brief}" }, button: "Make one", prompt: { name: "brief", label: "Who" } } };
  const { run, extra } = generateAsRun(step, "a tall sailor");
  assert.equal(run.kind, "run");
  assert.equal(run.workflow, "make-actor");
  assert.deepEqual(extra, { brief: "a tall sailor" });
  assert.deepEqual(listSpec({ id: "g", kind: "gallery", title: "G", entry_type: "actor" }, {}), { entry_type: "actor" });
});

test("a field's file is attached under its role when its type names one, else under its key", () => {
  const type = { schemaJson: { fields: [{ key: "image", type: "asset", role: "featured" }, { key: "general_view", type: "asset" }] } };
  assert.equal(fieldRole(type, "image"), "featured");
  assert.equal(fieldRole(type, "general_view"), "general_view");
  assert.equal(fieldRole(type, "missing"), "missing");
  assert.equal(fieldRole(null, "image"), "image");
  assert.equal(fieldRole(type, undefined), undefined);
  const assets = [{ role: "featured", publicUrl: "https://x/art.jpg", mimeType: "image/jpeg" }];
  assert.equal(cardPicture(assets, fieldRole(type, "image")), "https://x/art.jpg");
});

test("a new entry is named for what was typed, else for the file", () => {
  assert.equal(titleFor("  Weightless Hour ", "IMG_1.jpg"), "Weightless Hour");
  assert.equal(titleFor("", "weightless-hour_2.JPG"), "weightless hour 2");
  assert.equal(titleFor("", ""), "");
});

test("a setup's button opens it on the entry, carrying what the entry's fields hold, on the step it names", () => {
  const button = { entryType: "speech-line", label: "Takes", key: "line", step: "takes", also: { story: "story", world: "missing" } };
  const entry = { slug: "granny-advice-line-01-1", dataJson: { story: "granny-advice", text: "People say" } };
  const url = new URL(buttonHref("takes-of-a-line", button, entry), "http://x");
  assert.equal(url.pathname, "/workspace/setups/takes-of-a-line");
  assert.deepEqual(Object.fromEntries(url.searchParams), { step: "takes", line: "granny-advice-line-01-1", story: "granny-advice" });
  // no step: the setup opens on its first unanswered step; an empty field carries nothing
  const bare = new URL(buttonHref("x", { entryType: "a", label: "L", key: "k" }, { slug: "s", dataJson: null }), "http://x");
  assert.deepEqual(Object.fromEntries(bare.searchParams), { k: "s" });
});

test("a gallery names what it makes after its parent, the noun and the next number", () => {
  assert.equal(numberedTitle("01 Granny: People say…", "take", 0), "01 Granny: People say… · take 1");
  assert.equal(numberedTitle("  ", "take", 2), "Untitled · take 3");
});

test("a show card reads out the wanted fields that have a value, with the type's own labels", () => {
  const schema = { fields: [{ key: "text", label: "Text" }, { key: "direction", label: "Direction" }, { key: "speaker" }] };
  const data = { text: " People say. ", direction: "", speaker: "granny", status: "draft", n: 3 };
  assert.deepEqual(shownLines(data, schema, ["speaker", "text", "direction", "n", "missing"]), [
    { key: "speaker", label: "speaker", value: "granny" },
    { key: "text", label: "Text", value: "People say." },
    { key: "n", label: "n", value: "3" },
  ]);
  assert.deepEqual(shownLines(null, null, ["text"]), []);
});

test("a highlight marks the card whose field has the wanted value", () => {
  const step = { highlight: { field: "status", value: "in_use", label: "In use" } };
  assert.equal(highlightOf(step, { status: "in_use" }), "In use");
  assert.equal(highlightOf(step, { status: "recorded" }), null);
  assert.equal(highlightOf({}, { status: "in_use" }), null);
});

test("measured seconds are a real positive length, rounded to the millisecond", () => {
  assert.equal(measuredSeconds("2.6944"), 2.694);
  for (const bad of ["", "0", "-1", "abc", "Infinity", "99999", undefined, null]) assert.equal(measuredSeconds(bad), null);
});

test("an add form starts from the chosen entries' own values", () => {
  const entries = { line: { dataJson: { text: "People say.", direction: "tired", speed: 0.9, model: "", empty: null } } };
  const add = { prefill: { spoken: "line.text", direction: "line.direction", speed: "line.speed", model: "line.model", gone: "nobody.text" } };
  assert.deepEqual(prefillOf(add, entries), { spoken: "People say.", direction: "tired", speed: "0.9" });
  assert.deepEqual(prefillOf(undefined, entries), {});
  // the first of several that has a value
  const fallback = { prefill: { spoken: "line.delivery_text|line.text" } };
  assert.deepEqual(prefillOf(fallback, { line: { dataJson: { delivery_text: "[sighs] People say.", text: "People say." } } }), { spoken: "[sighs] People say." });
  assert.deepEqual(prefillOf(fallback, { line: { dataJson: { delivery_text: " ", text: "People say." } } }), { spoken: "People say." });
});

test("a long list of numbered entries runs from the lowest to the highest", () => {
  const rows = ["10 Cook: Soup", "2 Cook: Salt", "02 Granny: Hi", "1 Cook: Hello", "b", "A"].map((title) => ({ title }));
  assert.deepEqual(naturalByTitle(rows).map((r) => r.title), ["1 Cook: Hello", "2 Cook: Salt", "02 Granny: Hi", "10 Cook: Soup", "A", "b"]);
  assert.deepEqual(naturalByTitle([{ title: null }, { title: "a" }]).map((r) => r.title ?? ""), ["", "a"]);
});

test("a card action shows on the cards its when allows", () => {
  const use = { label: "Use this one", set: { status: "in_use" }, when: { field: "status", op: "neq", value: "in_use" } };
  assert.equal(cardActionShown(use, { status: "recorded" }), true);
  assert.equal(cardActionShown(use, { status: "in_use" }), false);
  assert.equal(cardActionShown(use, {}), true);
  const retry = { label: "Try again", set: { status: "queued" }, when: { field: "status", op: "eq", value: "draft" } };
  assert.equal(cardActionShown(retry, { status: "draft" }), true);
  assert.equal(cardActionShown(retry, { status: "recorded" }), false);
  assert.equal(cardActionShown({ label: "x", set: { a: 1 } }, null), true);
});
