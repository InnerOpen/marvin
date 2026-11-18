// Cue rows left behind when their line moves to another beat (lib/cueHomes.ts): the Timeline plays them in the beat that holds the line now, as
// the render does from Studio v221, and the beat page says where the line went, moves the row there as whole records, and shows adopted rows.
import assert from "node:assert/strict";
import { test } from "node:test";
import { cuesByHolder, cueWords, homeOf, moveCueRow, patchedAsSent, strayHomes } from "./cueHomes.ts";
import { layout } from "./timeline.ts";

test("cuesByHolder: a cue plays in the beat that holds its line now; one whose line is gone stays with the beat that stores it", () => {
  const beats = [
    { slug: "b1", cues: [{ line: "l1", word: 1 }, { line: "l2", word: 2, note: "kept" }, { line: "lost", word: 0 }] },
    { slug: "b2", cues: JSON.stringify([{ line: "l2", word: 0 }]) },
  ];
  const held = cuesByHolder(beats, new Map([["l1", "b1"], ["l2", "b2"]]));
  assert.deepEqual(
    held.get("b1").map((h) => [h.cue.line, h.stored]),
    [
      ["l1", "b1"],
      ["lost", "b1"],
    ],
  );
  assert.deepEqual(
    held.get("b2").map((h) => [h.cue.line, h.cue.word, h.stored, h.cue.position]),
    [
      ["l2", 2, "b1", 1],
      ["l2", 0, "b2", 0],
    ],
  );
  assert.deepEqual(held.get("b2")[0].cue.rest, { note: "kept" });
});

test("homeOf: here, moved to another beat, gone, or in no beat; nothing is said when the lookup failed", () => {
  const lines = new Map([["l1", "b1"], ["l2", "b2"], ["l3", ""]]);
  assert.deepEqual(homeOf({ line: "l1" }, "b1", lines), { kind: "here" });
  assert.deepEqual(homeOf({ line: "l2" }, "b1", lines), { kind: "moved", beat: "b2" });
  assert.deepEqual(homeOf({ line: "l3" }, "b1", lines), { kind: "unplaced" });
  assert.deepEqual(homeOf({ line: "nope" }, "b1", lines), { kind: "gone" });
  assert.deepEqual(homeOf({ line: "nope" }, "b1", null), { kind: "here" });
});

test("moveCueRow: takes the row out of the source's whole data and adds it to the target's, every other field left as it was", () => {
  const source = { story: "s", number: 1, cues: [{ line: "l1", word: 1 }, { line: "l2", word: 3, sound: "clang", odd: { keep: true } }], sounds: [{ sound: "x", at: 1 }] };
  const target = { story: "s", number: 2, cues: [{ line: "l9", word: 0 }], hold_seconds: 3 };
  const moved = moveCueRow(source, target, "cues", { position: 1, line: "l2", word: 3 });
  assert.deepEqual(moved.source, { story: "s", number: 1, cues: [{ line: "l1", word: 1 }], sounds: [{ sound: "x", at: 1 }] });
  assert.deepEqual(moved.target, { story: "s", number: 2, cues: [{ line: "l9", word: 0 }, { line: "l2", word: 3, sound: "clang", odd: { keep: true } }], hold_seconds: 3 });
  assert.equal(Object.keys(moved.source).length, Object.keys(source).length);
  assert.equal(Object.keys(moved.target).length, Object.keys(target).length);
  assert.deepEqual(source.cues.length, 2); // nothing changed in place
});

test("moveCueRow: finds the row by line and word when its position moved; writes the editor's row; keeps JSON text as text", () => {
  const source = { cues: JSON.stringify([{ line: "l2", word: 3 }, { line: "l1", word: 1 }]) };
  const moved = moveCueRow(source, {}, "cues", { position: 1, line: "l2", word: 3 }, { line: "l2", word: 3, look: { kind: "flash" } });
  assert.equal(typeof moved.source.cues, "string");
  assert.deepEqual(JSON.parse(moved.source.cues), [{ line: "l1", word: 1 }]);
  assert.deepEqual(moved.target, { cues: [{ line: "l2", word: 3, look: { kind: "flash" } }] }); // a beat with no cues yet gets the field
});

test("moveCueRow: null when the row is not there any more or a field is not a list, so nothing is overwritten", () => {
  assert.equal(moveCueRow({ cues: [{ line: "l1", word: 1 }] }, {}, "cues", { line: "l2", word: 3 }), null);
  assert.equal(moveCueRow({ cues: [{ line: "l2", word: 3 }] }, { cues: { not: "a list" } }, "cues", { line: "l2", word: 3 }), null);
  assert.equal(moveCueRow({ cues: "not json" }, {}, "cues", { line: "l2", word: 3 }), null);
});

test("patchedAsSent: a record that came back with fewer fields or another number of rows is reported", () => {
  const sent = { story: "s", number: 2, cues: [{}, {}] };
  assert.equal(patchedAsSent(sent, { story: "s", number: 2, cues: [{}, {}] }, "cues"), null);
  assert.match(patchedAsSent(sent, { story: "s", cues: [{}, {}] }, "cues"), /2 fields instead of 3/);
  assert.match(patchedAsSent(sent, { story: "s", number: 2, cues: [{}] }, "cues"), /1 rows instead of 2/);
  assert.match(patchedAsSent(sent, null, "cues"), /did not come back/);
});

const spec = { field: "cues", order: "number", beatType: "beat", lines: { entryType: "speech-line", in: "beat" } };
const beat = (slug, number, cues, id = `id-${slug}`) => ({ id, slug, title: `Beat ${slug}`, dataJson: { story: "s", number, ...(cues ? { cues } : {}) } });
const ownLines = [{ slug: "l1", title: "The hammer strikes the wheel.", who: "SMITH", chips: ["The", "hammer", "strikes", "the", "wheel."] }];

test("strayHomes: where each stray row's line is now, by the line's beat; and the rows other beats store for this beat's lines", async () => {
  const here = beat("b1", 1001, [{ line: "l1", word: 1 }, { line: "l2", word: 2 }, { line: "gone", word: 0 }, { line: "l4", word: 0 }, { line: "l5", word: 1 }]);
  const storyBeats = [here, beat("b2", 1002, [{ line: "l1", word: 3, sound: "clang", look: { kind: "flash" } }]), beat("b3", 1003)];
  const asked = [];
  const query = async (q) => {
    asked.push(q);
    if (q.entry_type === "speech-line") return [{ id: "x2", slug: "l2", title: "", dataJson: { beat: "b2" } }, { id: "x4", slug: "l4", title: "", dataJson: { beat: "" } }, { id: "x5", slug: "l5", title: "", dataJson: { beat: "b9" } }];
    return [beat("b9", 2001)];
  };
  const out = await strayHomes(spec, here, ownLines, storyBeats, [{ slug: "clang", name: "Clang" }], query);
  assert.deepEqual(out.self, { id: "id-b1", slug: "b1", label: "beat 1001" });
  assert.deepEqual(out.homes, {
    l2: { kind: "moved", id: "id-b2", slug: "b2", label: "beat 1002" },
    gone: { kind: "gone" },
    l4: { kind: "unplaced" },
    l5: { kind: "moved", id: "id-b9", slug: "b9", label: "beat 2001" }, // in another story's beat: found by its slug
  });
  assert.deepEqual(asked[0], { entry_type: "speech-line", entries: ["l2", "gone", "l4", "l5"] });
  assert.deepEqual(asked[1], { entry_type: "beat", entries: ["b9"] });
  assert.deepEqual(out.adopted, [{ from: { id: "id-b2", slug: "b2", label: "beat 1002" }, line: "SMITH: The hammer strikes the wheel.", text: "after “strikes” · Sound Clang · Look: Flash white, 0.9, 0.25 s" }]);
});

test("strayHomes: a failed lookup shows no notices; a beat with no strays asks nothing", async () => {
  const here = beat("b1", 1001, [{ line: "l2", word: 2 }]);
  assert.equal((await strayHomes(spec, here, ownLines, [here], [], async () => null)).homes, undefined);
  let asked = 0;
  const calm = await strayHomes(spec, beat("b1", 1001, [{ line: "l1", word: 2 }]), ownLines, [], [], async () => {
    asked++;
    return [];
  });
  assert.deepEqual([calm.homes, calm.adopted, asked], [{}, [], 0]);
});

test("cueWords: what a cue does in one line", () => {
  assert.equal(cueWords({ line: "l", word: 0, camera: { kind: "whip-pan", x: -1 }, mix: { kind: "dead-air" }, emphasis: true, pic: "b4", rest: {} }), "Camera: Whip pan left, 0.35 · Mix: Dead air 1.5 s · Emphasis · Picture b4");
});

// ── on the Timeline ─────────────────────────────────────────────────────────
const view = {
  kind: "timeline",
  title: "T",
  entry_type: "story",
  spine: { entry_type: "beat", of: "story", order: "number", word_cues: { field: "cues", lane: "lines", sounds: "sounds" } },
  lanes: [
    { id: "lines", title: "Lines", entry_type: "speech-line", of: "story", in: "beat", order: "number", text: "text", audio: "audio", seconds: "duration_seconds", words: "words" },
    { id: "sounds", title: "Sounds", entry_type: "sound", placed: { field: "sounds", ref: "sound", at: "at" }, audio: "audio", seconds: "duration_seconds" },
  ],
};
const take = (words) => ({ role: "audio", publicUrl: "https://cdn/x.mp3", mimeType: "audio/mpeg", ...(words ? { metadataJson: { words } } : {}) });
const words = [
  { text: "The", start: 0, end: 0.3 },
  { text: "hammer", start: 0.4, end: 0.9 },
];
const laidWith = (b1Cues, b2Cues) =>
  layout(view, {
    spine: [
      { id: "id-b1", slug: "b1", title: "b1", dataJson: { story: "s", number: 1, cues: b1Cues } },
      { id: "id-b2", slug: "b2", title: "b2", dataJson: { story: "s", number: 2, cues: b2Cues } },
    ],
    lanes: {
      lines: [
        { id: "l0", slug: "l0", title: "Opening", dataJson: { story: "s", beat: "b1", number: 1, text: "Hello there.", duration_seconds: 1 }, assets: [take()] },
        { id: "l1", slug: "l1", title: "The hammer", dataJson: { story: "s", beat: "b2", number: 1, text: "The hammer", duration_seconds: 1 }, assets: [take(words)] },
      ],
      sounds: [{ id: "clang", slug: "clang", title: "Clang", dataJson: { duration_seconds: 3 }, assets: [take()] }],
    },
  });

test("layout: a cue stored on the beat its line left plays in the beat that holds the line now, marked with where it is stored", () => {
  const laid = laidWith([{ line: "l1", word: 1, sound: "clang", look: { kind: "flash" } }], []);
  const [b1, b2] = laid.items;
  assert.equal(b1.cues, undefined);
  const [mark] = b2.cues;
  assert.deepEqual(mark.stored, { id: "id-b1", slug: "b1", title: "1" });
  assert.deepEqual(mark.look, { kind: "flash" });
  const [sound] = b2.lanes.sounds;
  assert.equal(sound.slot.item, "id-b1"); // a drag writes to the beat that stores the row
  assert.equal(sound.slot.index, 0);
  assert.equal(b1.lanes.sounds.length, 0);
  assert.ok(b2.seconds >= 0.3 + 3, "the sound lengthens the beat it plays in"); // after "The" (0.3 s past the lead), 3 s of clang
});

test("layout: a cue on its own beat's line is not marked; one whose line is gone is left out, as the render leaves it", () => {
  const laid = laidWith([{ line: "gone", word: 1, sound: "clang" }], [{ line: "l1", word: 1 }]);
  assert.equal(laid.items[0].cues, undefined);
  assert.equal(laid.items[1].cues[0].stored, undefined);
});
