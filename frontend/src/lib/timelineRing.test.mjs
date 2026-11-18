// A sound that rings over the next beats (`ring: true` on a beat's `sounds` row or on a cue on a word), as the render plays it from Studio v224:
// it plays in full from where it is placed and is left out of its beat's length (max(hold, spoken, end of its longest sound) + after).
import assert from "node:assert/strict";
import { test } from "node:test";
import { parseCues, RING, serializeCues } from "./cueFields.ts";
import { cueWords, moveCueRow } from "./cueHomes.ts";
import { layout, overlays, quiets, ringSpan, stackRows, withListEntry } from "./timeline.ts";
import { parseWordCues, serializeWordCues } from "./wordCues.ts";

const close = (actual, expected, what = "") => assert.ok(Math.abs(actual - expected) < 1e-9, `${what} ${actual} is not ${expected}`);

const spec = {
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
const sound = (slug, seconds) => ({ id: slug, slug, title: slug, dataJson: { duration_seconds: seconds }, assets: [take()] });
const beat = (slug, number, data = {}) => ({ id: `id-${slug}`, slug, title: slug, dataJson: { story: "s", number, ...data } });
const library = [sound("rumble", 9), sound("click", 1)];
// Two beats with nothing timed hold 4 s each (the view's default hold); b1 places what it is given.
const laidWith = (b1Sounds, b2Sounds) => layout(spec, { spine: [beat("b1", 1, { sounds: b1Sounds }), beat("b2", 2, b2Sounds ? { sounds: b2Sounds } : {})], lanes: { lines: [], sounds: library } });

test("ring: a placed sound that rings plays in full over the next beat and does not make its own beat longer", () => {
  const rung = laidWith([{ sound: "rumble", at: 2, ring: true }]);
  assert.deepEqual(rung.items.map((i) => [i.start, i.seconds]), [[0, 4], [4, 4]]);
  assert.equal(rung.total, 8);
  const [piece] = rung.items[0].lanes.sounds;
  assert.deepEqual([piece.start, piece.seconds, piece.ringsFrom], [2, 9, 4], "drawn at its real length, from where it is placed; its beat ends at 4");
  const plain = laidWith([{ sound: "rumble", at: 2 }]);
  assert.deepEqual(plain.items.map((i) => [i.start, i.seconds]), [[0, 11], [11, 4]], "without ring it stretches its beat to its end, as before");
  assert.equal(plain.items[0].lanes.sounds[0].ringsFrom, undefined);
  assert.equal(laidWith([{ sound: "rumble", at: 2, ring: false }]).items[0].seconds, 11, "ring: false is off");
  assert.equal(laidWith([{ sound: "rumble", at: 2, ring: "true" }]).items[0].seconds, 11, "only true rings, as the render reads it");
});

test("ring: a sound that does not ring still lengthens the beat, whatever rings beside it", () => {
  const laid = laidWith([{ sound: "rumble", at: 2, ring: true }, { sound: "click", at: 4.5 }]);
  assert.equal(laid.items[0].seconds, 5.5, "the click ends at 5.5; the rumble's 11 is left out");
  assert.deepEqual(laid.items[0].lanes.sounds.map((p) => p.ringsFrom), [5.5, undefined], "the ring sound crosses the beat where it really ends");
});

test("ring: a cue's sound that rings plays from its word in full and leaves its beat as long as its line", () => {
  const words = [{ text: "The", start: 0, end: 0.3 }, { text: "hammer", start: 0.4, end: 0.9 }];
  const laidCue = (cue) =>
    layout(spec, {
      spine: [beat("b1", 1, { cues: [cue] }), beat("b2", 2)],
      lanes: { lines: [{ id: "l1", slug: "l1", title: "The hammer", dataJson: { story: "s", beat: "b1", number: 1, text: "The hammer", duration_seconds: 1 }, assets: [take(words)] }], sounds: library },
    });
  const rung = laidCue({ line: "l1", word: 1, sound: "rumble", ring: true });
  const [b1] = rung.items;
  close(b1.seconds, 0.3 + 1 + 0.35, "lead + line + tail");
  const [piece] = b1.lanes.sounds;
  close(piece.start, 0.6, "after “The”");
  assert.equal(piece.seconds, 9);
  close(piece.ringsFrom, 1.65);
  close(laidCue({ line: "l1", word: 1, sound: "rumble" }).items[0].seconds, 0.6 + 9, "without ring the rumble stretches the beat");
});

test("ring: the lines lane's tail is the beat's own, not stretched to the sound's end", () => {
  const withLine = (ring) =>
    layout(spec, {
      spine: [beat("b1", 1, { sounds: [{ sound: "rumble", at: 0, ...(ring ? { ring } : {}) }] }), beat("b2", 2)],
      lanes: { lines: [{ id: "l1", slug: "l1", title: "Hi", dataJson: { story: "s", beat: "b1", number: 1, text: "Hi", duration_seconds: 1 }, assets: [take()] }], sounds: library },
    });
  const tail = (laid) => quiets(laid.items, spec.lanes[0]).find((q) => q.kind === "tail" && q.id.startsWith("id-b1"));
  close(tail(withLine(true)).seconds, 0.35, "rung: the usual tail");
  close(tail(withLine(false)).seconds, 9 - 1.3, "not rung: the tail runs to the end of the rumble");
});

test("ring: the player plays it in full from where it is placed, past its beat", () => {
  const laid = laidWith([{ sound: "rumble", at: 2, ring: true }]);
  const played = overlays(laid, spec.lanes).find((o) => o.id === "rumble");
  assert.deepEqual([played.start, played.seconds], [2, 9]);
});

test("ring: it overlaps the next beat's own sound on another row of the lane, not on top of it", () => {
  const laid = laidWith([{ sound: "rumble", at: 2, ring: true }], [{ sound: "click", at: 0 }]);
  const pieces = laid.items.flatMap((i) => i.lanes.sounds);
  assert.deepEqual(pieces.map((p) => [p.slug, p.start]), [["rumble", 2], ["click", 4]]);
  const rows = stackRows(pieces);
  assert.notEqual(rows[0], rows[1]);
});

test("ringSpan: the bar runs past its beat's end, with a mark there, and is cut only where the track ends", () => {
  assert.deepEqual(ringSpan({ start: 2, seconds: 9, ringsFrom: 4 }, 20), { drawn: 9, beyond: 7, mark: 2 });
  assert.deepEqual(ringSpan({ start: 2, seconds: 9, ringsFrom: 4 }, 8), { drawn: 6, beyond: 7, mark: 2 }, "the film (or its chapter) ends at 8");
  assert.equal(ringSpan({ start: 2, seconds: 1, ringsFrom: 4 }, 20), null, "it ends inside its beat: nothing rings over");
  assert.equal(ringSpan({ start: 2, seconds: 9 }, 20), null, "not a ring sound");
  assert.equal(ringSpan({ start: 2, seconds: 0, ringsFrom: 4 }, 20), null, "no length");
});

test("ring: a cue on a word round-trips `ring: true`, and leaves it out when off", () => {
  const [on, off, odd] = parseWordCues([{ line: "l1", word: 1, sound: "clang", ring: true }, { line: "l1", word: 2, sound: "clang", ring: false }, { line: "l1", word: 3, ring: "yes" }]);
  assert.equal(on.ring, true);
  assert.equal("ring" in off, false);
  assert.equal("ring" in odd || "ring" in odd.rest, false, "anything but true is off");
  assert.deepEqual(JSON.parse(serializeWordCues([on, off])), [{ line: "l1", word: 1, sound: "clang", ring: true }, { line: "l1", word: 2, sound: "clang" }]);
  delete on.ring;
  assert.equal("ring" in JSON.parse(serializeWordCues([on]))[0], false);
});

test("ring: a placed sound's row round-trips `ring: true`, and leaves it out when off", () => {
  const keys = { ref: "sound", at: "at" };
  const cues = parseCues([{ sound: "rumble", at: 2, ring: true, note: "x" }, { sound: "click", at: 1, ring: false }, { sound: "bell", at: 3 }], keys);
  assert.deepEqual(cues.map((c) => [c.ref, c.ring, c.rest]), [["rumble", true, { note: "x" }], ["click", false, {}], ["bell", false, {}]]);
  assert.deepEqual(JSON.parse(serializeCues(cues, keys)), [{ sound: "click", at: 1 }, { note: "x", sound: "rumble", at: 2, ring: true }, { sound: "bell", at: 3 }]);
  assert.equal(RING, "ring");
});

test("ring: a drag, a cleared nudge and a move to another beat keep the flag", () => {
  const data = { sounds: [{ sound: "rumble", at: 2, ring: true }], cues: [{ line: "l1", word: 1, sound: "clang", nudge: 0.5, ring: true }] };
  assert.deepEqual(withListEntry(data, "sounds", 0, "sound", "rumble", "at", 3.5).sounds[0], { sound: "rumble", at: 3.5, ring: true });
  assert.deepEqual(withListEntry(data, "cues", 0, "line", "l1", "nudge", 1).cues[0], { line: "l1", word: 1, sound: "clang", nudge: 1, ring: true });
  assert.deepEqual(withListEntry(data, "cues", 0, "line", "l1", "nudge", undefined).cues[0], { line: "l1", word: 1, sound: "clang", ring: true });
  // Move to beat: the page writes the row as its editor holds it (serializeWordCues of the one cue).
  const row = JSON.parse(serializeWordCues(parseWordCues(data.cues)))[0];
  const moved = moveCueRow({ cues: data.cues }, { cues: [] }, "cues", { position: 0, line: "l1", word: 1 }, row);
  assert.equal(moved.target.cues[0].ring, true);
  assert.deepEqual(moved.source.cues, []);
});

test("ring: a cue's words say its sound rings over", () => {
  assert.equal(cueWords(parseWordCues([{ line: "l1", word: 1, sound: "clang", ring: true }])[0]), "Sound clang (rings over the next beats)");
  assert.equal(cueWords(parseWordCues([{ line: "l1", word: 1, sound: "clang" }])[0]), "Sound clang");
});
