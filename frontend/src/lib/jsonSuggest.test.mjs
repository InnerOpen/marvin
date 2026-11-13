import test from "node:test";
import assert from "node:assert/strict";
import { normalChoice, readSuggest, suggestionFor, noteFor, nextBox } from "./jsonSuggest.ts";

const suggest = readSuggest({ from: "camera", values: { "Push in": { from: { zoom: 1 }, to: { zoom: 1.22 } }, Rocking: { rock: { degrees: 2.5 } } } });

test("a choice is compared however it is written", () => {
  assert.equal(normalChoice(" Push in "), "push-in");
  assert.equal(normalChoice("push_in"), "push-in");
  assert.equal(normalChoice(undefined), "");
});

test("a definition without from or values is not a suggestion", () => {
  assert.equal(readSuggest(null), null);
  assert.equal(readSuggest({ from: "camera" }), null);
  assert.equal(readSuggest({ values: {} }), null);
  assert.equal(readSuggest({ from: "camera", values: [] }), null);
  assert.ok(suggest);
});

test("the suggestion is the pretty JSON of the choice, empty for none or an unknown one", () => {
  assert.equal(suggestionFor(suggest, "push in"), JSON.stringify({ from: { zoom: 1 }, to: { zoom: 1.22 } }, null, 2));
  assert.equal(suggestionFor(suggest, "Rocking"), JSON.stringify({ rock: { degrees: 2.5 } }, null, 2));
  assert.equal(suggestionFor(suggest, ""), "");
  assert.equal(suggestionFor(suggest, "Whip pan"), "");
});

test("the note names the choice, and is empty when nothing is shown", () => {
  assert.equal(noteFor(suggest, "Push in", "{...}"), "From Push in. Edit it to make it your own.");
  assert.equal(noteFor({ ...suggest, note: "Using {pick}" }, "Rocking", "{...}"), "Using Rocking");
  assert.equal(noteFor(suggest, "", ""), "");
});

test("the box follows the choice while empty or untouched, and keeps what was written", () => {
  assert.deepEqual(nextBox("", "", "A"), { text: "A", suggested: true });
  assert.deepEqual(nextBox("A", "A", "B"), { text: "B", suggested: true });
  assert.deepEqual(nextBox("mine", "A", "B"), { text: "mine", suggested: false });
  assert.deepEqual(nextBox("A", "A", ""), { text: "", suggested: false }, "the choice was cleared: the box empties");
});
