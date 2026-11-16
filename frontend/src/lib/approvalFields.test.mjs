// What an approval card sends for its boxes (approvalFields.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { boxRows, changedFields, choiceLabel, fieldsFromForm, unchanged } from "./approvalFields.ts";

const PROMPT = { name: "prompt", label: "Prompt", value: "  A knife on a board.\nClose up.\n" };

describe("changedFields", () => {
  test("a box left alone is not sent, so the text as asked goes on byte for byte", () => {
    assert.deepEqual(changedFields([PROMPT], { prompt: PROMPT.value }), {});
  });
  test("a form's \\r\\n and the one leading line break a text box drops are not changes", () => {
    assert.equal(unchanged(PROMPT, "  A knife on a board.\r\nClose up.\r\n"), true);
    assert.equal(unchanged({ ...PROMPT, value: "\nLine" }, "Line"), true);
  });
  test("a changed box is sent with \\n line ends, and names the card has no box for are dropped", () => {
    assert.deepEqual(changedFields([PROMPT], { prompt: "A cleaver.\r\nSlow.", tone: "x" }), {
      prompt: "A cleaver.\nSlow.",
    });
  });
  test("a card without boxes sends none", () => {
    assert.deepEqual(changedFields(null, { prompt: "x" }), {});
  });
});

describe("fieldsFromForm", () => {
  test("reads each box from its field.<name> input, line ends as \\n, and nothing else", () => {
    const form = new Map([
      ["field.prompt", "A cleaver.\r\nSlow."],
      ["note", "ok"],
      ["field.", "x"],
    ]);
    assert.deepEqual(fieldsFromForm(form), { prompt: "A cleaver.\nSlow." });
  });
});

describe("choiceLabel", () => {
  test("the redo choice says it carries the change, only once a box is changed", () => {
    assert.equal(choiceLabel("Redo", "Redo", true), "Redo with changes");
    assert.equal(choiceLabel("Redo", "Redo", false), "Redo");
    assert.equal(choiceLabel("Keep", "Redo", true), "Keep");
    assert.equal(choiceLabel("Redo", null, true), "Redo");
  });
});

describe("boxRows", () => {
  test("between 3 and 14 lines, long lines counted as they wrap", () => {
    assert.equal(boxRows("short"), 3);
    assert.equal(boxRows("x".repeat(900)), 10);
    assert.equal(boxRows("line\n".repeat(40)), 14);
  });
});
