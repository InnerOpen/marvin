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
    ["sea", 0, 8, 2, 0.5, false, true], // b1 + b2 at the scene's 0.5: it replaces the sound's own 0.8, as in the render
    ["sea", 8, 4, 1, 0.2, false, true], // b3 sets its own level
    ["sea", 12, 4, 1, 0.5, true, true], // the hold: same sound, muffled, so its own block
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
    ["id-sea", 0, 8, true, 0.5],
    ["id-waltz", 0, laid.total, true, 0.3],
    ["id-sea", 8, 4, true, 0.2],
    ["id-sea", 12, 4, true, 0.5],
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

// ── Release C2: music levels per beat and a video over the pictures ──────────────────────────────────────────────────────────────────────
const musicSpec = () => ({ ...bedSpec, lanes: bedSpec.lanes.map((l) => (l.id === "music" ? { ...l, bed: { field: "music", item_volume: "music_volume" } } : l)) });
const musicLaid = (levels) => {
  const spine = bedBeats.map((b, i) => (levels[i] === undefined ? b : { ...b, dataJson: { ...b.dataJson, music_volume: levels[i] } }));
  return layout(musicSpec(), { entry: row("s", { music: "waltz" }), spine, groups: chapters, lanes: { lines: [], sounds: [], ambience: bedSounds, music: bedSounds }, via: { ambience: scenes } });
};

test("music: a beat that sets its own level shows as steps; one at zero is a silent step; no override, no steps", () => {
  assert.deepEqual(musicLaid([]).beds.music[0].steps, []);
  const [bed] = musicLaid([undefined, undefined, 0, undefined, undefined]).beds.music;
  assert.deepEqual(bed.steps.map((s) => [s.start, s.seconds, s.volume]), [[0, 8, 0.3], [8, 4, 0], [12, 8, 0.3]]);
  assert.equal(bed.volume, 0.3); // the block itself is still the story's level
});

test("music: neighbouring beats at one level are one step, and a level equal to the story's is no change", () => {
  const [bed] = musicLaid([0.3, 0.3, 0.1, 0.1, undefined]).beds.music;
  assert.deepEqual(bed.steps.map((s) => [s.start, s.seconds, s.volume]), [[0, 8, 0.3], [8, 8, 0.1], [16, 4, 0.3]]);
  assert.deepEqual(musicLaid([0.3, 0.3, 0.3, 0.3, 0.3]).beds.music[0].steps, []);
});

test("music: playback plays each audible step at its own level, keeps its place in the file across them and plays nothing in a silent one", () => {
  const laid = musicLaid([undefined, undefined, 0, undefined, undefined]);
  const music = overlays(laid, musicSpec().lanes).filter((o) => o.lane === "music");
  assert.deepEqual(music.map((o) => [o.start, o.seconds, o.volume, o.origin]), [[0, 8, 0.3, 0], [12, 8, 0.3, 0]]);
});

test("music: an unchanged bed still plays as one piece with no origin", () => {
  const music = overlays(musicLaid([]), musicSpec().lanes).filter((o) => o.lane === "music");
  assert.deepEqual(music.map((o) => [o.start, o.seconds, o.origin]), [[0, 20, undefined]]);
});

const rain = { role: "overlay", publicUrl: "https://cdn/media/rain-loop.webm?sig=1", mimeType: "video/webm" };
const grain = { role: "overlay", publicUrl: "https://cdn/media/grain.mp4", mimeType: "video/mp4" };
const coverSpec = { ...spec, lanes: [...spec.lanes, { id: "overlay", title: "Overlay", entry_type: "beat", cover: { field: "overlay", blend: "overlay_blend", opacity: "overlay_opacity", via: "scene", entry_type: "scene" } }] };
const coverLaid = ({ story = {}, storyAssets = [], scenes: sc, beatsData = [] }) => {
  const spine = bedBeats.map((b, i) => ({ ...b, dataJson: { ...b.dataJson, ...(beatsData[i] ?? {}) }, assets: beatsData[i]?.assets ?? [] }));
  return layout(coverSpec, { entry: row("s", story, { assets: storyAssets }), spine, groups: chapters, lanes: { lines: [], sounds: [] }, via: { overlay: sc ?? [] } });
};

test("overlay lane: the story's video runs under every beat as one block, named by its file, blend normal at full strength", () => {
  const [c] = coverLaid({ storyAssets: [grain] }).covers.overlay;
  assert.deepEqual([c.name, c.from, c.blend, c.opacity, c.start, c.seconds, c.items.length], ["grain.mp4", "story", "normal", 1, 0, 20, 5]);
});

test("overlay lane: a scene's wins over the story's, a beat's over both, and the blocks split where the video, blend or strength change", () => {
  const laid = coverLaid({
    storyAssets: [grain],
    scenes: [row("deck", { overlay_blend: "screen", overlay_opacity: 0.5 }, { assets: [rain] })],
    beatsData: [{}, {}, { assets: [grain], overlay_blend: "multiply" }],
  });
  assert.deepEqual(laid.covers.overlay.map((c) => [c.name, c.from, c.blend, c.opacity, c.start, c.seconds]), [
    ["rain-loop.webm", "scene", "screen", 0.5, 0, 8], // b1 and b2, from the deck
    ["grain.mp4", "beat", "multiply", 1, 8, 4], // b3's own
    ["grain.mp4", "story", "normal", 1, 12, 8], // b4 (scene "hold" has none) and b5 (no such scene) fall back to the story's
  ]);
});

test("overlay lane: a blend of none switches the overlay off from that level up, and a beat of its own still gets its own", () => {
  const laid = coverLaid({
    storyAssets: [grain],
    scenes: [row("deck", { overlay_blend: "none" }, { assets: [rain] })],
    beatsData: [{}, { assets: [rain] }, { overlay_blend: "none" }],
  });
  // b1: the scene says none; b2: its own rain; b3: none on the beat; b4 and b5: the story's again
  assert.deepEqual(laid.covers.overlay.map((c) => [c.name, c.from, c.start, c.seconds]), [
    ["rain-loop.webm", "beat", 4, 4],
    ["grain.mp4", "story", 12, 8],
  ]);
});

test("overlay lane: nothing named anywhere draws nothing, and an image attached in that role is not a video", () => {
  assert.deepEqual(coverLaid({}).covers, { overlay: [] });
  assert.deepEqual(coverLaid({ storyAssets: [{ role: "overlay", publicUrl: "https://cdn/x.png", mimeType: "image/png" }] }).covers.overlay, []);
});

test("overlay lane: a view without one has no covers", () => {
  assert.deepEqual(layout(spec, { spine: bedBeats, groups: chapters, lanes: { lines: [], sounds: [] } }).covers, {});
});

// ── a bed's level is the render's: where named, else the sound's own, else the lane's default ─────────────────────────────────────────
const quietSounds = [row("sea", {}, { assets: [sea] }), row("waltz", {}, { assets: [tune] })]; // neither sets a level
const defaultsSpec = {
  ...bedSpec,
  lanes: bedSpec.lanes.map((l) => (l.id === "music" ? { ...l, bed: { field: "music", item_volume: "music_volume", default_volume: 0.12 } } : l.id === "ambience" ? { ...l, bed: { ...l.bed, default_volume: 0.5 } } : l)),
};

test("bed levels: a sound with no level of its own plays at the lane's default (0.12 for music, 0.5 for ambience), as the render does", () => {
  const laid = layout(defaultsSpec, { entry: row("s", { music: "waltz" }), spine: bedBeats, groups: chapters, lanes: { lines: [], sounds: [], ambience: quietSounds, music: quietSounds }, via: { ambience: [row("deck", { ambience: "sea" })] } });
  assert.equal(laid.beds.music[0].volume, 0.12);
  assert.equal(laid.beds.ambience[0].volume, 0.5);
  assert.equal(layout(bedSpec, { entry: row("s", { music: "waltz" }), spine: bedBeats, groups: chapters, lanes: { lines: [], sounds: [], ambience: quietSounds, music: quietSounds } }).beds.music[0].volume, 1); // no default declared: full
});

test("bed levels: a beat that sets 0.3 over music at the default 0.12 is a step *up*, drawn as one", () => {
  const spine = bedBeats.map((b, i) => (i === 2 ? { ...b, dataJson: { ...b.dataJson, music_volume: 0.3 } } : b));
  const laid = layout(defaultsSpec, { entry: row("s", { music: "waltz" }), spine, groups: chapters, lanes: { lines: [], sounds: [], ambience: quietSounds, music: quietSounds }, via: {} });
  assert.deepEqual(laid.beds.music[0].steps.map((s) => [s.start, s.seconds, s.volume]), [[0, 8, 0.12], [8, 4, 0.3], [12, 8, 0.12]]);
});

test("bed levels: the sound's own level beats the default, and the level where it is named beats both", () => {
  const laid = layout(defaultsSpec, { entry: row("s", { music: "waltz" }), spine: bedBeats, groups: chapters, lanes: { lines: [], sounds: [], ambience: bedSounds, music: bedSounds }, via: { ambience: scenes } });
  assert.equal(laid.beds.music[0].volume, 0.3); // the waltz's own 0.3, not 0.12
  assert.equal(laid.beds.ambience[0].volume, 0.5); // the deck scene's 0.5, not the sea's 0.8
});

// ── fades on bed blocks, as the render plays them ─────────────────────────────────────────────────────────────────────────────────────
const fadeSpec = {
  ...bedSpec,
  lanes: bedSpec.lanes.map((l) =>
    l.id === "music"
      ? { ...l, bed: { field: "music", fade_in: "fade_in", fade_out: "fade_out", default_fade_out: 2, end_fade: "end_fade_seconds" } }
      : l.id === "ambience"
        ? { ...l, bed: { ...l.bed, fade_in: "fade_in", fade_out: "fade_out", default_fade_in: 0.6, default_fade_out: 0.6, end_fade: "end_fade_seconds" } }
        : l,
  ),
};
const fadeLaid = (story, soundsData = {}) =>
  layout(fadeSpec, {
    entry: row("s", { music: "waltz", ...story }),
    spine: bedBeats,
    groups: chapters,
    lanes: { lines: [], sounds: [], ambience: [row("sea", { volume: 0.8, ...soundsData }, { assets: [sea] })], music: [row("waltz", { volume: 0.3, ...soundsData }, { assets: [tune] })] },
    via: { ambience: [...scenes, row("nowhere", { ambience: "sea", ambience_volume: 0.5 })] }, // the last beat has a bed too, so one block runs to the end
  });

test("bed fades: music fades out over 2 s by default and in over nothing; a crossfade is 0.6 s on an ambience", () => {
  const laid = fadeLaid({});
  assert.deepEqual([laid.beds.music[0].fadeIn, laid.beds.music[0].fadeOut], [0, 2]);
  assert.deepEqual(laid.beds.ambience.map((b) => [b.fadeIn, b.fadeOut]), [[0.6, 0.6], [0.6, 0.6], [0.6, 0.6], [0.6, 0.6]]);
});

test("bed fades: the sound's own fades replace the defaults", () => {
  const laid = fadeLaid({}, { fade_in: 1.5, fade_out: 3 });
  assert.deepEqual([laid.beds.music[0].fadeIn, laid.beds.music[0].fadeOut], [1.5, 3]);
});

test("bed fades: the story's end fade wins for the music and for the ambience block that runs to the end, and for no other", () => {
  const laid = fadeLaid({ end_fade_seconds: 5 }, { fade_out: 1 });
  assert.equal(laid.beds.music[0].fadeOut, 5);
  const amb = laid.beds.ambience;
  assert.deepEqual(amb.map((b) => b.fadeOut), [1, 1, 1, 2]); // only the last block touches the end of the film; its 5 s is held to half of its 4 s, as the render does
});

// ── Play follows the render: fades and the dip under speech ───────────────────────────────────────────────────────────────────────────
import { gainAt, speechWindows, DUCK_DEPTH } from "./timeline.ts";

test("gain: a bed rises over its fade-in, falls over its fade-out, and is 1 between; no fade is always 1", () => {
  const o = { id: "m", lane: "music", start: 0, seconds: 20, audio: "x", volume: 1, loop: true, fade: { from: 0, to: 20, in: 2, out: 4 } };
  assert.equal(gainAt(o, 0), 0);
  assert.equal(gainAt(o, 1), 0.5);
  assert.equal(gainAt(o, 10), 1);
  assert.equal(gainAt(o, 18), 0.5); // half way down a 4 s fade-out
  assert.equal(gainAt(o, 20), 0);
  assert.equal(gainAt({ ...o, fade: undefined }, 20), 1);
});

test("gain: under a speech window it goes down to the depth over 0.2 s before the line and comes back over 0.5 s after", () => {
  const o = { id: "m", lane: "music", start: 0, seconds: 30, audio: "x", volume: 1, loop: true, duck: { depth: DUCK_DEPTH.strong, windows: [[10, 12]] } };
  assert.equal(gainAt(o, 9), 1);
  assert.ok(Math.abs(gainAt(o, 9.9) - (1 - 0.88 * 0.5)) < 1e-9); // half way down, 0.1 s before the line
  assert.ok(Math.abs(gainAt(o, 11) - 0.12) < 1e-9); // inside the line
  assert.ok(Math.abs(gainAt(o, 12.25) - (1 - 0.88 * 0.5)) < 1e-9); // half way back
  assert.equal(gainAt(o, 13), 1);
});

test("gain: a fade and a dip multiply", () => {
  const o = { id: "m", lane: "music", start: 0, seconds: 20, audio: "x", volume: 1, loop: true, fade: { from: 0, to: 20, in: 0, out: 4 }, duck: { depth: 0.5, windows: [[17, 19]] } };
  assert.ok(Math.abs(gainAt(o, 18) - 0.5 * 0.5) < 1e-9); // half way down the fade-out, and ducked to half
});

const duckSpec = { ...spec, lanes: [...spec.lanes, { id: "music", title: "Music", entry_type: "sound", bed: { field: "music", duck: "music_ducking", default_fade_out: 2 }, audio: "audio", loop: "loop", volume: "volume" }] };

test("speech windows: pieces with a take, joined when closer than a ramp; a line with no take does not duck", () => {
  const laid = layout(duckSpec, { spine: bedBeats, groups: chapters, lanes: { lines: [], sounds: [], music: [] } });
  // lay pieces by hand: two lines with takes 0.4 s apart, one far away, one with no take
  laid.items[0].lanes.lines = [
    { id: "a", start: 1, seconds: 2, audio: "t", estimated: false },
    { id: "b", start: 3.4, seconds: 1, audio: "t", estimated: false },
    { id: "c", start: 9, seconds: 1, audio: null, estimated: true },
    { id: "d", start: 12, seconds: 1, audio: "t", estimated: false },
  ];
  assert.deepEqual(speechWindows(laid, duckSpec.lanes), [[1, 4.4], [12, 13]]);
});

test("overlays: a music bed that ducks and fades carries both, and one that does not carries neither", () => {
  const ducking = layout(duckSpec, { entry: row("s", { music: "waltz", music_ducking: "light" }), spine: bedBeats, groups: chapters, lanes: { lines: [], sounds: [], music: bedSounds } });
  ducking.items[0].lanes.lines = [{ id: "a", start: 1, seconds: 2, audio: "t", estimated: false }];
  const [m] = overlays(ducking, duckSpec.lanes).filter((o) => o.lane === "music");
  assert.deepEqual(m.duck, { depth: 0.35, windows: [[1, 3]] });
  assert.deepEqual(m.fade, { from: 0, to: 20, in: 0, out: 2 });
  const quiet = layout(duckSpec, { entry: row("s", { music: "waltz", music_ducking: "none" }), spine: bedBeats, groups: chapters, lanes: { lines: [], sounds: [], music: bedSounds } });
  const [q] = overlays(quiet, duckSpec.lanes).filter((o) => o.lane === "music");
  assert.equal(q.duck, undefined);
});

test("an item carries the value its run button hands the workflow, exactly as written (04a keeps its letter and zero)", () => {
  const runSpec = { ...spec, spine: { ...spec.spine, run: { workflow: "screenplay-render", entry: "story", item: "beats", field: "number", inputs: { quality: "draft" } } } };
  const laid = layout(runSpec, { spine: [row("b4", { story: "s", number: "04a", chapter: "c1" }), row("b5", { story: "s", number: "05", chapter: "c1" })], groups: chapters, lanes: { lines: [], sounds: [] } });
  assert.deepEqual(laid.items.map((i) => i.key), ["04a", "05"]);
  assert.deepEqual(layout(spec, { spine: bedBeats, groups: chapters, lanes: { lines: [], sounds: [] } }).items.map((i) => i.key), ["", "", "", "", ""]); // no run declared: nothing
});

test("a beat inserted as 04a sits between 04 and 05, as the render orders them, with or without zeros", () => {
  const laid = layout(spec, { spine: [row("b5", { story: "s", number: "05", chapter: "c1" }), row("b4a", { story: "s", number: "04a", chapter: "c1" }), row("b4", { story: "s", number: "04", chapter: "c1" }), row("b10", { story: "s", number: "10", chapter: "c1" }), row("b2", { story: "s", number: 2, chapter: "c1" })], groups: chapters, lanes: { lines: [], sounds: [] } });
  assert.deepEqual(laid.items.map((i) => i.slug), ["b2", "b4", "b4a", "b5", "b10"]);
});

test("overlay lane: a block is named by the asset's title; its file name is only the fallback for one with no title", () => {
  const titled = { ...rain, name: "Light rain on glass" };
  const [c] = coverLaid({ storyAssets: [titled] }).covers.overlay;
  assert.equal(c.name, "Light rain on glass");
  assert.equal(coverLaid({ storyAssets: [{ ...rain, name: "  " }] }).covers.overlay[0].name, "rain-loop.webm");
  assert.equal(coverLaid({ storyAssets: [rain] }).covers.overlay[0].name, "rain-loop.webm");
  // two videos with different titles but one file are still one video: they merge by address, the label is the first's
  assert.equal(coverLaid({ storyAssets: [titled] }).covers.overlay.length, 1);
});

// ── layered ambience (the story's under the film, a beat's or its scene's over it) and scene bands ─────────────────────────────────────
const layerSpec = {
  ...bedSpec,
  lanes: bedSpec.lanes.map((l) => (l.id === "ambience" ? { ...l, bed: { ...l.bed, item_field: "ambience", entry_field: "ambience", entry_volume: "ambience_volume" } } : l)),
};
const gull = { role: "audio", publicUrl: "https://cdn/gull.mp3", mimeType: "audio/mpeg" };
const layered = (storyData, beatData = []) =>
  layout(layerSpec, {
    entry: row("s", { music: "waltz", ...storyData }),
    spine: bedBeats.map((b, i) => ({ ...b, dataJson: { ...b.dataJson, ...(beatData[i] ?? {}) } })),
    groups: chapters,
    lanes: { lines: [], sounds: [], ambience: [...bedSounds, row("hum", { volume: 0.2, loop: true }, { assets: [tune] }), row("gull", { volume: 0.7 }, { assets: [gull] })], music: bedSounds },
    via: { ambience: scenes },
  });

test("layered ambience: the story's bed runs under the whole film and is its own block beside the scenes' blocks", () => {
  const amb = layered({ ambience: "hum", ambience_volume: 0.1 }).beds.ambience;
  assert.deepEqual(amb[0] && [amb[0].slug, amb[0].start, amb[0].seconds, amb[0].volume], ["hum", 0, 20, 0.1]);
  assert.deepEqual(amb.slice(1).map((b) => b.slug), ["sea", "sea", "sea"]); // the scenes' blocks are still there, layered with it
});

test("layered ambience: a beat's own sound replaces its scene's for that beat, unmuffled, and stacks with the story's", () => {
  const amb = layered({ ambience: "hum" }, [undefined, undefined, { ambience: "gull" }]).beds.ambience;
  assert.deepEqual(amb.map((b) => [b.slug, b.start, b.seconds, b.muffled]), [["hum", 0, 20, false], ["sea", 0, 8, false], ["gull", 8, 4, false], ["sea", 12, 4, true]]);
});

test("layered ambience: a story that names none adds no block, and playback has every layer at once", () => {
  assert.deepEqual(layered({}).beds.ambience.map((b) => b.slug), ["sea", "sea", "sea"]);
  const over = overlays(layered({ ambience: "hum" }), layerSpec.lanes).filter((o) => o.lane === "ambience");
  assert.equal(over.filter((o) => o.start < 8 && o.start + o.seconds > 1).length, 2); // the story's and the first scene's, together
});

const sceneBand = { entry_type: "scene", field: "scene", title: "Scene" };
const bandSpec = { ...spec, spine: { ...spec.spine, bands: [sceneBand] } };
const bandLaid = (scenesOn) =>
  layout(bandSpec, {
    spine: bedBeats.map((b, i) => ({ ...b, dataJson: { ...b.dataJson, scene: scenesOn[i] ?? "" } })),
    groups: chapters,
    lanes: { lines: [], sounds: [] },
    bands: { scene: [row("deck", {}, { title: "On deck" }), row("cabin", {})].map((r) => ({ ...r, title: r.slug === "deck" ? "On the deck" : "Below" })) },
  });

test("scene bands wrap the consecutive beats that share a scene, titled by the scene, and leave beats with none out", () => {
  const { scene } = bandLaid(["deck", "deck", "cabin", "", "deck"]).bands;
  assert.deepEqual(scene.map((b) => [b.slug, b.title, b.start, b.seconds, b.items.length]), [["deck", "On the deck", 0, 8, 2], ["cabin", "Below", 8, 4, 1], ["deck", "On the deck", 16, 4, 1]]);
  assert.ok(scene[0].id && scene[2].id); // found, so it can be opened
});

test("a scene that was not found is titled by its slug; a view with no bands has none", () => {
  const { scene } = bandLaid(["gone", "gone"]).bands;
  assert.deepEqual([scene[0].title, scene[0].id, scene[0].items.length], ["gone", null, 2]);
  assert.deepEqual(layout(spec, { spine: bedBeats, groups: chapters, lanes: { lines: [], sounds: [] } }).bands, {});
});

// ── fades cascade: the sound's, then the story's, then the beat's ────────────────────────────────────────────────────────────────────────
const cascadeSpec = {
  ...bedSpec,
  lanes: bedSpec.lanes.map((l) =>
    l.id === "ambience"
      ? { ...l, bed: { ...l.bed, item_field: "ambience", entry_field: "ambience", fade_in: "fade_in", fade_out: "fade_out", default_fade_in: 0.6, default_fade_out: 0.6, start_fade: "start_fade_seconds", end_fade: "end_fade_seconds", entry_fade_in: "ambience_fade_in", entry_fade_out: "ambience_fade_out", item_fade_in: "ambience_fade_in", item_fade_out: "ambience_fade_out" } }
      : l.id === "music"
        ? { ...l, bed: { ...l.bed, fade_in: "fade_in", fade_out: "fade_out", default_fade_out: 2, start_fade: "start_fade_seconds", end_fade: "end_fade_seconds" } }
        : l,
  ),
};
const cascaded = (story, beatData = [], soundData = {}) =>
  layout(cascadeSpec, {
    entry: row("s", { music: "waltz", ambience: "hum", ...story }),
    spine: bedBeats.map((b, i) => ({ ...b, dataJson: { ...b.dataJson, ...(beatData[i] ?? {}) } })),
    groups: chapters,
    lanes: { lines: [], sounds: [], ambience: [...bedSounds, row("hum", { volume: 0.2, ...soundData }, { assets: [tune] })], music: bedSounds },
    via: { ambience: scenes },
  });
const story = (laid) => laid.beds.ambience.find((b) => b.slug === "hum"); // the story's own bed, under the whole film
const sea1 = (laid) => laid.beds.ambience.find((b) => b.slug === "sea" && b.start === 0); // the first scene's block

test("fade cascade: the sound's own fade is the base, the story's replaces it, a beat's replaces the story's", () => {
  assert.deepEqual([story(cascaded({}, [], { fade_in: 1.5, fade_out: 2.5 })).fadeIn, story(cascaded({}, [], { fade_in: 1.5, fade_out: 2.5 })).fadeOut], [1.5, 2.5]); // the sound alone
  const byStory = cascaded({ ambience_fade_in: 3, ambience_fade_out: 4 }, [], { fade_in: 1.5, fade_out: 2.5 });
  assert.deepEqual([story(byStory).fadeIn, story(byStory).fadeOut], [3, 4]); // the story over the sound
  assert.deepEqual([sea1(byStory).fadeIn, sea1(byStory).fadeOut], [3, 4]); // …and over the scenes' beds too (their first block is 8 s, so a 4 s fade is just the half it may take)
  const byBeat = cascaded({ ambience_fade_in: 3 }, [{ ambience_fade_in: 0.5, ambience_fade_out: 1 }]);
  assert.deepEqual([sea1(byBeat).fadeIn, sea1(byBeat).fadeOut], [0.5, 0.6]); // the first beat's own fade-in; the block's last beat sets none, so the default fade-out
});

test("fade cascade: the film's start and end fades cover what nothing more specific set, and a specific one is not replaced by them", () => {
  const film = cascaded({ start_fade_seconds: 5, end_fade_seconds: 6 }, [], { fade_in: 1, fade_out: 1 });
  assert.deepEqual([story(film).fadeIn, story(film).fadeOut], [5, 6]); // the film's, over the sound's
  const specific = cascaded({ start_fade_seconds: 5, end_fade_seconds: 6, ambience_fade_in: 0.3, ambience_fade_out: 0.4 });
  assert.deepEqual([story(specific).fadeIn, story(specific).fadeOut], [0.3, 0.4]); // the story's ambience setting is more specific than the film's
  assert.equal(cascaded({ start_fade_seconds: 5 }).beds.music[0].fadeIn, 5); // the music takes the film's start fade
});
