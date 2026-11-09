import assert from "node:assert/strict";
import { test } from "node:test";
import { refFieldsOf, refOf, refOptions, refScope, refTypesOf, withCurrent, preferred, refViaOf } from "./refFields.ts";

const schema = {
  fields: [
    { key: "voice", type: "text", ref: "voice" },
    { key: "narrator", type: "text", ref: " voice " },
    { key: "actor", type: "text", ref: "actor" },
    { key: "role", type: "text" },
    { key: "kind", type: "select", ref: "voice", options: ["a"] },
    { key: "blank", type: "text", ref: "" },
  ],
};

test("only a text field's non-empty ref refers to a type", () => {
  assert.equal(refOf({ type: "text", ref: "voice" }), "voice");
  assert.equal(refOf({ type: "select", ref: "voice" }), null);
  assert.equal(refOf({ type: "text", ref: 3 }), null);
  assert.equal(refOf({ type: "text" }), null);
});

test("the ref fields of a schema, with their types", () => {
  assert.deepEqual(refFieldsOf(schema), [
    { key: "voice", ref: "voice", via: null },
    { key: "narrator", ref: "voice", via: null },
    { key: "actor", ref: "actor", via: null },
  ]);
});

test("the referenced types are distinct", () => {
  assert.deepEqual(refTypesOf(schema), ["voice", "actor"]);
});

test("a missing schema refers to nothing", () => {
  assert.deepEqual(refTypesOf(null), []);
  assert.deepEqual(refTypesOf({}), []);
});

test("options are sorted by title ignoring case, and an entry without a slug is left out", () => {
  const options = refOptions([
    { slug: "b", title: "bravo" },
    { slug: "a", title: "Alpha" },
    { slug: "", title: "Nameless" },
    { slug: "c", title: "" },
  ]);
  assert.deepEqual(options, [
    { slug: "a", title: "Alpha" },
    { slug: "b", title: "bravo" },
    { slug: "c", title: "c" },
  ]);
});

test("a current value missing from the options is kept, marked not found", () => {
  const options = [{ slug: "a", title: "Alpha" }];
  assert.deepEqual(withCurrent(options, "gone"), [...options, { slug: "gone", title: "gone (not found)" }]);
});

test("a current value in the options, or none, adds nothing", () => {
  const options = [{ slug: "a", title: "Alpha" }];
  assert.equal(withCurrent(options, "a"), options);
  assert.equal(withCurrent(options, ""), options);
  assert.equal(withCurrent(options, null), options);
});

test("a wizard's choices narrow a referenced type by the fields it has", () => {
  const actor = { fields: [{ key: "world", type: "text" }, { key: "build", type: "text" }] };
  assert.deepEqual(refScope(actor, { world: "w", story: "s" }), { world: "w" });
});

test("a type with none of the chosen fields is not narrowed", () => {
  assert.deepEqual(refScope({ fields: [{ key: "name", type: "text" }] }, { world: "w", story: "s" }), {});
  assert.deepEqual(refScope(null, { world: "w" }), {});
});

test("ref_via: only a well-formed one counts, and a field's refFieldsOf carries it", () => {
  const via = { entry_type: "cast-member", field: "voice", match: { story: "story" } };
  assert.deepEqual(refViaOf({ ref_via: via }), via);
  assert.equal(refViaOf({}), null);
  assert.equal(refViaOf({ ref_via: { entry_type: "cast-member", field: "voice", match: {} } }), null);
  assert.equal(refViaOf({ ref_via: { entry_type: "cast-member", match: { story: "story" } } }), null);
  assert.deepEqual(refFieldsOf({ fields: [{ key: "voice", type: "text", ref: "voice", ref_via: via }] }), [{ key: "voice", ref: "voice", via }]);
});

test("preferred: the story's cast first under their heading, the rest under another; nobody cast leaves the list as it is", () => {
  const all = [{ slug: "a", title: "Alice" }, { slug: "b", title: "Brian" }, { slug: "c", title: "Chris" }];
  assert.deepEqual(preferred(all, ["c", "a", "gone"], "Cast in this story", "Other voices").map((o) => [o.slug, o.group]), [
    ["a", "Cast in this story"], ["c", "Cast in this story"], ["b", "Other voices"],
  ]);
  assert.equal(preferred(all, [], "x", "y"), all);
  assert.equal(preferred(all, ["nobody"], "x", "y"), all);
});
