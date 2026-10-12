// The "Process an image" step's form ↔ definition (mediaStep.ts).

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { MEDIA_OPS, mediaFields, OP_FIELDS, sourceChoice, sourceFromChoice } from "./mediaStep.ts";

describe("where the picture comes from", () => {
  test("each stored source reads back as the form shows it, and goes back unchanged", () => {
    for (const [source, mode, value] of [
      [undefined, "current", ""],
      ["${asset.id}", "current", ""],
      ["${steps.square.output.asset.id}", "step", "square"],
      ["role:hero", "role", "hero"],
      ["harbour-photo", "asset", "harbour-photo"],
    ]) {
      assert.deepEqual(sourceChoice(source), { mode, value });
      assert.equal(sourceFromChoice(mode, value), mode === "current" ? null : source);
    }
  });

  test("a source that needs a value says so", () => {
    assert.throws(() => sourceFromChoice("role", " "), /role/);
    assert.throws(() => sourceFromChoice("step", ""), /step's id/);
  });
});

describe("an op's fields", () => {
  test("numbers become numbers, blanks and defaults are left out", () => {
    assert.deepEqual(mediaFields("resize", { width: "800", height: "", fit: "inside", format: "webp", quality: "" }), {
      width: 800,
      format: "webp",
    });
    assert.deepEqual(mediaFields("crop", { aspect: "4:5", focus: "center" }), { aspect: "4:5" });
    assert.deepEqual(mediaFields("palette", { colors: "6", width: "100" }), { colors: 6 }); // other ops' fields ignored
  });

  test("the server's rules are checked before saving", () => {
    assert.throws(() => mediaFields("resize", {}), /width or a height/);
    assert.throws(() => mediaFields("resize", { width: "100", fit: "cover" }), /both a width and a height/);
    assert.throws(() => mediaFields("resize", { width: "12.5" }), /whole number/);
    assert.throws(() => mediaFields("crop", { aspect: "wide" }), /1:1/);
    assert.throws(() => mediaFields("convert", {}), /format/);
    assert.throws(() => mediaFields("grade", { preset: "  " }), /preset/);
    assert.throws(() => mediaFields("palette", { colors: "40" }), /1 to 16/);
  });

  test("every op has a label and a field list", () => {
    assert.deepEqual(MEDIA_OPS.map((o) => o.op).sort(), Object.keys(OP_FIELDS).sort());
  });
});
