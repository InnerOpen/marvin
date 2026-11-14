import { test } from "node:test";
import assert from "node:assert/strict";
import { batchAdjustAllowed, chosen, cleanFileName, jobLine, jobOver, pictureName, templateChoices } from "./uploadTemplate.ts";

const TYPES = [
  {
    slug: "artwork",
    name: "Artwork",
    picturePresetsJson: [{ slug: "ornament-look", name: "Ornament look", steps: [] }],
    templatesJson: [
      { slug: "ornament", name: "Ornament", picturePreset: "ornament-look" },
      { slug: "plain", name: "Plain" },
    ],
  },
  { slug: "venue", name: "Venue", templatesJson: null },
  { slug: "page", name: "Page" },
];

test("every template of every type is a choice, saying its preset", () => {
  const choices = templateChoices(TYPES);
  assert.deepEqual(
    choices.map((c) => [c.value, c.label, c.picturePreset]),
    [
      ["artwork/ornament", "Artwork: Ornament, treated with Ornament look", "ornament-look"],
      ["artwork/plain", "Artwork: Plain", null],
    ],
  );
});

test("none (the default) is no choice, so an upload is as it always was", () => {
  const choices = templateChoices(TYPES);
  assert.equal(chosen(choices, ""), null);
  assert.equal(chosen(choices, null), null);
  assert.equal(chosen(choices, "artwork/gone"), null);
  assert.equal(chosen(choices, "artwork/plain")?.template, "plain");
  assert.equal(templateChoices([]).length, 0);
});

test("a picture is named by the AI, else by its cleaned file name", () => {
  assert.equal(cleanFileName("IMG_4491.jpeg"), "IMG 4491");
  assert.equal(cleanFileName("snowy-owl_final.PNG"), "snowy owl final");
  assert.deepEqual(pictureName({ name: " \"Red cardinal ornament\" " }, "IMG_1.jpg"), { name: "Red cardinal ornament", named: true });
  assert.deepEqual(pictureName({ name: "" }, "IMG_1.jpg"), { name: "IMG 1", named: false });
  assert.deepEqual(pictureName(null, "DSC_0042.JPG"), { name: "DSC 0042", named: false });
});

test("the batch adjustments are off while a preset treats the pictures", () => {
  const [withPreset, plain] = templateChoices(TYPES);
  assert.equal(batchAdjustAllowed(withPreset), false);
  assert.equal(batchAdjustAllowed(plain), true);
  assert.equal(batchAdjustAllowed(null), true);
});

test("a treatment job in words", () => {
  assert.equal(jobLine({ state: "running", done: 3, total: 50 }), "Treating 4 of 50…");
  assert.equal(jobLine({ state: "done", total: 50, failed: 0 }), "Treated all 50.");
  assert.match(jobLine({ state: "done", total: 5, failed: 1, errors: ["Bad: not a picture"] }), /Treated 4 of 5; 1 could not be: Bad/);
  assert.match(jobLine({ state: "queued", total: 2 }), /Waiting/);
  assert.equal(jobOver({ state: "failed" }), true);
  assert.equal(jobOver({ state: "running" }), false);
});
