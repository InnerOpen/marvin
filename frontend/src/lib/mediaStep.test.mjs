// The "Process an image" step's form ↔ definition (mediaStep.ts).

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  filledRows,
  MEDIA_OPS,
  mediaFields,
  OP_FIELDS,
  sourceChoice,
  sourceFromChoice,
  templateRows,
} from "./mediaStep.ts";

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

describe("a render step", () => {
  test("takes a template or its own html, at most 4000 px a side", () => {
    assert.deepEqual(mediaFields("render", { template: "quote", width: "800" }), { template: "quote", width: 800 });
    assert.throws(() => mediaFields("render", {}), /one of them/);
    assert.throws(() => mediaFields("render", { template: "quote", html: "<p></p>" }), /one of them/);
    assert.throws(() => mediaFields("render", { html: "<p></p>", width: "5000" }), /4000/);
  });

  test("rows show the template's names first and keep what the step had", () => {
    assert.deepEqual(templateRows(["quote", "attribution"], { attribution: "Ada", extra: "x" }), {
      quote: "",
      attribution: "Ada",
      extra: "x",
    });
    assert.deepEqual(filledRows({ quote: "", attribution: "Ada" }), { attribution: "Ada" });
    assert.equal(filledRows({ quote: "" }), null);
  });
});

test("document and privacy ops: pages as numbers, what to look for as a list, boxes as given", () => {
  assert.deepEqual(mediaFields("pages", { page: "2", count: "3", format: "webp" }), { page: 2, count: 3, format: "webp" });
  assert.throws(() => mediaFields("pages", { count: "40" }), /count must be a whole number from 1 to 10/);
  assert.deepEqual(mediaFields("extract_text", { ocr: "auto" }), {}); // the default
  assert.deepEqual(mediaFields("extract_text", { ocr: "never" }), { ocr: "never" });
  assert.deepEqual(mediaFields("find_sensitive", { find: "Face, plate" }), { find: ["face", "plate"] });
  assert.deepEqual(mediaFields("find_sensitive", { find: "face, plate, text" }), {}); // all of them is the default
  assert.throws(() => mediaFields("redact", { find: "tattoo" }), /not tattoo/);
  assert.deepEqual(mediaFields("redact", { boxes: "[[0.1, 0.2, 0.3, 0.3]]" }), { boxes: [[0.1, 0.2, 0.3, 0.3]] });
  assert.deepEqual(mediaFields("redact", { boxes: "${steps.find.output.regions}" }), { boxes: "${steps.find.output.regions}" });
});

test("zip and printed PDFs: files needed; PDF only for a render", () => {
  assert.deepEqual(mediaFields("zip", { files: "${steps.set.output.rows}", name: "Archive" }), { files: "${steps.set.output.rows}", name: "Archive" });
  assert.throws(() => mediaFields("zip", {}), /zip needs files/);
  assert.deepEqual(mediaFields("render", { template: "guide", format: "pdf" }), { template: "guide", format: "pdf" });
  assert.throws(() => mediaFields("convert", { format: "pdf" }), /PDF is for a render/);
});
