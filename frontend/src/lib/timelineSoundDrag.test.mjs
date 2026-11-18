// Moving a sound on the Timeline: a beat's placed sound gets a new `at`; a sound a cue on a word plays gets a `nudge` on its cue (seconds after,
// or before, its word). Positions are worked out by hand from layout() (lead 0.3).
import assert from "node:assert/strict";
import { test } from "node:test";
import { atAfterDrag, layout, nudgeAfterDrag, nudgeGhosts, pieceKey, stackRows, withListEntry } from "./timeline.ts";
import { parseWordCues, serializeWordCues } from "./wordCues.ts";

const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} is not ${expected}`);

test("atAfterDrag: the new offset snapped to 0.05 s (thousandths with shift), before its beat as far back as the film's start", () => {
  assert.equal(atAfterDrag(1.5, -0.27), 1.25);
  assert.equal(atAfterDrag(1.5, 0.4321, true), 1.932);
  assert.equal(atAfterDrag(0.2, -0.71, false, -12), -0.5); // over the beat before: 0.5 s before this one starts
  assert.equal(atAfterDrag(0.2, -0.7321, true, -12), -0.532);
  assert.equal(atAfterDrag(0.2, -30, false, -12), -12); // never before the film starts (this beat starts 12 s in)
  assert.equal(atAfterDrag(0.2, -3), 0); // the first beat, or no earliest given: 0
  assert.equal(atAfterDrag(0.2, -3, false, 0), 0);
});

test("layout: a placed sound with a negative at starts before its beat, over the one before; in the first beat it starts at 0", () => {
  const view = {
    kind: "timeline",
    title: "T",
    entry_type: "story",
    spine: { entry_type: "beat", of: "story", order: "number", seconds: { hold: "hold_seconds" } },
    lanes: [{ id: "sounds", title: "Sounds", entry_type: "sound", placed: { field: "sounds", ref: "sound", at: "at" }, audio: "audio", seconds: "duration_seconds" }],
  };
  const bolt = { id: "bolt", slug: "bolt", title: "Lightning", dataJson: { duration_seconds: 1 }, assets: [{ role: "audio", publicUrl: "https://cdn/b.mp3", mimeType: "audio/mpeg" }] };
  const laid = (first, second) =>
    layout(view, {
      spine: [
        { id: "b1", slug: "b1", title: "b1", dataJson: { story: "s", number: 1, hold_seconds: 4, sounds: first } },
        { id: "b2", slug: "b2", title: "b2", dataJson: { story: "s", number: 2, hold_seconds: 4, sounds: second } },
      ],
      lanes: { sounds: [bolt] },
    });
  const plain = laid([], [{ sound: "bolt", at: 1 }]);
  const early = laid([], [{ sound: "bolt", at: -0.5 }]);
  const [sound] = early.items[1].lanes.sounds;
  close(sound.start, plain.items[1].start - 0.5);
  assert.equal(sound.at, -0.5);
  assert.deepEqual(early.items.map((i) => [i.start, i.seconds]), plain.items.map((i) => [i.start, i.seconds])); // it lengthens nothing
  const far = laid([], [{ sound: "bolt", at: -40 }]).items[1].lanes.sounds[0];
  close(far.start, 0); // never before the film starts
  const first = laid([{ sound: "bolt", at: -2 }], []).items[0].lanes.sounds[0];
  close(first.start, 0);
  assert.equal(first.at, 0);
});

test("withListEntry: one key of one entry changes, everything else is sent back as it was", () => {
  const data = {
    story: "s",
    sounds: [
      { sound: "rain", at: 0 },
      { sound: "clang", at: 1.5, volume: 0.6 },
    ],
    hold_seconds: 3,
  };
  assert.deepEqual(withListEntry(data, "sounds", 1, "sound", "clang", "at", 1.25), {
    story: "s",
    sounds: [
      { sound: "rain", at: 0 },
      { sound: "clang", at: 1.25, volume: 0.6 },
    ],
    hold_seconds: 3,
  });
  assert.deepEqual(data.sounds[1].at, 1.5); // the record handed in is left alone
  const cues = { cues: [{ line: "l1", word: 3, sound: "clang", nudge: 0.3 }] };
  assert.deepEqual(withListEntry(cues, "cues", 0, "line", "l1", "nudge", undefined), {
    cues: [{ line: "l1", word: 3, sound: "clang" }],
  }); // ↺ removes the key
  assert.deepEqual(withListEntry({ cues: JSON.stringify(cues.cues) }, "cues", 0, "line", "l1", "nudge", -0.2), {
    cues: [{ line: "l1", word: 3, sound: "clang", nudge: -0.2 }],
  }); // a list kept as text
});

test("withListEntry: nothing is written when the entry is no longer the one the page drew", () => {
  const data = { sounds: [{ sound: "rain", at: 0 }] };
  assert.equal(withListEntry(data, "sounds", 0, "sound", "clang", "at", 1), null);
  assert.equal(withListEntry(data, "sounds", 3, "sound", "rain", "at", 1), null);
  assert.equal(withListEntry({}, "sounds", 0, "sound", "rain", "at", 1), null);
});

test("wordCues: a cue's nudge is read, kept and written back; 0 leaves the key out", () => {
  const [a, b] = parseWordCues([
    { line: "l1", word: 3, sound: "s", nudge: 0.35 },
    { line: "l1", word: 4, nudge: 0 },
  ]);
  assert.equal(a.nudge, 0.35);
  assert.equal(b.nudge, undefined);
  assert.deepEqual(JSON.parse(serializeWordCues([a, b])), [
    { line: "l1", word: 3, sound: "s", nudge: 0.35 },
    { line: "l1", word: 4 },
  ]);
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
      seconds: "duration_seconds",
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
const take = { role: "audio", publicUrl: "https://cdn/x.mp3", mimeType: "audio/mpeg" };
const laid = (beat) =>
  layout(spec, {
    spine: [{ id: "b1", slug: "b1", title: "b1", dataJson: { story: "s", number: 1, ...beat } }],
    lanes: {
      lines: [
        {
          id: "l1",
          slug: "l1",
          title: "l1",
          dataJson: { story: "s", beat: "b1", number: 1, text: "one two three four", duration_seconds: 4 },
        },
      ],
      sounds: [{ id: "clang", slug: "clang", title: "Clang", dataJson: { duration_seconds: 0.5 }, assets: [take] }],
    },
  });

test("a beat's placed sounds know their place in its list, so the same sound placed twice moves apart", () => {
  const [a, b] = laid({ sounds: [{ sound: "clang", at: 0.5 }, "junk", { sound: "clang", at: 2 }] }).items[0].lanes
    .sounds;
  assert.deepEqual(a.slot, { item: "b1", field: "sounds", index: 0, ref: "clang" });
  assert.deepEqual(b.slot, { item: "b1", field: "sounds", index: 2, ref: "clang" });
  assert.notEqual(pieceKey(a), pieceKey(b));
});

test("a cue sound plays at its word plus its nudge; the ghost marks the word", () => {
  // "two" ends at character 7 of 18 -> share 0.3889 of the 4 s line, which starts at 0.3: 1.8556; nudged +0.4
  const item = laid({ cues: [{ line: "l1", word: 2, sound: "clang", nudge: 0.4 }] }).items[0];
  const [sound] = item.lanes.sounds;
  const word = 0.3 + 0.3889 * 4;
  close(sound.natural, word);
  close(sound.start, word + 0.4);
  assert.equal(sound.nudge, 0.4);
  assert.deepEqual(sound.slot, { item: "b1", field: "cues", index: 0, ref: "l1" });
  assert.equal(item.cues[0].nudge, 0.4);
  const [ghost] = nudgeGhosts(item.lanes.sounds, stackRows(item.lanes.sounds));
  close(ghost.start, word);
  close(ghost.to, word + 0.4);
  // dragging it back over its word clears the nudge
  assert.equal(nudgeAfterDrag(sound.natural, sound.start - 0.41), 0);
});

test("a cue sound nudged before its beat's sound starts plays at the beat's start, as the render places it", () => {
  const [sound] = laid({ cues: [{ line: "l1", word: 0, sound: "clang", nudge: -1 }] }).items[0].lanes.sounds;
  close(sound.start, 0);
});

// ── a cue's sound nudged before its own beat (Studio manifest.plan: max(word + nudge, 0)) ──────────────────
const cueView = {
  kind: "timeline",
  title: "T",
  entry_type: "story",
  spine: { entry_type: "beat", of: "story", order: "number", word_cues: { field: "cues", lane: "lines", sounds: "sounds" } },
  lanes: [
    { id: "lines", title: "Lines", entry_type: "speech-line", of: "story", in: "beat", order: "number", text: "text", audio: "audio", seconds: "duration_seconds" },
    { id: "sounds", title: "Sounds", entry_type: "sound", placed: { field: "sounds", ref: "sound", at: "at" }, audio: "audio", seconds: "duration_seconds" },
  ],
};
const audio = { role: "audio", publicUrl: "https://cdn/x.mp3", mimeType: "audio/mpeg" };
const cueLaid = (nudge) =>
  layout(cueView, {
    spine: [
      { id: "b13", slug: "b13", title: "b13", dataJson: { story: "s", number: 13 } },
      { id: "b14", slug: "b14", title: "b14", dataJson: { story: "s", number: 14, cues: [{ line: "l14", word: 0, sound: "strike", ...(nudge ? { nudge } : {}) }] } },
    ],
    lanes: {
      lines: [
        { id: "l13", slug: "l13", title: "Before", dataJson: { story: "s", beat: "b13", number: 1, text: "It was dark.", duration_seconds: 2 }, assets: [audio] },
        { id: "l14", slug: "l14", title: "Strike", dataJson: { story: "s", beat: "b14", number: 1, text: "Then the sky split.", duration_seconds: 2 }, assets: [audio] },
      ],
      sounds: [{ id: "strike", slug: "strike", title: "Lightning", dataJson: { duration_seconds: 1 }, assets: [audio] }],
    },
  });

test("layout: a cue's sound nudged before its beat starts is laid there, over the beat before, and never before the film starts", () => {
  const plain = cueLaid(0);
  const b14 = plain.items[1];
  const word = b14.cues[0].at; // the line's start: word 0
  close(word, b14.start + 0.3);
  const early = cueLaid(-0.85).items[1]; // 0.55 s before the beat starts
  const [sound] = early.lanes.sounds;
  close(sound.start, b14.start - 0.55);
  close(sound.at, -0.55);
  close(sound.natural, word);
  assert.equal(sound.nudge, -0.85);
  assert.deepEqual(
    cueLaid(-0.85).items.map((i) => [i.start, i.seconds]),
    plain.items.map((i) => [i.start, i.seconds]),
  ); // reaching back lengthens nothing
  close(cueLaid(-10).items[1].lanes.sounds[0].start, 0); // never before the film starts
});

test("dragging a cue's sound further left before its beat: a more negative nudge, laid earlier, held at the film start", () => {
  const [sound] = cueLaid(-0.85).items[1].lanes.sounds;
  const nudge = nudgeAfterDrag(sound.natural, sound.start - 0.5);
  assert.equal(nudge, -1.35);
  const [moved] = cueLaid(nudge).items[1].lanes.sounds;
  close(moved.start, sound.start - 0.5);
  close(nudgeAfterDrag(sound.natural, sound.start - 100, true), -sound.natural); // the film's start, not the beat's
});
