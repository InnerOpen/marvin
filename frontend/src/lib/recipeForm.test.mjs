// The entry type page's recipe boxes (recipeForm.ts): Authoring instructions and Voice live outside the JSON.
// Run with `npm test` (plain `node --test`). Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { foldRecipe, splitRecipe } from "./recipeForm.ts";

describe("splitRecipe", () => {
  test("takes the instructions and the voice out of the JSON", () => {
    const out = splitRecipe({ instructions: "Short.", enrichment: { voice: "Wry.", alt: true }, assets: { min: 1 } });
    assert.equal(out.instructions, "Short.");
    assert.equal(out.voice, "Wry.");
    assert.deepEqual(JSON.parse(out.json), { enrichment: { alt: true }, assets: { min: 1 } });
  });

  test("drops an enrichment left empty and gives empty JSON for nothing else", () => {
    assert.deepEqual(splitRecipe({ enrichment: { voice: "Wry." } }), { instructions: "", voice: "Wry.", json: "" });
    assert.deepEqual(splitRecipe(null), { instructions: "", voice: "", json: "" });
  });
});

describe("foldRecipe", () => {
  test("puts the voice back under enrichment next to its other keys", () => {
    const out = JSON.parse(foldRecipe('{"enrichment": {"alt": true}}', "", " Wry. "));
    assert.deepEqual(out, { enrichment: { alt: true, voice: "Wry." } });
  });

  test("a blank voice removes it, and an emptied enrichment goes too", () => {
    assert.equal(foldRecipe('{"enrichment": {"voice": "Old."}}', "", ""), "");
    assert.deepEqual(JSON.parse(foldRecipe("", "Short.", "")), { instructions: "Short." });
  });

  test("invalid or non-object JSON is left for the server to reject", () => {
    assert.equal(foldRecipe("{nope", "", "Wry."), null);
    assert.equal(foldRecipe("[1]", "", "Wry."), null);
    assert.deepEqual(JSON.parse(foldRecipe('{"enrichment": "odd"}', "", "Wry.")), { enrichment: "odd" });
  });
});
