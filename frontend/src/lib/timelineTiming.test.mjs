// The Timeline's timing against the renderer's (ScreenplayStudio render/storyrender/manifest.py `plan` and `_pictures`, marvin_pull.py
// `timing_of` and `word_place`). The numbers are worked out by hand from those rules, and most are the ones the renderer's own tests check
// (render/tests/test_picture_lead.py, test_dual_dialogue.py, test_word_cues.py).
import assert from "node:assert/strict";
import { test } from "node:test";
import { cues, layout, MIN_PICTURE, overlays, picturesOf, placeLines, quiets, secondsOf, speechWindows, wordAt } from "./timeline.ts";

const close = (actual, expected, what = "") =>
  assert.ok(Math.abs(actual - expected) < 1e-9, `${what} ${actual} is not ${expected}`);
const allClose = (actual, expected, what = "") => {
  assert.equal(actual.length, expected.length, `${what} length`);
  for (const [i, a] of actual.entries()) close(a, expected[i], `${what}[${i}]`);
};

const linesLane = {
  id: "lines",
  title: "Lines",
  entry_type: "speech-line",
  of: "story",
  in: "beat",
  order: "number",
  text: "text",
  audio: "audio",
  seconds: "duration_seconds",
  estimate_from: "text",
  nudge: "nudge",
  simultaneous: "simultaneous",
  words: "words",
};
const spec = {
  kind: "timeline",
  title: "Timeline",
  entry_type: "story",
  spine: {
    entry_type: "beat",
    of: "story",
    order: "number",
    group: { entry_type: "chapter", field: "chapter", order: "number" },
    starts_during: "starts_during",
    seconds: {
      hold: "hold_seconds",
      lead: "lead_seconds",
      gap: "gap_seconds",
      tail: "tail_seconds",
      picture_lead: "picture_lead",
      defaults: { hold: 4, lead: 0.3, gap: 0.25, tail: 0.35 },
      entry: { lead: "line_lead", gap: "line_gap", tail: "line_tail", picture_lead: "picture_lead" },
    },
  },
  lanes: [linesLane],
};

const take = (words) => ({
  role: "audio",
  publicUrl: "https://cdn/take.mp3",
  mimeType: "audio/mpeg",
  ...(words ? { metadataJson: { words } } : {}),
});
const story = (data = {}) => ({ id: "id-s", slug: "s", title: "S", dataJson: data });
const beat = (n, data = {}) => ({
  id: `id-b${n}`,
  slug: `b${n}`,
  title: `b${n}`,
  dataJson: { story: "s", number: n, ...data },
});
let seq = 0;
/** A recorded line of `seconds` in beat `n`. */
const line = (n, seconds, data = {}, words = null) => {
  seq += 1;
  return {
    id: `id-l${seq}`,
    slug: data.slug ?? `l${seq}`,
    title: `l${seq}`,
    dataJson: {
      story: "s",
      beat: `b${n}`,
      number: seq,
      duration_seconds: seconds,
      text: data.text ?? "words",
      ...data,
    },
    assets: [take(words)],
  };
};
const lay = (beats, lines, entry = story(), view = spec) => layout(view, { entry, spine: beats, lanes: { lines } });
const starts = (laid) => laid.items.flatMap((i) => i.lanes.lines.map((p) => p.start));

test("timing: the story's line_lead / line_gap / line_tail are every beat's silences; a beat's own wins", () => {
  const laid = lay(
    [beat(1), beat(2, { lead_seconds: 0.5 })],
    [line(1, 2), line(1, 1), line(2, 1)],
    story({ line_lead: 0.05, line_gap: 0.12, line_tail: 0.1 }),
  );
  close(laid.items[0].seconds, 0.05 + 2 + 0.12 + 1 + 0.1);
  allClose(starts(laid), [0.05, 0.05 + 2 + 0.12, 3.27 + 0.5]);
  close(laid.items[1].seconds, 0.5 + 1 + 0.1);
  close(laid.total, 4.87);
  // 0 is a value; empty or not a number is not set, and the view's defaults apply
  assert.deepEqual(secondsOf(beat(1), spec.spine.seconds, story({ line_lead: 0, line_gap: "", line_tail: "x" })), {
    hold: 4,
    lead: 0,
    gap: 0.25,
    tail: 0.35,
  });
});

test("timing: a view without `seconds.entry` ignores the story's fields, exactly as before", () => {
  const plain = {
    ...spec,
    spine: { ...spec.spine, seconds: { ...spec.spine.seconds, entry: undefined, picture_lead: undefined } },
  };
  const laid = lay(
    [beat(1, { picture_lead: 0.8 }), beat(2, { picture_lead: 0.8 })],
    [line(1, 2), line(2, 1)],
    story({ line_lead: 0.05, picture_lead: 0.8 }),
    plain,
  );
  allClose(starts(laid), [0.3, 2.65 + 0.3]);
  for (const item of laid.items) assert.deepEqual(item.onScreen, { start: item.start, seconds: item.seconds });
});

test("pictures: a picture lead brings a beat's picture that long before its first word; the sound and the film's length stay", () => {
  const laid = lay([beat(1), beat(2, { picture_lead: 0.8 })], [line(1, 2), line(2, 1)]);
  const [a, b] = laid.items;
  close(b.start, 2.65); // the sound did not move
  close(b.lanes.lines[0].start, 2.95);
  close(b.onScreen.start, 2.95 - 0.8);
  close(a.onScreen.seconds, 2.65 - 0.5);
  close(b.onScreen.start + b.onScreen.seconds, laid.total);
  close(laid.total, 2.65 + 1.65);
  // 0 is at the first word, later than the sound starts
  close(lay([beat(1), beat(2, { picture_lead: 0 })], [line(1, 2), line(2, 1)]).items[1].onScreen.start, 2.95);
});

test("pictures: the story's picture lead applies to every beat that sets none; the first picture still starts at 0", () => {
  const laid = lay([beat(1), beat(2)], [line(1, 2), line(2, 1)], story({ picture_lead: 0.8 }));
  close(laid.items[0].onScreen.start, 0);
  close(laid.items[1].onScreen.start, 2.15);
  const own = lay([beat(1), beat(2, { picture_lead: 0.2 })], [line(1, 2), line(2, 1)], story({ picture_lead: 0.8 }));
  close(own.items[1].onScreen.start, 2.75);
});

test("pictures: never before the film starts, never closer than MIN_PICTURE after the one before", () => {
  const laid = lay(
    [beat(1), beat(2, { picture_lead: 3 }), beat(3, { picture_lead: 3 })],
    [line(1, 0.2), line(2, 0.2), line(3, 0.2)],
  );
  allClose(
    laid.items.map((i) => i.onScreen.start),
    [0, MIN_PICTURE, 2 * MIN_PICTURE],
  );
  assert.ok(laid.items.every((i) => i.onScreen.seconds > 0));
});

test("pictures: a silent beat with a lead comes that long before it starts and keeps its hold on screen", () => {
  const laid = lay(
    [beat(1), beat(2, { hold_seconds: 3, picture_lead: 0.8 }), beat(3, { picture_lead: 0.8 })],
    [line(1, 2), line(3, 1)],
  );
  close(laid.items[1].onScreen.start, 2.65 - 0.8);
  close(laid.items[1].onScreen.seconds, 3 + 0.3);
  close(laid.items[2].onScreen.start, 5.65 + 0.3 - 0.8);
});

test("pictures: the chapters, bands and beds follow the pictures", () => {
  const view = { ...spec, spine: { ...spec.spine, bands: [{ entry_type: "scene", field: "scene" }] } };
  const beats = [beat(1, { chapter: "c1", scene: "x" }), beat(2, { chapter: "c2", scene: "y", picture_lead: 0.8 })];
  const laid = layout(view, {
    entry: story(),
    spine: beats,
    groups: [
      { id: "c1", slug: "c1", title: "One", dataJson: { number: 1 } },
      { id: "c2", slug: "c2", title: "Two", dataJson: { number: 2 } },
    ],
    lanes: { lines: [line(1, 2), line(2, 1)] },
  });
  close(laid.groups[1].start, 2.15);
  close(laid.groups[0].seconds, 2.15);
  close(laid.bands.scene[1].start, 2.15);
});

test("nudge: a line starts later or earlier and the lines after it follow where it now ends", () => {
  const laid = lay([beat(1)], [line(1, 2), line(1, 1, { nudge: 0.5 }), line(1, 1, { nudge: -0.1 })]);
  allClose(starts(laid), [0.3, 0.3 + 2 + 0.25 + 0.5, 0.3 + 2 + 0.25 + 0.5 + 1 + 0.25 - 0.1]);
  close(laid.total, 4.2 + 1 + 0.35);
});

test("nudge: one laid over the line before ends the beat when the line ending last does; the quiets go by that", () => {
  const laid = lay([beat(1)], [line(1, 2), line(1, 0.5, { nudge: -2 })]);
  allClose(starts(laid), [0.3, 0.3 + 2 + 0.25 - 2]);
  close(laid.total, 0.3 + 2 + 0.35);
  const q = quiets(laid.items, linesLane);
  assert.deepEqual(
    q.map((x) => x.kind),
    ["lead", "tail"],
  );
  close(q[1].start, 2.3);
  close(q[1].seconds, 0.35);
  // Play walks one line at a time: the one laid over is played over the walk
  assert.deepEqual(cues(laid, [linesLane]).filter((c) => c.piece).length, 1);
  assert.equal(overlays(laid, [linesLane]).length, 1);
  close(overlays(laid, [linesLane])[0].start, 0.55);
});

test("nudge: moves the voice, never the picture (no lead); never before the film starts", () => {
  const laid = lay([beat(1), beat(2)], [line(1, 2), line(2, 1, { nudge: -1 })]);
  close(laid.items[1].lanes.lines[0].start, 2.65 + 0.3 - 1);
  close(laid.items[1].start, 2.65);
  close(laid.items[1].onScreen.start, 2.65); // the picture before is not cut short
  close(laid.items[0].onScreen.seconds, 2.65);
  close(lay([beat(1)], [line(1, 1, { nudge: -5 })]).items[0].lanes.lines[0].start, 0);
  // held to -10..10 as the render reads it
  close(lay([beat(1)], [line(1, 1, { nudge: 40 })]).items[0].lanes.lines[0].start, 10.3);
});

test("nudge: does not move a picture lead either, and the picture before keeps its length", () => {
  const plain = lay([beat(1), beat(2, { picture_lead: 0.8 })], [line(1, 2), line(2, 1)]);
  const nudged = lay([beat(1), beat(2, { picture_lead: 0.8 })], [line(1, 2), line(2, 1, { nudge: -0.35 })]);
  close(nudged.items[1].lanes.lines[0].start, plain.items[1].lanes.lines[0].start - 0.35);
  close(nudged.items[1].onScreen.start, plain.items[1].onScreen.start);
  close(nudged.items[0].onScreen.seconds, plain.items[0].onScreen.seconds);
});

test("dual dialogue: a simultaneous line starts with the line before, and the next follows the later of the two", () => {
  const laid = lay([beat(1)], [line(1, 2), line(1, 3, { simultaneous: true }), line(1, 1)]);
  allClose(starts(laid), [0.3, 0.3, 0.3 + 3 + 0.25]);
  close(laid.total, 3.55 + 1 + 0.35);
  const nudged = lay([beat(1)], [line(1, 2), line(1, 1, { simultaneous: true, nudge: 0.5 })]);
  allClose(starts(nudged), [0.3, 0.8]);
  close(nudged.total, 0.3 + 2 + 0.35);
  close(starts(lay([beat(1)], [line(1, 1, { simultaneous: true })]))[0], 0.3); // nothing to join: at the lead
  allClose(starts(lay([beat(1)], [line(1, 2), line(1, 3, { simultaneous: "yes" })])), [0.3, 2.55]); // only a real true counts, as in the render
});

test("placeLines: unmoved lines report no spoken length, so the item keeps the plain sum", () => {
  const plain = placeLines(
    [
      { seconds: 2, nudge: 0, together: false },
      { seconds: 1, nudge: 0, together: false },
    ],
    { lead: 0.3, gap: 0.25, tail: 0.35 },
    10,
  );
  allClose(plain.starts, [10.3, 12.55]);
  assert.equal(plain.spoken, null);
  close(
    placeLines(
      [
        { seconds: 2, nudge: 0, together: false },
        { seconds: 0.5, nudge: -2, together: false },
      ],
      { lead: 0.3, gap: 0.25, tail: 0.35 },
      10,
    ).spoken,
    2.65,
  );
});

const words = [
  { text: "one", start: 0, end: 0.5 },
  { text: "two", start: 0.6, end: 1.0 },
  { text: "[sighs]", start: 1.0, end: 1.05 },
  { text: "three", start: 1.1, end: 1.4 },
  { text: "four", start: 1.5, end: 2.0 },
];

test("overlay: its picture comes in at the start of its word, the beat before gives way there, and it adds no time", () => {
  const host = line(1, 4, { slug: "host", text: "one two three four" }, words);
  const laid = lay(
    [beat(1), beat(2, { starts_during: { line: "host", word: 3 }, hold_seconds: 0 }), beat(3)],
    [host, line(3, 1)],
  );
  const [a, b, c] = laid.items;
  close(laid.total, 4.65 + 1.65); // as long as without the overlay
  close(b.seconds, 0);
  close(b.overlay.at, 0.3 + 1.5); // "four": the [sighs] tag is not a word
  assert.equal(b.overlay.text, "four");
  assert.equal(b.overlay.estimated, false);
  assert.deepEqual([a.onScreen.start, a.onScreen.seconds], [0, 1.8]);
  close(b.onScreen.start, 1.8);
  close(c.onScreen.start, c.start); // the overlay lasts until the next picture
  close(b.onScreen.seconds, 4.65 - 1.8);
});

test("overlay: a hold keeps it up that long from its word, so only what runs past the beat before adds time", () => {
  const host = line(1, 4, { slug: "host", text: "one two three four" }, words);
  const laid = lay(
    [beat(1), beat(2, { starts_during: { line: "host", word: 3 }, hold_seconds: 5 }), beat(3)],
    [host, line(3, 1)],
  );
  close(laid.items[2].start, 0.3 + 1.5 + 5);
});

test("overlay: with no word timings its place comes from where the word stands in the text", () => {
  const host = line(1, 4, { slug: "host", text: "one two three four" });
  const b = lay([beat(1), beat(2, { starts_during: { line: "host", word: 2 } })], [host]).items[1];
  close(b.overlay.at, 0.3 + 0.4444 * 4); // "three" starts at character 8 of 18
  assert.equal(b.overlay.estimated, true);
  assert.equal(b.overlay.text, "three");
});

test("overlay: one whose line is not laid before it is an ordinary beat", () => {
  const laid = lay(
    [beat(1), beat(2, { starts_during: { line: "elsewhere", word: 1 }, hold_seconds: 4 })],
    [line(1, 1)],
  );
  assert.equal(laid.items[1].overlay, undefined);
  close(laid.items[1].seconds, 4);
});

test("wordAt: a sound at the end of the word before its note, a picture at the start of the word after it, as the render places them", () => {
  const bare = { text: "The hammer strikes the wheel.", seconds: 1, words: null };
  close(wordAt(bare, 3, true).at, Math.round(("The hammer strikes".length / bare.text.length) * 10000) / 10000);
  close(wordAt(bare, 3, false).at, Math.round(("The hammer strikes ".length / bare.text.length) * 10000) / 10000);
  close(wordAt(bare, 0, true).at, 0);
  close(wordAt(bare, 9, false).at, 1); // past the last word: the end
  const timed = { text: "", seconds: 2, words: words.filter((w) => !w.text.startsWith("[")) };
  close(wordAt(timed, 2, true).at, 1.0);
  close(wordAt(timed, 2, false).at, 1.1);
  close(wordAt(timed, 0, true).at, 0);
  close(wordAt(timed, 7, false).at, 2.0);
  assert.equal(wordAt(timed, 1, true).estimated, false);
});

test("picturesOf: nothing moved, the pictures are the sound's windows to the last digit", () => {
  const shots = [
    { start: 0, seconds: 2.65, firstWord: 0.3, lead: null, anchor: null },
    { start: 2.65, seconds: 1.65, firstWord: 2.95, lead: null, anchor: null },
  ];
  assert.deepEqual(picturesOf(shots, 4.3), [
    { start: 0, seconds: 2.65 },
    { start: 2.65, seconds: 1.65 },
  ]);
});

// ── a beat's clip (ScreenplayStudio v223 clip.py, manifest `plan`: `max(hold, speech, sounds, clip) + after`; build: its sound from the picture's start)
const clipSpec = {
  ...spec,
  spine: {
    ...spec.spine,
    picture: "still",
    clip: { field: "clip", lane: "lines", audio: "clip_audio", volume: "clip_volume", start: "clip_start", end: "clip_end", seconds: "clip_seconds", has_audio: "clip_has_audio", poster: "clip_poster", text: "clip_text", corner: "clip_corner", shape: "clip_shape", look: "clip_look" },
  },
};
const video = (seconds, extra = {}) => ({ id: "vid-1", role: "clip", publicUrl: "https://cdn/me.mp4", mimeType: "video/mp4", name: "Recording", ...(seconds ? { metadataJson: { recording: { duration_seconds: seconds } } } : {}), ...extra });
const clipBeat = (n, data = {}, assets = [video(6.4)]) => ({ ...beat(n, { still: `img-${n}`, clip: "vid-1", ...data }), assets });
const layClip = (beats, lines = []) => layout(clipSpec, { entry: story(), spine: beats, lanes: { lines } });

test("clip: a beat with a clip and nothing else lasts as long as the clip the recorder measured, not the default hold", () => {
  const laid = layClip([clipBeat(1), beat(2)]);
  close(laid.items[0].seconds, 6.4, "the clip's length");
  assert.equal(laid.items[0].clip.measured, "recorded");
  assert.equal(laid.items[0].estimated, false);
  close(laid.items[1].start, 6.4, "the next beat starts after it");
  close(laid.items[1].seconds, 4, "a beat with no clip keeps the default hold");
});

test("clip: it counts with the lines and the beat's own hold, whichever is longest", () => {
  const short = layClip([clipBeat(1)], [line(1, 2)]); // 0.3 + 2 + 0.35 = 2.65 < 6.4
  close(short.items[0].seconds, 6.4);
  const long = layClip([clipBeat(1)], [line(1, 8)]); // 0.3 + 8 + 0.35
  close(long.items[0].seconds, 8.65);
  const held = layClip([clipBeat(1, { hold_seconds: 9 })]);
  close(held.items[0].seconds, 9);
});

test("clip: the measured length on the beat wins, trimmed by its start and end; a trim past the file is what the render refuses", () => {
  const trimmed = layClip([clipBeat(1, { clip_seconds: 10, clip_start: 2, clip_end: 5 })]);
  close(trimmed.items[0].clip.seconds, 3);
  assert.equal(trimmed.items[0].clip.measured, "described");
  close(trimmed.items[0].seconds, 3, "only its own hold would hold it longer");
  const fromTwo = layClip([clipBeat(1, { clip_start: 2 })]); // the recorder's 6.4, less 2
  close(fromTwo.items[0].clip.seconds, 4.4);
  const hair = layClip([clipBeat(1, { clip_seconds: 6, clip_end: 6.04 })]); // a hair past its end is its end
  close(hair.items[0].clip.seconds, 6);
  assert.equal(hair.items[0].clip.problem, null);
  const past = layClip([clipBeat(1, { clip_seconds: 6, clip_end: 7 })]);
  assert.match(past.items[0].clip.problem, /past the end/);
  const backwards = layClip([clipBeat(1, { clip_start: 3, clip_end: 2 })]);
  assert.match(backwards.items[0].clip.problem, /must come after/);
});

test("clip: with no length known it is a marked guess, unless its trim gives its length", () => {
  const guessed = layClip([clipBeat(1, {}, [video(null)])]);
  close(guessed.items[0].clip.seconds, 4);
  assert.equal(guessed.items[0].clip.measured, "estimated");
  assert.equal(guessed.items[0].estimated, true);
  assert.equal(guessed.items[0].clip.sound.estimated, true);
  const ends = layClip([clipBeat(1, { clip_start: 1, clip_end: 3.5 }, [video(null)])]);
  close(ends.items[0].clip.seconds, 2.5);
  assert.equal(ends.items[0].clip.measured, "trimmed");
});

test("clip: it plays from where its picture comes in, cut with its picture, its sound running to its end", () => {
  // beat 2's picture comes in 1 s before its first word, over the end of beat 1 (2.65 s): at 2.65 + 0.3 - 1 = 1.95
  const laid = layClip([beat(1), clipBeat(2, { picture_lead: 1 })], [line(1, 2), line(2, 1)]);
  const [one, two] = laid.items;
  close(one.seconds, 2.65);
  close(two.seconds, 6.4, "its length counts from its sound");
  close(two.onScreen.start, 1.95);
  close(two.clip.start, 1.95, "the clip");
  close(two.clip.sound.start, 1.95, "its sound");
  close(two.clip.sound.seconds, 6.4);
  close(two.onScreen.seconds, 7.1);
  close(two.clip.shown, 6.4, "shown in full: its picture is up longer");
  // the next picture brought 2 s before its first word (6.4 + 0.3 - 2 = 4.7) cuts the clip's picture; its sound plays on
  const cut = layClip([clipBeat(1), beat(2, { picture_lead: 2 })], [line(2, 1)]);
  close(cut.items[0].onScreen.seconds, 4.7);
  close(cut.items[0].clip.shown, 4.7);
  close(cut.items[0].clip.sound.seconds, 6.4);
});

test("clip: its sound is heard unless it is off, at 0 or the file has none; Play plays it from its trim and the music ducks under it", () => {
  const heard = layClip([clipBeat(1, { clip_start: 1.5, clip_volume: 0.6 })]);
  const sound = heard.items[0].clip.sound;
  assert.equal(sound.audio, "https://cdn/me.mp4");
  close(sound.volume, 0.6);
  const [o] = overlays(heard, clipSpec.lanes);
  assert.deepEqual([o.lane, o.start, o.audio, o.origin], ["lines", 0, "https://cdn/me.mp4", -1.5]);
  close(o.seconds, 4.9);
  assert.deepEqual(speechWindows(heard, clipSpec.lanes), [[0, 4.9]]);
  for (const off of [{ clip_audio: false }, { clip_audio: "no" }, { clip_volume: 0 }, { clip_has_audio: false }]) {
    const laid = layClip([clipBeat(1, off)]);
    assert.equal(laid.items[0].clip.sound, null, JSON.stringify(off));
    close(laid.items[0].seconds, 6.4, "its picture still plays");
  }
});

test("clip: the poster, the text, the corner and the shape are read from the beat; an unknown corner is the render's default", () => {
  const poster = { id: "img-p", role: "clip_poster", publicUrl: "https://cdn/p.jpg", mimeType: "image/jpeg" };
  const laid = layClip([clipBeat(1, { clip_poster: "img-p", clip_text: "Hi there", clip_corner: "TOP-left", clip_shape: "square" }, [video(6.4), poster]), clipBeat(2, { clip_corner: "middle" })]);
  const [a, b] = laid.items.map((i) => i.clip);
  assert.deepEqual([a.poster, a.text, a.corner, a.shape], ["https://cdn/p.jpg", "Hi there", "top-left", "square"]);
  assert.deepEqual([b.poster, b.corner, b.shape], [null, "bottom-right", "circle"]);
});

test("clip: a spec with no clip key lays a beat that names one as before", () => {
  const laid = lay([clipBeat(1)]);
  close(laid.items[0].seconds, 4);
  assert.equal(laid.items[0].clip, undefined);
});
