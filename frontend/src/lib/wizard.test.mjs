import assert from "node:assert/strict";
import { test } from "node:test";
import {
  approvalsOf, blocker, inputKeys, isDone, keysAfter, missingForNewRow, runInputs, sameValue, withoutLater, chooseSpec, createData, currentStep, hasValue, holds, listSpec, nextStep, passes, previousStep, readCtx, shownSteps, stepHref, substitute, withoutEmpty,
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
  assert.equal(stepHref("narrate", { world: "w" }, "story", { story: "s 1" }), "/workspace/wizards/narrate?step=story&world=w&story=s+1");
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
  assert.deepEqual(missingForNewRow("", { cast_id: null }, required, true), ["Name", "Cast id"]);
  assert.deepEqual(missingForNewRow("Old cook", { cast_id: null }, required, false), ["Cast id"]);
  assert.deepEqual(missingForNewRow("", { cast_id: "old-cook" }, required, false), ["Name"]);
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
