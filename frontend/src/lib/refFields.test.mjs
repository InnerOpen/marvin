import assert from "node:assert/strict";
import { test } from "node:test";
import { refFieldsOf, refOf, refOptions, refScope, refTypesOf, withCurrent, tiered, refViasOf, refFilterOf, refListenOf, refMatchOf, narrowOptions, refScopeSplit } from "./refFields.ts";

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
    { key: "voice", ref: "voice", vias: [], filter: {}, listen: null, match: {} },
    { key: "narrator", ref: "voice", vias: [], filter: {}, listen: null, match: {} },
    { key: "actor", ref: "actor", vias: [], filter: {}, listen: null, match: {} },
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

test("ref_via: a well-formed one or a list of tiers counts, and refFieldsOf carries them", () => {
  const via = { entry_type: "cast-member", field: "voice", match: { story: "story" } };
  assert.deepEqual(refViasOf({ ref_via: via }), [via]);
  assert.deepEqual(refViasOf({ ref_via: [{ ...via, label: " This speaker " }, via] }), [{ ...via, label: "This speaker" }, via]);
  assert.deepEqual(refViasOf({}), []);
  assert.deepEqual(refViasOf({ ref_via: { entry_type: "cast-member", field: "voice", match: {} } }), []);
  assert.deepEqual(refViasOf({ ref_via: [{ entry_type: "cast-member", match: { story: "story" } }, via] }), [via]);
  assert.deepEqual(refFieldsOf({ fields: [{ key: "voice", type: "text", ref: "voice", ref_via: via }] }), [{ key: "voice", ref: "voice", vias: [via], filter: {}, listen: null, match: {} }]);
});

test("tiered: each option under the first tier that names it, the rest last; nobody named leaves the list as it is", () => {
  const all = [{ slug: "a", title: "Alice" }, { slug: "b", title: "Brian" }, { slug: "c", title: "Chris" }, { slug: "d", title: "Dan" }];
  const tiers = [{ label: "This speaker", slugs: ["c"] }, { label: "Cast", slugs: ["a", "c", "gone"] }];
  assert.deepEqual(tiered(all, tiers, "Other voices").map((o) => [o.slug, o.group]), [
    ["c", "This speaker"], ["a", "Cast"], ["b", "Other voices"], ["d", "Other voices"],
  ]);
  assert.equal(tiered(all, [{ label: "x", slugs: [] }], "y"), all);
  assert.equal(tiered(all, [{ label: "x", slugs: ["nobody"] }], "y"), all);
});

test("ref_filter and ref_listen: only well-formed ones count, and refOptions carries a recording to hear", () => {
  assert.deepEqual(refFilterOf({ ref_filter: { kind: "music", bad: 3, "": "x" } }), { kind: "music" });
  assert.deepEqual(refFilterOf({ ref_filter: ["kind"] }), {});
  assert.deepEqual(refFilterOf({}), {});
  assert.equal(refListenOf({ ref_listen: " audio " }), "audio");
  assert.equal(refListenOf({ ref_listen: "" }), null);
  const heard = { role: "audio", publicUrl: "https://cdn/x.mp3", mimeType: "audio/mpeg" };
  const entries = [
    { slug: "a", title: "Harbour", assets: [heard] },
    { slug: "b", title: "Wind", assets: [{ role: "audio", publicUrl: "https://cdn/p.png", mimeType: "image/png" }] },
    { slug: "c", title: "Silent", assets: [] },
  ];
  // options come sorted by title: Harbour, Silent, Wind
  assert.deepEqual(refOptions(entries, "audio").map((o) => [o.slug, o.audio ?? null]), [["a", "https://cdn/x.mp3"], ["c", null], ["b", null]]);
  assert.equal(refOptions(entries)[0].audio, undefined); // without a role to play, nothing is carried
});

test("ref_match: only well-formed name pairs count, and refFieldsOf carries them", () => {
  assert.deepEqual(refMatchOf({ ref_match: { story: "story", bad: 3, "": "x", also: "" } }), { story: "story" });
  assert.deepEqual(refMatchOf({ ref_match: ["story"] }), {});
  assert.deepEqual(refMatchOf({}), {});
  assert.deepEqual(refFieldsOf({ fields: [{ key: "chapter", type: "text", ref: "chapter", ref_match: { story: "story" } }] })[0].match, { story: "story" });
});

test("refOptions carries the matched fields' values, only when it is asked to", () => {
  const entries = [{ slug: "a", title: "A", dataJson: { story: "granny", n: 1 } }, { slug: "b", title: "B", dataJson: {} }];
  assert.deepEqual(refOptions(entries, null, ["story"]).map((o) => o.match), [{ story: "granny" }, {}]);
  assert.equal(refOptions(entries)[0].match, undefined);
});

test("narrowOptions: the entries of this entry's own story; nothing to match on leaves the list whole", () => {
  const options = [
    { slug: "g1", title: "Granny 1", match: { story: "granny" } },
    { slug: "o1", title: "Onion 1", match: { story: "onion" } },
    { slug: "g2", title: "Granny 2", match: { story: "granny" } },
  ];
  const match = { story: "story" };
  assert.deepEqual(narrowOptions(options, match, { story: "granny" }, "").map((o) => o.slug), ["g1", "g2"]);
  assert.equal(narrowOptions(options, match, { story: "" }, ""), options);
  assert.equal(narrowOptions(options, match, {}, ""), options);
  assert.equal(narrowOptions(options, {}, { story: "granny" }, ""), options);
});

test("narrowOptions keeps the one already chosen, marked when it belongs to another story, and a stale value as it is", () => {
  const options = [{ slug: "g1", title: "Granny 1", match: { story: "granny" } }, { slug: "o1", title: "Onion 1", match: { story: "onion" } }];
  const kept = narrowOptions(options, { story: "story" }, { story: "granny" }, "o1");
  assert.deepEqual(kept.map((o) => [o.slug, o.title]), [["g1", "Granny 1"], ["o1", "Onion 1 (not in this story)"]]);
  const stale = withCurrent(options, "gone");
  assert.deepEqual(narrowOptions(stale, { story: "story" }, { story: "granny" }, "gone").map((o) => [o.slug, o.title]), [["g1", "Granny 1"], ["gone", "gone (not found)"]]);
});

test("refScopeSplit: a required field always narrows, an optional one narrows to the entry's own or none (the shared library stays)", () => {
  const sound = { fields: [{ key: "story", type: "text" }, { key: "kind", type: "select" }, { key: "prompt", type: "text", required: true }] };
  assert.deepEqual(refScopeSplit(sound, { story: "granny", world: "w", prompt: "x" }), { fixed: { prompt: "x" }, open: { story: "granny" } });
  assert.deepEqual(refScopeSplit(sound, { story: "" }), { fixed: {}, open: {} });
  assert.deepEqual(refScopeSplit(null, { story: "g" }), { fixed: {}, open: {} });
  const actor = { fields: [{ key: "world", type: "text", required: true }] };
  assert.deepEqual(refScopeSplit(actor, { world: "w", story: "s" }), { fixed: { world: "w" }, open: {} });
});
