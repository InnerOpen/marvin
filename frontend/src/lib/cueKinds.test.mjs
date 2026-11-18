// What a cue on a word can do besides its sound and picture (lib/cueKinds.ts): the camera moves, looks and changes to the mix the Screenplay
// Studio render reads, how the editor and the Timeline name them, and that none of them moves anything on the Timeline.
import assert from "node:assert/strict";
import { test } from "node:test";
import { CUE_KINDS, EMPHASIS, MIX_SECONDS, cueChips, effectChip, effectOf, effectWords, emphasisOf, kindOf, refused } from "./cueKinds.ts";
import { cues, layout, mixStretches, overlays } from "./timeline.ts";
import { parseWordCues, serializeWordCues } from "./wordCues.ts";

const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} is not ${expected}`);

test("CUE_KINDS: every kind the render does (Studio v218/v219) is offered, emphasis too", () => {
  const offered = Object.entries(CUE_KINDS).flatMap(([group, kinds]) => kinds.filter((k) => k.enabled).map((k) => `${group}:${k.kind}`));
  assert.deepEqual(offered, [
    "camera:punch",
    "camera:shake",
    "camera:nudge",
    "camera:whip-pan",
    "camera:sway",
    "look:flash",
    "look:burn",
    "look:dip",
    "look:freeze",
    "look:tint",
    "look:blur",
    "look:vignette",
    "look:glitch",
    "mix:dead-air",
    "mix:duck",
  ]);
  assert.equal(EMPHASIS.enabled, true);
  assert.equal(EMPHASIS.scale.default, 1.3);
});

test("CUE_KINDS: the render's defaults (camera.py LOOK_DEFAULTS, MIX_DEFAULTS, WHIP, SWAY), each one of its choices or inside its range", () => {
  const defaults = (group, kind) => Object.fromEntries(kindOf(group, kind).fields.map((f) => [f.key, f.default ?? f.unset]));
  assert.deepEqual(defaults("look", "flash"), { color: "white", amount: 0.9, seconds: 0.25 });
  assert.deepEqual(defaults("look", "burn"), { amount: 0.9, seconds: 0.35 });
  assert.deepEqual(defaults("look", "dip"), { color: "black", seconds: 0.8 });
  assert.deepEqual(defaults("look", "freeze"), { seconds: 0.6 });
  assert.deepEqual(defaults("look", "tint"), { color: "sepia", amount: 1, seconds: "to the end of the shot" });
  assert.deepEqual(defaults("look", "blur"), { amount: 0.6, seconds: 0.8 });
  assert.deepEqual(defaults("look", "vignette"), { amount: 0.7, seconds: 1 });
  assert.deepEqual(defaults("look", "glitch"), { seconds: 0.2 });
  assert.deepEqual(defaults("camera", "whip-pan"), { x: 1, amount: 0.35 });
  assert.deepEqual(defaults("camera", "sway"), { amount: 0.8, seconds: 1.5 });
  assert.deepEqual(defaults("mix", "dead-air"), { seconds: MIX_SECONDS });
  assert.deepEqual(defaults("mix", "duck"), { amount: 0.3, seconds: 1.5 });
  assert.deepEqual(
    kindOf("look", "flash").fields[0].choices.map((c) => c.value),
    ["white", "black", "orange", "red", "gold", "blue"],
  );
  for (const [group, kinds] of Object.entries(CUE_KINDS)) {
    for (const k of kinds) {
      for (const f of k.fields) {
        if (f.default === undefined) assert.ok(f.unset, `${group}:${k.kind}.${f.key} says what empty means`);
        else if (f.choices) assert.ok(f.choices.some((c) => c.value === f.default), `${group}:${k.kind}.${f.key}`);
        else assert.ok(f.default >= f.min && f.default <= f.max, `${group}:${k.kind}.${f.key}`);
      }
    }
  }
  assert.match(kindOf("camera", "whip-pan").help, /1\.7× at its peak/);
});

test("effectOf: numbers are held to the render's ranges, as camera.py holds them, and what else a cue carries stays", () => {
  assert.deepEqual(effectOf("camera", { kind: "Whip-Pan", x: 0.4, amount: "0.9" }), { kind: "whip-pan", x: 1, amount: 0.5 });
  assert.deepEqual(effectOf("camera", { kind: "whip-pan", x: -7, amount: 0 }), { kind: "whip-pan", x: -1, amount: 0.05 });
  assert.deepEqual(effectOf("camera", { kind: "whip-pan", x: 0 }), { kind: "whip-pan", x: 1 }); // the render: x < 0 is left, else right
  assert.deepEqual(effectOf("camera", { kind: "sway", amount: "12", seconds: "45" }), { kind: "sway", amount: 5, seconds: 10 });
  assert.deepEqual(effectOf("look", { kind: "flash", amount: 4, color: "Orange", ease: "out" }), { kind: "flash", amount: 1, color: "orange", ease: "out" });
  assert.deepEqual(effectOf("look", { kind: "tint", amount: "lots", seconds: 40 }), { kind: "tint", seconds: 30 }); // not a number: left to the default
  assert.deepEqual(effectOf("mix", { kind: "duck", amount: -1, seconds: 0 }), { kind: "duck", amount: 0, seconds: 0.05 });
});

test("effectOf: a colour the kind does not take is kept as written, and shown as one the render leaves out", () => {
  const purple = effectOf("look", { kind: "flash", color: "purple" });
  assert.deepEqual(purple, { kind: "flash", color: "purple" });
  assert.equal(refused("look", purple), true);
  assert.equal(refused("look", { kind: "dip", color: "gold" }), true); // a dip takes black or white only
  assert.equal(refused("look", { kind: "flash", color: "gold" }), false);
  assert.match(effectWords("look", purple), /the render leaves it out/);
  assert.deepEqual(
    cueChips({ look: purple }).map((c) => [c.chip, c.unknown]),
    [["flash", true]],
  );
});

test("effectOf: a kind this build does not know is kept exactly as written; something that is not a kind at all is nothing", () => {
  assert.deepEqual(effectOf("look", { kind: "Sparkle", amount: 99, stars: 5 }), { kind: "Sparkle", amount: 99, stars: 5 });
  assert.equal(effectOf("look", "flash"), undefined);
  assert.equal(effectOf("mix", { seconds: 2 }), undefined);
  assert.equal(effectOf("mix", [{ kind: "duck" }]), undefined);
});

test("effectWords and effectChip: how each kind reads, the defaults filled in", () => {
  assert.equal(effectWords("camera", { kind: "punch" }), "Punch 1.06");
  assert.equal(effectChip("camera", { kind: "punch" }), null); // the flag's ✣ says it, as before
  assert.equal(effectWords("camera", { kind: "whip-pan", x: -1 }), "Whip pan left, 0.35");
  assert.equal(effectChip("camera", { kind: "whip-pan" }), "whip pan");
  assert.equal(effectWords("camera", { kind: "sway" }), "Sway 0.8, 1.5 s");
  assert.equal(effectWords("look", { kind: "flash" }), "Flash white, 0.9, 0.25 s");
  assert.equal(effectChip("look", { kind: "flash" }), "flash");
  assert.equal(effectChip("look", { kind: "burn" }), "burn");
  assert.equal(effectWords("look", { kind: "dip", color: "white", seconds: 1 }), "Dip white, 1 s");
  assert.equal(effectWords("look", { kind: "tint" }), "Tint sepia, 1, to the end of the shot");
  assert.equal(effectWords("look", { kind: "freeze" }), "Freeze 0.6 s");
  assert.equal(effectChip("mix", { kind: "dead-air" }), "dead air 1.5 s");
  assert.equal(effectChip("mix", { kind: "dead-air", seconds: 2.25 }), "dead air 2.25 s");
  assert.equal(effectChip("mix", { kind: "duck" }), "duck");
  assert.equal(effectWords("mix", { kind: "duck" }), "Duck 0.3, 1.5 s");
  assert.equal(effectChip("look", { kind: "sparkle" }), "sparkle?");
  assert.match(effectWords("look", { kind: "sparkle" }), /^sparkle \(not a kind the render knows/);
});

test("cueChips: a chip for each new thing a cue does, none pending now, an unknown kind shown by its name, not dropped", () => {
  const chips = cueChips({ camera: { kind: "punch" }, look: { kind: "flash" }, mix: { kind: "dead-air", seconds: 2 }, emphasis: true });
  assert.deepEqual(
    chips.map((c) => [c.group, c.chip, c.pending, c.unknown]),
    [
      ["look", "flash", false, false],
      ["mix", "dead air 2 s", false, false],
      ["emphasis", "emphasis", false, false],
    ],
  );
  assert.equal(chips[1].words, "Mix: Dead air 2 s");
  assert.deepEqual(
    cueChips({ camera: { kind: "whip-pan" }, look: { kind: "glitch" }, mix: { kind: "reverb" } }).map((c) => [c.chip, c.pending, c.unknown]),
    [
      ["whip pan", false, false],
      ["glitch", false, false],
      ["reverb?", false, true],
    ],
  );
  assert.deepEqual(cueChips({ camera: null }), []);
});

test("emphasisOf: true, or an object whose scale is held to 1 to 2", () => {
  assert.equal(emphasisOf(true), true);
  assert.deepEqual(emphasisOf({ scale: "1.4", style: "caps" }), { scale: 1.4, style: "caps" });
  assert.deepEqual(emphasisOf({ scale: 9 }), { scale: 2 });
  assert.equal(emphasisOf(false), undefined);
  assert.equal(emphasisOf(null), undefined);
});

test("parseWordCues / serializeWordCues: a row with every new key, unknown keys and kinds, round trips unchanged", () => {
  const row = {
    line: "l1",
    word: 2,
    camera: { kind: "whip-pan", x: -1, amount: 0.4 },
    look: { kind: "sparkle", stars: 5 },
    mix: { kind: "dead-air", seconds: 2 },
    emphasis: { scale: 1.4, style: "caps" },
    nudge: 0.5,
    note: "kept",
  };
  const [cue] = parseWordCues([row]);
  assert.deepEqual(cue.look, { kind: "sparkle", stars: 5 });
  assert.deepEqual(cue.mix, { kind: "dead-air", seconds: 2 });
  assert.deepEqual(cue.rest, { note: "kept" });
  assert.deepEqual(JSON.parse(serializeWordCues(parseWordCues([row]))), [row]);
});

test("parseWordCues: a look, mix or emphasis that cannot be read is kept with the rest, so a save does not lose it", () => {
  const row = { line: "l1", word: 1, look: "flash", mix: { seconds: 2 }, emphasis: "yes", camera: 7 };
  const [cue] = parseWordCues([row]);
  assert.equal(cue.look, undefined);
  assert.deepEqual(cue.rest, { look: "flash", mix: { seconds: 2 }, emphasis: "yes", camera: 7 });
  assert.deepEqual(JSON.parse(serializeWordCues([cue])), [row]);
  // set in the editor, the new value wins over the one kept
  assert.deepEqual(JSON.parse(serializeWordCues([{ ...cue, look: { kind: "dip" } }]))[0].look, { kind: "dip" });
});

// ── on the Timeline ─────────────────────────────────────────────────────────
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
const words = [
  { text: "The", start: 0, end: 0.3 },
  { text: "hammer", start: 0.4, end: 0.9 },
  { text: "strikes", start: 1.0, end: 1.4 },
  { text: "the", start: 1.5, end: 1.6 },
  { text: "wheel.", start: 1.7, end: 2.2 },
];
const rows = (cueList) => ({
  spine: [
    { id: "b1", slug: "b1", title: "b1", dataJson: { story: "s", number: 1, cues: cueList } },
    { id: "b2", slug: "b2", title: "b2", dataJson: { story: "s", number: 2 } },
  ],
  lanes: {
    lines: [{ id: "l1", slug: "l1", title: "The hammer line", dataJson: { story: "s", beat: "b1", number: 1, text: "The hammer strikes the wheel.", duration_seconds: 2.5 }, assets: [take(words)] }],
    sounds: [{ id: "clang", slug: "clang", title: "Clang", dataJson: { duration_seconds: 0.5 }, assets: [take()] }],
  },
});
const at = 0.3 + 1.4; // "strikes" ends 1.4 s into the line, which starts after the 0.3 s lead

test("layout: a cue's look, mix and emphasis ride on its mark; dead air lasts its seconds from its word plus its nudge", () => {
  const laid = layout(spec, rows([{ line: "l1", word: 3, look: { kind: "flash" }, mix: { kind: "dead-air", seconds: 2 }, emphasis: true, nudge: 0.5 }]));
  const [mark] = laid.items[0].cues;
  close(mark.at, at);
  assert.deepEqual(mark.look, { kind: "flash" });
  assert.equal(mark.emphasis, true);
  const [stretch] = mixStretches(laid.items);
  assert.deepEqual([stretch.item, stretch.kind, stretch.chip, stretch.words], ["b1", "dead-air", "dead air 2 s", "Dead air 2 s"]);
  close(stretch.start, at + 0.5);
  close(stretch.seconds, 2);
});

test("layout: dead air or a duck with no seconds lasts the render's 1.5 s, and a nudge never takes it before its beat starts", () => {
  const laid = layout(spec, rows([{ line: "l1", word: 3, mix: { kind: "duck" }, nudge: -5 }]));
  const [stretch] = mixStretches(laid.items);
  close(stretch.start, laid.items[0].start);
  close(stretch.seconds, 1.5);
});

test("layout: a mix kind the render does not know is kept on the mark but draws no stretch", () => {
  const laid = layout(spec, rows([{ line: "l1", word: 3, mix: { kind: "reverb" } }]));
  assert.deepEqual(laid.items[0].cues[0].mix, { kind: "reverb" });
  assert.deepEqual(mixStretches(laid.items), []);
});

test("layout: looks, mixes and emphasis change nothing about timing: lengths, cuts, the walk and what plays are the same", () => {
  const plain = [{ line: "l1", word: 3, sound: "clang", nudge: 0.4 }, { line: "l1", word: 5 }];
  const dressed = [
    { line: "l1", word: 3, sound: "clang", nudge: 0.4, look: { kind: "tint" }, mix: { kind: "dead-air", seconds: 9 }, emphasis: true },
    { line: "l1", word: 5, look: { kind: "glitch" }, mix: { kind: "duck", seconds: 30 }, camera: { kind: "sway", seconds: 20 } },
  ];
  const [a, b] = [layout(spec, rows(plain)), layout(spec, rows(dressed))];
  const timing = (laid) => laid.items.map((i) => [i.id, i.start, i.seconds, i.onScreen.start, i.onScreen.seconds]);
  assert.deepEqual(timing(b), timing(a));
  assert.deepEqual(cues(b, spec.lanes), cues(a, spec.lanes));
  assert.deepEqual(overlays(b, spec.lanes), overlays(a, spec.lanes));
});
