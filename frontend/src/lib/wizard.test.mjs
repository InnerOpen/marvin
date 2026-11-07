import assert from "node:assert/strict";
import { test } from "node:test";
import {
  chooseSpec, createData, currentStep, holds, listSpec, nextStep, passes, previousStep, readCtx, shownSteps, stepHref, substitute, withoutEmpty,
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
