// The `x-marvin-options` helpers (integrationOptions.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { filterOptions, findOption, getArg, hintedInputs, optionsHint, setArg } from "./integrationOptions.ts";

const hinted = { type: "string", "x-marvin-options": { action: "list_workflows", value: "path", label: "name" } };

describe("optionsHint", () => {
  test("reads a well-formed hint", () => {
    assert.deepEqual(optionsHint(hinted), { action: "list_workflows", value: "path", label: "name" });
  });

  test("label and args are optional", () => {
    const prop = { "x-marvin-options": { action: "list", value: "id", args: { active: true } } };
    assert.equal(optionsHint(prop).action, "list");
  });

  test("no hint, or a malformed one, is null (the input stays free text)", () => {
    for (const prop of [
      undefined,
      null,
      "string",
      { type: "string" },
      { "x-marvin-options": "list" },
      { "x-marvin-options": { value: "id" } },
      { "x-marvin-options": { action: "list" } },
      { "x-marvin-options": { action: "list", value: "id", label: 3 } },
    ]) {
      assert.equal(optionsHint(prop), null);
    }
  });
});

test("hintedInputs keeps schema order and skips plain inputs", () => {
  const schema = { properties: { data: { type: "object" }, path: hinted, other: hinted } };
  assert.deepEqual(hintedInputs(schema), ["path", "other"]);
  assert.deepEqual(hintedInputs(undefined), []);
});

describe("filterOptions / findOption", () => {
  const options = [
    { value: "marvin/inquiry", label: "Inquiry" },
    { value: 7, label: "Seven" },
  ];

  test("matches label or value, case-insensitively", () => {
    assert.deepEqual(filterOptions(options, "inq"), [options[0]]);
    assert.deepEqual(filterOptions(options, "MARVIN/"), [options[0]]);
    assert.deepEqual(filterOptions(options, "7"), [options[1]]);
    assert.deepEqual(filterOptions(options, "  "), options);
  });

  test("finds by value compared as text", () => {
    assert.equal(findOption(options, "7"), options[1]);
    assert.equal(findOption(options, ""), undefined);
    assert.equal(findOption(options, "$event.payload.path"), undefined);
  });
});

describe("setArg / getArg", () => {
  test("sets one key and keeps the rest", () => {
    const next = setArg('{"data": {"a": 1}}', "path", "marvin/inquiry");
    assert.deepEqual(JSON.parse(next), { data: { a: 1 }, path: "marvin/inquiry" });
    assert.equal(getArg(next, "path"), "marvin/inquiry");
  });

  test("an empty value removes the key; empty args become empty text", () => {
    assert.equal(setArg('{"path": "x"}', "path", ""), "");
    assert.deepEqual(JSON.parse(setArg("", "path", 7)), { path: 7 });
  });

  test("text that isn't a JSON object is left alone", () => {
    assert.equal(setArg("{not json", "path", "x"), null);
    assert.equal(setArg("[1, 2]", "path", "x"), null);
    assert.equal(getArg("{not json", "path"), undefined);
  });
});
