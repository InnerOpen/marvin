import assert from "node:assert/strict";
import { test } from "node:test";
import { cues, estimateSeconds, quiets, stackRows, itemSeconds, layout, minInnerWidth, overlays, percent, pieceSeconds, tickLevels, progress, progressLine, scale, secondsOf, ticks, widthOf } from "./timeline.ts";

const spec = {
  kind: "timeline",
  title: "Timeline",
  entry_type: "story",
  spine: {
    entry_type: "beat",
    of: "story",
    order: "number",
    group: { entry_type: "chapter", field: "chapter", order: "number" },
    picture: "still",
    text: "picture",
    status: "status",
    seconds: { hold: "hold_seconds", lead: "lead_seconds", gap: "gap_seconds", tail: "tail_seconds", defaults: { hold: 4, lead: 0.3, gap: 0.25, tail: 0.35 } },
  },
  lanes: [
    { id: "lines", title: "Lines", entry_type: "speech-line", of: "story", in: "beat", order: "number", text: "text", who: "speaker", audio: "audio", seconds: "duration_seconds", estimate_from: "text", status: "status" },
    { id: "sounds", title: "Sounds", entry_type: "sound", placed: { field: "sounds", ref: "sound", at: "at" }, audio: "audio", seconds: "duration_seconds", volume: "volume" },
  ],
};

const row = (slug, data, extra = {}) => ({ id: `id-${slug}`, slug, title: slug, dataJson: data, ...extra });
const still = { role: "still", publicUrl: "https://cdn/still.png", mimeType: "image/png" };
const take = { role: "audio", publicUrl: "https://cdn/take.mp3", mimeType: "audio/mpeg" };

const beats = [
  row("b2", { story: "s", number: 2, chapter: "c1", picture: "A door." }),
  row("b1", { story: "s", number: 1, chapter: "c1", picture: "A street.", sounds: [{ sound: "rain", at: 1.5 }, { sound: "nope", at: 0 }] }, { assets: [still] }),
  row("b3", { story: "s", number: 3, chapter: "c2", hold_seconds: 6 }),
  row("b4", { story: "s", number: 4, chapter: "c-missing" }),
];
const chapters = [row("c2", { number: 2 }), row("c1", { number: 1 })];
const lines = [
  row("l2", { beat: "b1", number: 2, text: "one two three", speaker: "Ann" }),
  row("l1", { beat: "b1", number: 1, text: "ignored because recorded", speaker: "Bob", duration_seconds: 2 }, { assets: [take] }),
  row("l3", { beat: "b2", number: 1, text: "", speaker: "Ann" }),
];
const sounds = [row("rain", { duration_seconds: 3 })];

test("estimate: 150 words a minute, never under a second", () => {
  assert.equal(estimateSeconds("one two three"), 1.2);
  assert.equal(estimateSeconds("hi"), 1);
  assert.equal(estimateSeconds(Array(150).fill("w").join(" ")), 60);
});

test("item seconds follow the renderer: lead + pieces + gaps + tail, or hold when nothing is timed", () => {
  const plain = row("b", {});
  assert.equal(itemSeconds(plain, [{ seconds: 2 }, { seconds: 3 }], spec.spine.seconds).toFixed(2), "5.90");
  assert.equal(itemSeconds(plain, [{ seconds: 2 }], spec.spine.seconds).toFixed(2), "2.65");
  assert.equal(itemSeconds(plain, [], spec.spine.seconds), 4);
  assert.equal(itemSeconds(row("b", { hold_seconds: 6 }), [], spec.spine.seconds), 6);
  assert.equal(itemSeconds(row("b", { lead_seconds: 1, tail_seconds: 1, gap_seconds: 0 }), [{ seconds: 1 }, { seconds: 1 }], spec.spine.seconds), 4);
});

test("seconds fields fall back to the view's defaults, and a bad value is ignored", () => {
  assert.deepEqual(secondsOf(row("b", { hold_seconds: "7", lead_seconds: -1 }), spec.spine.seconds), { hold: 7, lead: 0.3, gap: 0.25, tail: 0.35 });
  assert.deepEqual(secondsOf(row("b", {}), undefined), { hold: 4, lead: 0.3, gap: 0.25, tail: 0.35 });
});

test("a piece is timed by its recording, else estimated from its text, else untimed", () => {
  assert.deepEqual(pieceSeconds(lines[1], spec.lanes[0]), { seconds: 2, estimated: false });
  assert.deepEqual(pieceSeconds(lines[0], spec.lanes[0]), { seconds: 1.2, estimated: true });
  assert.equal(pieceSeconds(lines[2], spec.lanes[0]), null);
  assert.equal(pieceSeconds(row("x", {}), spec.lanes[1]), null);
});

test("layout orders beats inside ordered chapters, times them, and puts strays last", () => {
  const laid = layout(spec, { spine: beats, groups: chapters, lanes: { lines, sounds } });
  assert.deepEqual(laid.groups.map((g) => [g.title, g.items.map((i) => i.slug)]), [["c1", ["b1", "b2"]], ["c2", ["b3"]], ["", ["b4"]]]);
  const [b1, b2, b3, b4] = laid.items;
  // b1: lead 0.3 + l1 2.0 + gap 0.25 + l2 1.2 + tail 0.35 = 4.1
  assert.equal(b1.seconds.toFixed(2), "4.10");
  assert.equal(b1.estimated, true);
  assert.equal(b1.picture, "https://cdn/still.png");
  // b2 has one line with no text and no take: nothing timed, so it holds
  assert.equal(b2.seconds, 4);
  assert.equal(b2.start.toFixed(2), "4.10");
  assert.equal(b2.lanes.lines.length, 1);
  assert.equal(b2.text, "A door.");
  assert.equal(b3.seconds, 6);
  assert.equal(b4.start.toFixed(2), "14.10");
  assert.equal(laid.total.toFixed(2), "18.10");
  assert.equal(laid.groups[0].seconds.toFixed(2), "8.10");
});

test("layout places line pieces one after another from the lead, recorded or estimated", () => {
  const laid = layout(spec, { spine: beats, groups: chapters, lanes: { lines, sounds } });
  const [l1, l2] = laid.items[0].lanes.lines;
  assert.deepEqual([l1.slug, l1.start.toFixed(2), l1.seconds, l1.estimated, l1.audio, l1.who], ["l1", "0.30", 2, false, "https://cdn/take.mp3", "Bob"]);
  assert.deepEqual([l2.slug, l2.start.toFixed(2), l2.seconds, l2.estimated, l2.audio], ["l2", "2.55", 1.2, true, null]);
});

test("layout puts placed sounds at their offset and drops a reference to nothing", () => {
  const laid = layout(spec, { spine: beats, groups: chapters, lanes: { lines, sounds } });
  const placed = laid.items[0].lanes.sounds;
  assert.equal(placed.length, 1);
  assert.deepEqual([placed[0].slug, placed[0].at, placed[0].start, placed[0].seconds], ["rain", 1.5, 1.5, 3]);
  assert.deepEqual(laid.items[1].lanes.sounds, []);
});

test("rows with no order field sort by slug, as the renderer does", () => {
  const unordered = { ...spec, lanes: [{ ...spec.lanes[0], order: undefined }] };
  const laid = layout(unordered, { spine: beats, groups: chapters, lanes: { lines: [...lines].reverse() } });
  assert.deepEqual(laid.items[0].lanes.lines.map((p) => p.slug), ["l1", "l2"]);
});

test("layout without a group spec is one untitled group; without lanes every item holds", () => {
  const bare = { ...spec, spine: { entry_type: "beat", of: "story", order: "number" }, lanes: undefined };
  const laid = layout(bare, { spine: beats, lanes: {} });
  assert.deepEqual(laid.groups.map((g) => g.title), [""]);
  assert.deepEqual(laid.items.map((i) => i.seconds), [4, 4, 4, 4]);
  assert.equal(laid.total, 16);
});

test("scale fills the width but never shrinks the shortest item under its minimum card", () => {
  assert.equal(scale([{ seconds: 10 }, { seconds: 10 }], 20, 1000), 50);
  assert.equal(scale([{ seconds: 0.3 }, { seconds: 10 }], 10.3, 1000), 240);
  assert.equal(scale([], 0, 1000), 0);
  assert.equal(widthOf(0.3, 50), 72);
  assert.equal(widthOf(10, 50), 500);
});

test("ticks pick a step for about ten marks", () => {
  assert.deepEqual(ticks(18.1), [0, 2, 4, 6, 8, 10, 12, 14, 16, 18]);
  assert.deepEqual(ticks(4), [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4]);
  assert.equal(ticks(600).length, 11);
  assert.deepEqual(ticks(0), [0]);
});

test("progress counts pictures and takes, and reads as a line", () => {
  const laid = layout(spec, { spine: beats, groups: chapters, lanes: { lines, sounds } });
  const steps = progress(spec, laid);
  assert.deepEqual(steps, [
    { label: "beats with a picture", done: 1, total: 4 },
    { label: "lines recorded", done: 1, total: 3 },
    { label: "sounds recorded", done: 0, total: 1 },
  ]);
  assert.equal(progressLine(steps), "1 of 4 beats with a picture · 1 of 3 lines recorded · 0 of 1 sounds recorded");
});

test("cues walk every second of the timeline: silences, takes and estimated lines, holds", () => {
  const laid = layout(spec, { spine: beats, groups: chapters, lanes: { lines, sounds } });
  const walk = cues(laid, spec.lanes);
  const b1 = walk.filter((c) => c.item === "id-b1");
  assert.deepEqual(
    b1.map((c) => [c.piece, c.start.toFixed(2), c.seconds.toFixed(2), c.audio]),
    [
      [null, "0.00", "0.30", null],
      ["id-l1", "0.30", "2.00", "https://cdn/take.mp3"],
      [null, "2.30", "0.25", null],
      ["id-l2", "2.55", "1.20", null],
      [null, "3.75", "0.35", null],
    ],
  );
  assert.deepEqual(walk.find((c) => c.item === "id-b3"), { item: "id-b3", piece: null, lane: null, start: 8.1, seconds: 6, audio: null });
  assert.equal(walk.find((c) => c.piece === "id-l1").lane, "lines");
  const end = walk[walk.length - 1];
  assert.equal((end.start + end.seconds).toFixed(2), laid.total.toFixed(2));
});

test("the strip fills its container: percent positions, and a pixel floor that keeps the shortest item clickable", () => {
  assert.equal(percent(5, 20), "25%");
  assert.equal(percent(1, 3), "33.3333%");
  assert.equal(percent(0, 0), "0%");
  assert.equal(minInnerWidth([{ seconds: 0.3 }, { seconds: 10 }], 10.3), 2472);
  assert.equal(minInnerWidth([{ seconds: 4 }, { seconds: 6 }], 10), 180);
  assert.equal(minInnerWidth([], 0), 0);
});

test("tick levels: the fitted ruler's ticks show at every zoom, finer ticks only when zoomed in", () => {
  const all = tickLevels(18.1);
  assert.deepEqual(all.find((x) => x.t === 0).levels, [1, 2, 4, 8]);
  assert.deepEqual(all.find((x) => x.t === 2).levels, [1, 2, 4, 8]);
  assert.deepEqual(all.find((x) => x.t === 1).levels, [2, 4, 8]);
  assert.deepEqual(all.find((x) => x.t === 0.5).levels, [4, 8]);
  assert.equal(all.filter((x) => x.levels.includes(1)).length, ticks(18.1).length);
  assert.deepEqual(all.map((x) => x.t).slice(0, 4), [0, 0.5, 1, 1.5]);
});

const bedSpec = {
  ...spec,
  lanes: [
    ...spec.lanes,
    { id: "ambience", title: "Ambience", entry_type: "sound", bed: { via: "scene", entry_type: "scene", field: "ambience", volume: "ambience_volume", item_volume: "ambience_volume", muffled: "ambience_muffled" }, audio: "audio", loop: "loop", volume: "volume" },
    { id: "music", title: "Music", entry_type: "sound", bed: { field: "music" }, audio: "audio", loop: "loop", volume: "volume" },
  ],
};
const sea = { role: "audio", publicUrl: "https://cdn/sea.mp3", mimeType: "audio/mpeg" };
const tune = { role: "audio", publicUrl: "https://cdn/tune.mp3", mimeType: "audio/mpeg" };
const bedBeats = [
  row("b1", { story: "s", number: 1, scene: "deck", chapter: "c1" }),
  row("b2", { story: "s", number: 2, scene: "deck", chapter: "c1" }),
  row("b3", { story: "s", number: 3, scene: "deck", chapter: "c1", ambience_volume: 0.2 }),
  row("b4", { story: "s", number: 4, scene: "hold", chapter: "c1" }),
  row("b5", { story: "s", number: 5, scene: "nowhere", chapter: "c1" }),
];
const scenes = [row("deck", { ambience: "sea", ambience_volume: 0.5 }), row("hold", { ambience: "sea", ambience_volume: 0.5, ambience_muffled: true })];
const bedSounds = [row("sea", { volume: 0.8, loop: true }, { assets: [sea] }), row("waltz", { volume: 0.3 }, { assets: [tune] })];

test("bed lanes: a scene's ambience runs under its beats as one block, splits on a level or muffling change, skips an unknown scene", () => {
  const laid = layout(bedSpec, { entry: row("s", { music: "waltz" }), spine: bedBeats, groups: chapters, lanes: { lines: [], sounds: [], ambience: bedSounds, music: bedSounds }, via: { ambience: scenes } });
  const amb = laid.beds.ambience;
  assert.deepEqual(amb.map((b) => [b.slug, b.start, b.seconds, b.items.length, Number(b.volume.toFixed(2)), b.muffled, b.loop]), [
    ["sea", 0, 8, 2, 0.4, false, true], // b1 + b2 at 0.8 × 0.5
    ["sea", 8, 4, 1, 0.16, false, true], // b3 lowers its own level: 0.8 × 0.2
    ["sea", 12, 4, 1, 0.4, true, true], // the hold: same sound, muffled, so its own block
  ]);
  assert.equal(amb[0].audio, "https://cdn/sea.mp3");
  assert.deepEqual(laid.beds.music.map((b) => [b.slug, b.start, b.seconds, Number(b.volume.toFixed(2)), b.items.length]), [["waltz", 0, 20, 0.3, 5]]);
});

test("progress: a bed lane counts its blocks with a take, and an empty lane says nothing", () => {
  const laid = layout(bedSpec, { entry: row("s", { music: "waltz" }), spine: bedBeats, groups: chapters, lanes: { lines: [], sounds: [], ambience: bedSounds, music: bedSounds }, via: { ambience: scenes } });
  assert.deepEqual(progress(bedSpec, laid).map((p) => p.label + " " + p.done + "/" + p.total), ["beats with a picture 0/5", "ambience with a take 3/3", "music with a take 1/1"]);
});

test("bed lanes: nothing named, nothing drawn; a story without music has no music block", () => {
  const laid = layout(bedSpec, { entry: row("s", {}), spine: bedBeats, groups: chapters, lanes: { lines: [], sounds: [], ambience: [], music: bedSounds } });
  assert.deepEqual(laid.beds, { ambience: [], music: [] });
});

test("overlays: placed sounds at their offset and beds under their stretch, in time order, with levels", () => {
  const placed = [row("b6", { story: "s", number: 6, chapter: "c1", sounds: [{ sound: "gull", at: 1 }, { sound: "silent", at: 2 }] })];
  const fx = [row("gull", { duration_seconds: 2, volume: 0.6 }, { assets: [take] }), row("silent", { duration_seconds: 1 })];
  const laid = layout(bedSpec, { entry: row("s", { music: "waltz" }), spine: [...bedBeats, ...placed], groups: chapters, lanes: { lines: [], sounds: fx, ambience: bedSounds, music: bedSounds }, via: { ambience: scenes } });
  const over = overlays(laid, bedSpec.lanes);
  assert.deepEqual(over.map((o) => o.lane), ["ambience", "music", "ambience", "ambience", "sounds"]);
  assert.deepEqual(over.map((o) => [o.id, o.start, o.seconds, o.loop, Number(o.volume.toFixed(2))]), [
    ["id-sea", 0, 8, true, 0.4],
    ["id-waltz", 0, laid.total, true, 0.3],
    ["id-sea", 8, 4, true, 0.16],
    ["id-sea", 12, 4, true, 0.4],
    ["id-gull", 21, 2, false, 0.6], // the placed effect at its offset inside b6 (which starts at 20); the one with no take is not played
  ]);
});

test("quiets: the lead, the gaps and the tail the renderer adds around lines, or a whole hold", () => {
  const laid = layout(spec, { spine: beats, groups: chapters, lanes: { lines, sounds } });
  const q = quiets(laid.items, spec.lanes[0]).map((x) => [x.id, x.kind, x.start.toFixed(2), x.seconds.toFixed(2)]);
  assert.deepEqual(q.slice(0, 4), [["id-b1:lead", "lead", "0.00", "0.30"], ["id-b1:gap0", "gap", "2.30", "0.25"], ["id-b1:tail", "tail", "3.75", "0.35"], ["id-b2:hold", "hold", "4.10", "4.00"]]);
  assert.deepEqual(quiets(laid.items, spec.lanes[1]), []);
});

test("a line with a take but no stored length keeps the text's estimate and says the take's length is unknown", () => {
  const spec2 = { ...spec, lanes: [spec.lanes[0]] };
  const only = [row("b1", { story: "s", number: 1 }), row("b2", { story: "s", number: 2 })];
  const ls = [
    row("took", { beat: "b1", number: 1, text: "one two three", speaker: "Ann" }, { assets: [take] }),
    row("none", { beat: "b2", number: 1, text: "one two three", speaker: "Ann" }),
  ];
  const laid = layout(spec2, { spine: only, groups: [], lanes: { lines: ls } });
  const [a] = laid.items[0].lanes.lines;
  const [b] = laid.items[1].lanes.lines;
  assert.deepEqual([a.estimated, a.unmeasured, a.seconds, !!a.audio], [true, true, 1.2, true]);
  assert.deepEqual([b.estimated, b.unmeasured, !!b.audio], [true, false, false]);
});

test("stackRows: pieces that overlap in time go on different rows, and a free row is reused", () => {
  const pieces = [
    { start: 0, seconds: 3 }, // row 0
    { start: 1, seconds: 3 }, // overlaps the first: row 1
    { start: 2, seconds: 1 }, // row 0 and row 1 are busy: row 2
    { start: 4, seconds: 1 }, // the others are done: row 0 again
  ];
  assert.deepEqual(stackRows(pieces), [0, 1, 2, 0]);
  assert.deepEqual(stackRows([]), []);
  assert.deepEqual(stackRows([{ start: 0, seconds: 1 }, { start: 1, seconds: 1 }]), [0, 0]); // back to back share a row
  // a zero-length piece still holds its row for a moment, so a neighbour starting just after does not hide its label
  assert.deepEqual(stackRows([{ start: 0, seconds: 0 }, { start: 0.5, seconds: 1 }]), [0, 1]);
  // rows come back in the order given, whatever the time order
  assert.deepEqual(stackRows([{ start: 5, seconds: 1 }, { start: 0, seconds: 6 }]), [1, 0]);
});
