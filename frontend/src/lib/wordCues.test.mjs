// Cues on words: the JSON shape the Screenplay Studio render reads (marvin_pull `_cues`, camera.py `cue_of`), and where the Timeline
// draws them (at the end of the word before the cue, as the render plays the sound).
import assert from "node:assert/strict";
import { test } from "node:test";
import { layout, overlays } from "./timeline.ts";
import { wordCueSpecsFor } from "./cueFields.ts";
import { cameraOf, cameraWords, chipsOf, parseWordCues, serializeWordCues } from "./wordCues.ts";

const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} is not ${expected}`);

test("parseWordCues: keeps the well-formed cues and what else they carried", () => {
  const cues = parseWordCues(
    JSON.stringify([
      {
        line: "l1",
        word: 3,
        sound: "clang",
        volume: 0.6,
        camera: { kind: "punch", amount: 1.08 },
        pic: "b04a",
        note: "kept",
      },
      { line: "", word: 1 },
      { word: 2 },
      { line: "l1", word: -1 },
      "nope",
      { line: "l2", word: "2" },
    ]),
  );
  assert.deepEqual(cues, [
    {
      line: "l1",
      word: 3,
      sound: "clang",
      volume: 0.6,
      camera: { kind: "punch", amount: 1.08 },
      pic: "b04a",
      position: 0,
      rest: { note: "kept" },
    },
    { line: "l2", word: 2, position: 5, rest: {} }, // its place in the stored list, malformed entries counted
  ]);
  assert.deepEqual(parseWordCues("not json"), []);
  assert.deepEqual(parseWordCues(null), []);
});

test("serializeWordCues: the render's shape, line and word always and the rest only when set", () => {
  const text = serializeWordCues([
    { line: "l1", word: 3, sound: "clang", volume: 0.6, camera: { kind: "shake", amount: 2 }, rest: { note: "kept" } },
    { line: "l2", word: 0, pic: "b04a", rest: {} },
  ]);
  assert.deepEqual(JSON.parse(text), [
    { note: "kept", line: "l1", word: 3, sound: "clang", volume: 0.6, camera: { kind: "shake", amount: 2 } },
    { line: "l2", word: 0, pic: "b04a" },
  ]);
  assert.deepEqual(
    parseWordCues(text).map((c) => c.line),
    ["l1", "l2"],
  ); // a round trip
});

test("cameraOf: the render's kinds and ranges", () => {
  assert.deepEqual(cameraOf({ kind: "Punch", amount: 3 }), { kind: "punch", amount: 1.5 });
  assert.deepEqual(cameraOf({ kind: "shake", amount: "2" }), { kind: "shake", amount: 2 });
  assert.deepEqual(cameraOf({ kind: "nudge", x: 0.7, y: 1.4 }), { kind: "nudge", x: 0.7, y: 1 });
  assert.deepEqual(cameraOf({ kind: "punch" }), { kind: "punch" });
  assert.deepEqual(cameraOf({ kind: "zoom", amount: 40 }), { kind: "zoom", amount: 40 }); // not a kind the render knows: kept as written
  assert.equal(cameraOf({ amount: 2 }), undefined);
  assert.equal(cameraWords({ kind: "punch" }), "Punch 1.06");
  assert.equal(cameraWords({ kind: "nudge", x: 0.7, y: 0.4 }), "Nudge 0.7, 0.4");
});

test("chipsOf: the take's timed words when it has them, else the text's", () => {
  assert.deepEqual(chipsOf("The hammer strikes", null), ["The", "hammer", "strikes"]);
  assert.deepEqual(chipsOf("ignored", [{ text: "The" }, { text: "hammer" }]), ["The", "hammer"]);
});

const spec = {
  kind: "timeline",
  title: "T",
  entry_type: "story",
  spine: {
    entry_type: "beat",
    of: "story",
    order: "number",
    word_cues: { field: "cues", lane: "lines", sounds: "sounds" },
  },
  lanes: [
    {
      id: "lines",
      title: "Lines",
      entry_type: "speech-line",
      of: "story",
      in: "beat",
      order: "number",
      text: "text",
      audio: "audio",
      seconds: "duration_seconds",
      words: "words",
    },
    {
      id: "sounds",
      title: "Sounds",
      entry_type: "sound",
      placed: { field: "sounds", ref: "sound", at: "at" },
      audio: "audio",
      seconds: "duration_seconds",
    },
  ],
};
const take = (words) => ({
  role: "audio",
  publicUrl: "https://cdn/x.mp3",
  mimeType: "audio/mpeg",
  ...(words ? { metadataJson: { words } } : {}),
});
const words = [
  { text: "The", start: 0, end: 0.3 },
  { text: "hammer", start: 0.4, end: 0.9 },
  { text: "strikes", start: 1.0, end: 1.4 },
  { text: "the", start: 1.5, end: 1.6 },
  { text: "wheel.", start: 1.7, end: 2.2 },
];
const rows = (cues, sounds) => ({
  spine: [
    { id: "b1", slug: "b1", title: "b1", dataJson: { story: "s", number: 1, cues } },
    { id: "b2", slug: "b2", title: "b2", dataJson: { story: "s", number: 2 } },
  ],
  lanes: {
    lines: [
      {
        id: "l1",
        slug: "l1",
        title: "The hammer line",
        dataJson: { story: "s", beat: "b1", number: 1, text: "The hammer strikes the wheel.", duration_seconds: 2.5 },
        assets: [take(words)],
      },
    ],
    sounds,
  },
});
const clang = (seconds, withTake = true) => ({
  id: "clang",
  slug: "clang",
  title: "Clang",
  dataJson: { duration_seconds: seconds },
  ...(withTake ? { assets: [take()] } : {}),
});

test("layout: a cue's sound plays in the sounds lane at the end of the word before it, at its own level", () => {
  const laid = layout(
    spec,
    rows([{ line: "l1", word: 3, sound: "clang", volume: 0.6, camera: { kind: "punch" } }], [clang(0.5)]),
  );
  const [mark] = laid.items[0].cues;
  close(mark.at, 0.3 + 1.4); // "strikes" ends 1.4 s into the line, which starts after the 0.3 s lead
  close(mark.picAt, 0.3 + 1.5);
  assert.equal(mark.text, "strikes");
  assert.equal(mark.estimated, false);
  assert.deepEqual(mark.sound, { slug: "clang", title: "Clang", heard: true });
  assert.deepEqual(mark.camera, { kind: "punch" });
  const [sound] = laid.items[0].lanes.sounds;
  close(sound.start, 1.7);
  close(sound.at, 1.7);
  assert.equal(sound.volume, 0.6);
  assert.deepEqual(sound.cue, { line: "The hammer line", word: 3, text: "strikes" });
  assert.equal(overlays(laid, spec.lanes).length, 1); // Play plays it
});

test("layout: a cue sound that runs past the beat's speech lengthens the beat, as the render's sfx_end does", () => {
  const laid = layout(spec, rows([{ line: "l1", word: 5, sound: "clang" }], [clang(2)]));
  close(laid.items[0].seconds, 0.3 + 2.2 + 2); // "wheel." ends at 2.2 s into the line; the clang runs 2 s after
  const unheard = layout(spec, rows([{ line: "l1", word: 5, sound: "clang" }], [clang(2, false)]));
  close(unheard.items[0].seconds, 0.3 + 2.5 + 0.35); // no take: drawn, but nothing plays and the beat is as before
  assert.equal(unheard.items[0].cues[0].sound.heard, false);
});

test("layout: a cue on a line that is not laid is left out; one with no word timings is placed by its text", () => {
  assert.equal(
    layout(spec, rows([{ line: "elsewhere", word: 1, sound: "clang" }], [clang(0.5)])).items[0].cues,
    undefined,
  );
  const plain = rows([{ line: "l1", word: 3 }], []);
  plain.lanes.lines[0].assets = [];
  const [mark] = layout(spec, plain).items[0].cues;
  assert.equal(mark.estimated, true);
  close(
    mark.at,
    0.3 + (Math.round(("The hammer strikes".length / "The hammer strikes the wheel.".length) * 10000) / 10000) * 2.5,
  );
});

test("wordCueSpecsFor: a view that declares cues on words gives the spine type's page what it needs to edit them", () => {
  const [found] = wordCueSpecsFor(
    [{ definition: { ...spec, spine: { ...spec.spine, starts_during: "starts_during", picture: "still" } } }],
    "beat",
  );
  assert.equal(found.field, "cues");
  assert.deepEqual(found.lines, {
    entryType: "speech-line",
    in: "beat",
    text: "text",
    who: undefined,
    audio: "audio",
    words: "words",
    order: "number",
    off: undefined,
  });
  assert.equal(found.sounds.entryType, "sound");
  assert.equal(found.sounds.field, "sounds");
  assert.deepEqual(
    [found.of, found.order, found.picture, found.startsDuring],
    ["story", "number", "still", "starts_during"],
  );
  assert.deepEqual(wordCueSpecsFor([{ definition: spec }], "story"), []); // not the spine type
  assert.deepEqual(
    wordCueSpecsFor(
      [{ definition: { ...spec, spine: { ...spec.spine, word_cues: { field: "cues", lane: "sounds" } } } }],
      "beat",
    ),
    [],
  ); // not an `in` lane
});
