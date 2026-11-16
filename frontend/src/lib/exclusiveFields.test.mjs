import assert from "node:assert/strict";
import { test } from "node:test";
import { blockedNote, conflictNote, exclusiveState, isFilled, partnersOf, uploadRefusal, writeRefusal } from "./exclusiveFields.ts";

const fountain = { key: "fountain", label: "Fountain", type: "markdown", exclusive_with: ["fountain_file"] };
const file = { key: "fountain_file", label: "Fountain file", type: "asset" }; // the other side need not say it
const premise = { key: "premise", label: "Premise", type: "text" };
const fields = [premise, fountain, file];

test("blank text, an empty id list and nothing hold nothing", () => {
  for (const v of [null, undefined, "", "  \n", [], ["  "], {}]) assert.equal(isFilled(v), false, JSON.stringify(v));
  for (const v of ["x", "id-1", "id-1,", ["id"], 0, false]) assert.equal(isFilled(v), true, JSON.stringify(v));
});

test("a pair is read from either side; a name that is no field is ignored", () => {
  assert.deepEqual(partnersOf(fields, "fountain").map((f) => f.key), ["fountain_file"]);
  assert.deepEqual(partnersOf(fields, "fountain_file").map((f) => f.key), ["fountain"]);
  assert.deepEqual(partnersOf(fields, "premise"), []);
  assert.deepEqual(partnersOf([{ ...fountain, exclusive_with: ["gone"] }], "fountain"), []);
});

test("one filled closes the other; neither or one leaves no warning; both from before warns on both", () => {
  assert.deepEqual(exclusiveState(fields, {}), { fountain: { blockedBy: null, conflicts: [] }, fountain_file: { blockedBy: null, conflicts: [] } });
  assert.deepEqual(exclusiveState(fields, { fountain: "INT. PORCH" }).fountain_file, { blockedBy: "fountain", conflicts: [] });
  assert.deepEqual(exclusiveState(fields, { fountain: "INT. PORCH" }).fountain, { blockedBy: null, conflicts: [] });
  assert.deepEqual(exclusiveState(fields, { fountain_file: "a1", fountain: "   " }).fountain, { blockedBy: "fountain_file", conflicts: [] });
  const both = exclusiveState(fields, { fountain: "INT.", fountain_file: "a1" });
  assert.deepEqual(both.fountain, { blockedBy: null, conflicts: ["fountain_file"] });
  assert.deepEqual(both.fountain_file, { blockedBy: null, conflicts: ["fountain"] });
  assert.equal("premise" in both, false);
});

test("the lines say where it is and how to free the field", () => {
  assert.equal(blockedNote(fountain, file), "“Fountain file” holds it. Remove the file to write it here instead.");
  assert.equal(blockedNote(file, fountain), "“Fountain” holds it as text. Clear that text to attach a file here instead.");
  assert.match(conflictNote(fountain, file), /Both “Fountain” and “Fountain file” are filled in, and only one is used/);
  assert.match(uploadRefusal(file, fountain, "Porch"), /^Porch already has “Fountain” filled in, .* Empty “Fountain” first \(clear the text/);
});

test("a write is refused as the server refuses it, before it is sent", () => {
  assert.equal(writeRefusal(fields, {}, { fountain: "x" }), null);
  assert.match(writeRefusal(fields, {}, { fountain: "x", fountain_file: "a1" }), /take one or the other, and this would fill both/);
  assert.equal(
    writeRefusal(fields, { fountain_file: "a1" }, { fountain: "INT.", fountain_file: "a1" }),
    "“Fountain file” already holds something, and “Fountain” is used instead of it, not with it. Empty “Fountain file” first (remove the file), then fill “Fountain”.",
  );
  const both = { fountain: "x", fountain_file: "a1" };
  assert.equal(writeRefusal(fields, both, { ...both, premise: "p" }), null);
});
