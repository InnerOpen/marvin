import assert from "node:assert/strict";
import { test } from "node:test";
import { cueSpecsFor, parseCues, serializeCues } from "./cueFields.ts";

const views = [
  {
    definition: {
      kind: "timeline",
      spine: { entry_type: "beat" },
      lanes: [
        { id: "lines", title: "Lines", entry_type: "speech-line", in: "beat" },
        { id: "sounds", title: "Sounds", entry_type: "sound", placed: { field: "sounds", ref: "sound", at: "at" }, audio: "audio", seconds: "duration_seconds" },
        { id: "again", title: "Again", entry_type: "sound", placed: { field: "sounds", ref: "sound", at: "at" } },
      ],
    },
  },
  { definition: { kind: "timeline", spine: { entry_type: "story" }, lanes: [{ id: "x", entry_type: "sound", placed: { field: "cues", ref: "s", at: "t" } }] } },
];

test("the cue lists of a type come from the views whose spine it is, one per field", () => {
  const specs = cueSpecsFor(views, "beat");
  assert.deepEqual(specs, [{ field: "sounds", ref: "sound", at: "at", entryType: "sound", title: "Sounds", audio: "audio", seconds: "duration_seconds" }]);
  assert.deepEqual(cueSpecsFor(views, "scene"), []);
  assert.equal(cueSpecsFor(views, "story")[0].title, "x");
});

test("cues parse from JSON text or a list, keep what else they carried, and serialize in time order without empty ones", () => {
  const spec = { ref: "sound", at: "at" };
  const cues = parseCues('[{"sound":"rain","at":"2.5","volume":0.4},{"sound":"gull","at":1},{"bogus":true},{"sound":"","at":3}]', spec);
  assert.deepEqual(cues.map((c) => [c.ref, c.at, c.rest]), [["rain", 2.5, { volume: 0.4 }], ["gull", 1, {}], ["", 0, { bogus: true }], ["", 3, {}]]);
  assert.deepEqual(JSON.parse(serializeCues(cues, spec)), [{ sound: "gull", at: 1 }, { volume: 0.4, sound: "rain", at: 2.5 }]);
  assert.deepEqual(parseCues([{ sound: "a", at: -2 }], spec), [{ ref: "a", at: 0, level: null, rest: {} }]);
  assert.deepEqual(parseCues("not json", spec), []);
  assert.deepEqual(parseCues({ sound: "a" }, spec), []);
  assert.equal(serializeCues([], spec), "[]");
});

test("a placed lane's filter limits what is offered: well-formed text values only, nothing when there are none", () => {
  const withFilter = (filter) => [{ definition: { kind: "timeline", spine: { entry_type: "beat" }, lanes: [{ id: "sounds", entry_type: "sound", placed: { field: "sounds", ref: "sound", at: "at", filter } }] } }];
  assert.deepEqual(cueSpecsFor(withFilter({ kind: "effect" }), "beat")[0].filter, { kind: "effect" });
  assert.deepEqual(cueSpecsFor(withFilter({ kind: "effect", bad: 3, "": "x" }), "beat")[0].filter, { kind: "effect" });
  for (const nothing of [{}, ["kind"], "effect", { kind: 3 }, undefined]) assert.equal("filter" in cueSpecsFor(withFilter(nothing), "beat")[0], false);
});

test("a cue's own level: read when the lane names the key, written back only when set, and never invented", () => {
  const withLevel = { ref: "sound", at: "at", volume: "volume" };
  const cues = parseCues('[{"sound":"rain","at":2.5,"volume":0.4},{"sound":"gull","at":1},{"sound":"bell","at":3,"volume":7}]', withLevel);
  assert.deepEqual(cues.map((c) => [c.ref, c.level, c.rest]), [["rain", 0.4, {}], ["gull", null, {}], ["bell", null, { volume: 7 }]]); // 7 is not a level: left as it was
  assert.deepEqual(JSON.parse(serializeCues(cues, withLevel)), [
    { sound: "gull", at: 1 },
    { sound: "rain", at: 2.5, volume: 0.4 },
    { sound: "bell", at: 3, volume: 7 },
  ]);
  cues[0].level = null; // cleared in the editor: the cue goes back to the sound's own level
  assert.deepEqual(JSON.parse(serializeCues(cues, withLevel)).find((c) => c.sound === "rain"), { sound: "rain", at: 2.5 });
  cues[1].level = 0; // 0 is a level (silent), not "not set"
  assert.equal(JSON.parse(serializeCues(cues, withLevel)).find((c) => c.sound === "gull").volume, 0);
});

test("without a level key in the lane, a cue's volume is just something else it carried", () => {
  const plain = { ref: "sound", at: "at" };
  const [cue] = parseCues('[{"sound":"rain","at":2,"volume":0.4}]', plain);
  assert.equal(cue.level, null);
  assert.deepEqual(cue.rest, { volume: 0.4 });
  assert.deepEqual(JSON.parse(serializeCues([cue], plain)), [{ volume: 0.4, sound: "rain", at: 2 }]);
});

test("the lane's level key reaches the editor's spec", () => {
  const view = { definition: { kind: "timeline", spine: { entry_type: "beat" }, lanes: [{ id: "sounds", title: "Sounds", entry_type: "sound", placed: { field: "sounds", ref: "sound", at: "at", volume: "volume" } }] } };
  assert.equal(cueSpecsFor([view], "beat")[0].volume, "volume");
  view.definition.lanes[0].placed.volume = undefined;
  assert.equal("volume" in cueSpecsFor([view], "beat")[0], false);
});

