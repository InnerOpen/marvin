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
  assert.deepEqual(parseCues([{ sound: "a", at: -2 }], spec), [{ ref: "a", at: 0, rest: {} }]);
  assert.deepEqual(parseCues("not json", spec), []);
  assert.deepEqual(parseCues({ sound: "a" }, spec), []);
  assert.equal(serializeCues([], spec), "[]");
});
