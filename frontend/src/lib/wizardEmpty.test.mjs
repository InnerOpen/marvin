import assert from "node:assert/strict";
import { test } from "node:test";
import { emptyLine, emptyLinks, fillerOf, lackingOf, narrowedBy } from "./wizardEmpty.ts";

const def = {
  title: "Cast a role",
  steps: [
    { id: "world", kind: "choose", title: "World", as: "world", entry_type: "world" },
    { id: "series", kind: "choose", title: "Series", as: "series", entry_type: "series", optional: true, scope: { world: "${world}" } },
    { id: "story", kind: "choose", title: "Story", as: "story", entry_type: "story", scope: { world: "${world}", series: "${series}" } },
    { id: "role", kind: "choose", title: "Role", as: "role", entry_type: "role", scope: { story: "${story}" } },
    { id: "assign", kind: "form", title: "The actor", entry: "role", fields: ["actor", "costume"] },
    { id: "write", kind: "run", title: "Write the prompt", workflow: "write-prompt", report: { entry: "role", field: "master_prompt" }, when: { ctx: "how", op: "eq", value: "make" } },
    { id: "sheet", kind: "upload", title: "The sheet", entry: "role", field: "sheet" },
    { id: "lines", kind: "run", title: "Voice for the lines", workflow: "voice-lines", requires: { entry: "role", field: "voice" } },
    { id: "cast", kind: "gallery", title: "The cast", entry_type: "cast-member", parent: "story", parent_field: "story" },
    { id: "pictures", kind: "choose", title: "Pictures", as: "pictures", multiple: true, assets: { asset_type: "image", unused: true } },
  ],
};
const at = (id) => def.steps.find((s) => s.id === id);
const ctx = { world: "oz", story: "tin", role: "young-man" };

test("an empty step is narrowed by the earlier choices it reads, the answered ones only", () => {
  assert.deepEqual(narrowedBy(def, ctx, at("story")).map((s) => s.id), ["world"]); // the series was skipped: it narrows nothing
  assert.deepEqual(narrowedBy(def, { ...ctx, series: "s1" }, at("story")).map((s) => s.id), ["world", "series"]);
  assert.deepEqual(narrowedBy(def, ctx, at("cast")).map((s) => s.id), ["story"]); // the entry it hangs under
  assert.deepEqual(narrowedBy(def, ctx, at("world")), []);
});

test("an empty step says why in plain words: whose it is, what narrowed it, what it looks for, or that there is none", () => {
  assert.equal(emptyLine(at("cast"), "Cast member", { owner: "The Tin Soldier", todo: "Add the first one below." }), "The Tin Soldier has no cast member yet. Add the first one below.");
  assert.equal(emptyLine(at("role"), "Role", { narrowed: narrowedBy(def, ctx, at("role")) }), "No role belongs to what you chose in “Story” yet.");
  assert.equal(emptyLine(at("story"), "Story", { narrowed: narrowedBy(def, { ...ctx, series: "s1" }, at("story")) }), "No story belongs to what you chose in “World” and “Series” yet.");
  assert.equal(emptyLine(at("pictures"), "file"), "No file fits what this step looks for right now.");
  assert.equal(emptyLine(at("world"), "World"), "This workspace has no world yet.");
});

test("the package's own empty line wins over the default", () => {
  assert.equal(emptyLine({ ...at("role"), empty: " No lines in this beat. " }, "Role", { owner: "Beat 3", todo: "Add one." }), "No lines in this beat.");
});

test("an empty step points at the step its package names, then at the choices to change", () => {
  const role = { ...at("role"), empty_next: { step: "story" } };
  assert.deepEqual(emptyLinks(def, ctx, role, "cast", narrowedBy(def, ctx, role)), [{ label: "Go to “Story”", href: "/workspace/setups/cast?step=story&world=oz&story=tin&role=young-man" }]);
  assert.deepEqual(emptyLinks(def, ctx, { ...role, empty_next: { step: "world", text: "Pick another world" } }, "cast", narrowedBy(def, ctx, role)).map((l) => l.label), ["Pick another world", "Change “Story”"]);
  assert.deepEqual(emptyLinks(def, ctx, at("role"), "cast"), []);
});

test("an empty step may point at a path in the app, and never outside it or at a step that is not before it", () => {
  const to = (empty_next) => emptyLinks(def, ctx, { ...at("role"), empty_next }, "cast");
  assert.deepEqual(to({ text: "Open the open call", href: "/workspace/setups/open-call" }), [{ label: "Open the open call", href: "/workspace/setups/open-call" }]);
  assert.deepEqual(to({ text: "Elsewhere", href: "https://example.com" }), []);
  assert.deepEqual(to({ text: "Elsewhere", href: "//example.com" }), []);
  assert.deepEqual(to({ step: "lines" }), []); // a later step
  assert.deepEqual(to({ step: "write" }), []); // not shown: its `when` does not hold
});

test("what a run requires is filled by the earlier form, upload or run that writes it", () => {
  assert.equal(fillerOf(def, ctx, at("lines"), { entry: "role", field: "actor" })?.id, "assign");
  assert.equal(fillerOf(def, ctx, at("lines"), { entry: "role", field: "sheet" })?.id, "sheet");
  assert.equal(fillerOf(def, ctx, at("lines"), { entry: "role", field: "master_prompt" }), null); // the run that writes it is not shown
  assert.equal(fillerOf(def, { ...ctx, how: "make" }, at("lines"), { entry: "role", field: "master_prompt" })?.id, "write");
  assert.equal(fillerOf(def, ctx, at("lines"), { entry: "role", field: "voice" }), null);
  assert.equal(fillerOf(def, { world: "oz", story: "tin" }, at("lines"), { entry: "role", field: "voice" })?.id, "role"); // not chosen: the step that picks it
});

test("a run whose requirement is missing says what is empty and where to fill it", () => {
  const entry = { id: "e1", title: "The Young Man" };
  assert.deepEqual(lackingOf(def, ctx, at("lines"), "cast", { label: "Voice (ElevenLabs id)", entry }), {
    text: "“Voice” on The Young Man is empty, and this step needs it.",
    link: { label: "Open The Young Man to fill it in", href: "/workspace/entries/e1", out: true },
  });
  const needsActor = { ...at("lines"), requires: { entry: "role", field: "actor" } };
  assert.deepEqual(lackingOf(def, ctx, needsActor, "cast", { entry }), {
    text: "“actor” on The Young Man is empty, and this step needs it.",
    link: { label: "Go to “The actor”", href: "/workspace/setups/cast?step=assign&world=oz&story=tin&role=young-man" },
  });
  assert.deepEqual(lackingOf(def, { world: "oz", story: "tin" }, at("lines"), "cast", {}), {
    text: "This step needs the role chosen first.",
    link: { label: "Go to “Role”", href: "/workspace/setups/cast?step=role&world=oz&story=tin" },
  });
});
