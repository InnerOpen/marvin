// The custom AI step's answer fields ↔ JSON Schema (customStep.ts).

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { fieldsFromSchema, schemaFromFields } from "./customStep.ts";

describe("answer fields", () => {
  test("round-trip through the schema, every field required", () => {
    const fields = [
      { name: "caption", kind: "text", description: "For the post" },
      { name: "tempo_bpm", kind: "whole number", description: "" },
      { name: "instruments", kind: "list of text", description: "" },
      { name: "spam", kind: "yes/no", description: "" },
    ];
    const schema = schemaFromFields(fields);
    assert.deepEqual(schema.required, ["caption", "tempo_bpm", "instruments", "spam"]);
    assert.deepEqual(schema.properties.instruments, { type: "array", items: { type: "string" } });
    assert.deepEqual(fieldsFromSchema(schema), fields);
  });

  test("a schema the list can't show is left to JSON", () => {
    assert.equal(
      fieldsFromSchema({ type: "object", properties: { q: { type: "string", minLength: 10 } }, required: ["q"] }),
      null,
    );
    assert.equal(fieldsFromSchema({ type: "object", properties: { q: { type: "string" } } }), null); // optional field
    assert.deepEqual(fieldsFromSchema(undefined), []);
  });

  test("bad names and empty lists are refused with a reason", () => {
    assert.throws(() => schemaFromFields([]), /at least one/);
    assert.throws(() => schemaFromFields([{ name: "Caption!", kind: "text", description: "" }]), /lower-case/);
    assert.throws(
      () =>
        schemaFromFields([
          { name: "a", kind: "text", description: "" },
          { name: "a", kind: "number", description: "" },
        ]),
      /twice/,
    );
  });
});
