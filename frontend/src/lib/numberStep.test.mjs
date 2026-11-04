// A number field's input step (numberStep.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { numberStep } from "./numberStep.ts";

describe("numberStep", () => {
  test("takes any decimal when the field sets no step", () => {
    assert.equal(numberStep(undefined), "any");
    assert.equal(numberStep(null), "any");
  });
  test("keeps a step the field sets", () => {
    assert.equal(numberStep(0.05), 0.05);
    assert.equal(numberStep(1), 1);
  });
  test("a zero, negative or non-finite step is no step", () => {
    assert.equal(numberStep(0), "any");
    assert.equal(numberStep(-1), "any");
    assert.equal(numberStep(Number.NaN), "any");
  });
});
