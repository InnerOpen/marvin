import assert from "node:assert/strict";
import { test } from "node:test";
import { aspectOf, canReview, clockText, jumpTo, parseClock, placeIn, cardMinPx, PICTURE_SIZES, cues, estimateSeconds, quiets, stackRows, itemSeconds, layout, minInnerWidth, overlays, percent, pieceSeconds, tickLevels, progress, progressLine, scale, secondsOf, ticks, widthOf } from "./timeline.ts";

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
  // b1: lead 0.3 + l1 2.0 + gap 0.25 + l2 1.2 + tail 0.35 = 4.1, but its 3 s rain sound placed at 1.5 runs to 4.5, and the render lets a beat last until then
  assert.equal(b1.seconds.toFixed(2), "4.50");
  assert.equal(b1.estimated, true);
  assert.equal(b1.picture, "https://cdn/still.png");
  // b2 has one line with no text and no take: nothing timed, so it holds
  assert.equal(b2.seconds, 4);
  assert.equal(b2.start.toFixed(2), "4.50");
  assert.equal(b2.lanes.lines.length, 1);
  assert.equal(b2.text, "A door.");
  assert.equal(b3.seconds, 6);
  assert.equal(b4.start.toFixed(2), "14.50");
  assert.equal(laid.total.toFixed(2), "18.50");
  assert.equal(laid.groups[0].seconds.toFixed(2), "8.50");
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
      [null, "3.75", "0.75", null], // the beat runs on until its rain sound has finished, so this quiet reaches 4.5
    ],
  );
  assert.deepEqual(walk.find((c) => c.item === "id-b3"), { item: "id-b3", piece: null, lane: null, start: 8.5, seconds: 6, audio: null });
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
  assert.deepEqual(q.slice(0, 4), [["id-b1:lead", "lead", "0.00", "0.30"], ["id-b1:gap0", "gap", "2.30", "0.25"], ["id-b1:tail", "tail", "3.75", "0.75"], ["id-b2:hold", "hold", "4.50", "4.00"]]);
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

const cardSpec = { ...spec, lanes: [...spec.lanes, { id: "overlay", title: "Overlay", entry_type: "beat", cover: { field: "overlay", via: "scene", entry_type: "scene", card: { title: "info_title", text: "info_text", delay: "overlay_delay", default_delay: 0.6, name: "Info card" } } }] };
const cardLaid = (beatsData) => {
  const spine = bedBeats.map((b, i) => ({ ...b, dataJson: { ...b.dataJson, ...(beatsData[i] ?? {}) }, assets: beatsData[i]?.assets ?? [] }));
  return layout(cardSpec, { entry: row("s", {}, { assets: [grain] }), spine, groups: chapters, lanes: { lines: [], sounds: [] }, via: { overlay: [] } });
};

test("overlay lane: a card the beat writes is a block of its own, in after the delay, and it takes the place of the overlay file for that beat", () => {
  const laid = cardLaid([{}, { info_title: "The Last Onion", info_text: "A ship.", overlay_delay: 1.5 }, {}]);
  assert.deepEqual(laid.covers.overlay.map((c) => [c.name, !!c.card, c.start, c.seconds, c.items.length]), [
    ["grain.mp4", false, 0, 4, 1], // b1: the story's file
    ["Info card: The Last Onion", true, 5.5, 2.5, 1], // b2 (4 to 8 s): in after 1.5 s, and the story's file is not drawn under it
    ["grain.mp4", false, 8, 12, 3], // b3 to b5: the file again
  ]);
});

test("overlay lane: a card with no delay set comes in after the default, a sentence alone names it, and no card text is no card", () => {
  const laid = cardLaid([{ info_text: "Only a sentence." }, { info_title: "  " }]);
  assert.deepEqual(laid.covers.overlay.slice(0, 2).map((c) => [c.name, c.card ?? false, c.start]), [["Info card: Only a sentence.", true, 0.6], ["grain.mp4", false, 4]]);
});

test("overlay lane: nothing named anywhere draws nothing, and a file that is no picture or video is not an overlay", () => {
  assert.deepEqual(coverLaid({}).covers, { overlay: [] });
  assert.deepEqual(coverLaid({ storyAssets: [{ role: "overlay", publicUrl: "https://cdn/x.pdf", mimeType: "application/pdf" }] }).covers.overlay, []);
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

test("beats inserted past 04z go on as 04aa, 04ab, which sit after 04z and before 05 (letters by length, then alphabet)", () => {
  const laid = layout(spec, { spine: ["05", "04aa", "04b", "04z", "04", "04ab", "04a"].map((n) => row(`b${n}`, { story: "s", number: n, chapter: "c1" })), groups: chapters, lanes: { lines: [], sounds: [] } });
  assert.deepEqual(laid.items.map((i) => i.slug), ["b04", "b04a", "b04b", "b04z", "b04aa", "b04ab", "b05"]);
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

// ── the story's bed turned down or muffled by a scene or a beat, and who set each stretch ────────────────────────────────────────────
const adjustSpec = {
  ...layerSpec,
  lanes: layerSpec.lanes.map((l) =>
    l.id === "ambience" ? { ...l, bed: { ...l.bed, entry_item_volume: "story_ambience_volume", entry_via_volume: "story_ambience_volume", entry_via_muffled: "story_ambience_muffled" } } : l,
  ),
};
const adjusted = (sceneRows, beatData = [], story = { ambience: "hum", ambience_volume: 0.2 }) =>
  layout(adjustSpec, {
    entry: row("s", story),
    spine: bedBeats.map((b, i) => ({ ...b, dataJson: { ...b.dataJson, ambience_volume: undefined, ...(beatData[i] ?? {}) } })),
    groups: chapters,
    lanes: { lines: [], sounds: [], ambience: [...bedSounds, row("hum", { volume: 0.5, loop: true }, { assets: [tune] })], music: bedSounds },
    via: { ambience: sceneRows },
  }).beds.ambience[0];

test("the story's bed: a scene turns it down and mutes it, a beat's own level wins, and each stretch says who set it", () => {
  const bed = adjusted([
    row("deck", { ambience: "sea", story_ambience_volume: 0.1, story_ambience_muffled: true }, { title: "On deck" }),
    row("hold", { ambience: "sea", story_ambience_volume: 0.03, story_ambience_muffled: true }, { title: "The hold" }),
  ], [undefined, undefined, { story_ambience_volume: 0.05 }]);
  assert.equal(bed.slug, "hum");
  assert.deepEqual(bed.steps.map((st) => [st.start, st.seconds, st.volume, st.source, st.by, st.muffled]), [
    [0, 8, 0.1, "scene", "On deck", true],
    [8, 4, 0.05, "beat", "b3", true], // the beat's own level, though its scene is heard from inside too
    [12, 4, 0.03, "scene", "The hold", true],
    [16, 4, 0.2, "story", undefined, false], // a beat in no known scene: the story's own level, not muffled
  ]);
});

test("the story's bed: nothing adjusted draws no steps, as before; a scene with no level of its own keeps the story's level but can still muffle", () => {
  assert.deepEqual(adjusted([row("deck", { ambience: "sea" }), row("hold", { ambience: "sea" })]).steps, []);
  const quiet = adjusted([row("deck", { story_ambience_muffled: true }, { title: "On deck" })]);
  assert.deepEqual(quiet.steps.map((st) => [st.start, st.seconds, st.volume, st.source, st.muffled]), [[0, 12, 0.2, "story", true], [12, 8, 0.2, "story", false]]);
});

test("the story's bed: a spec without the new keys is exactly what it was", () => {
  const plain = layered({ ambience: "hum", ambience_volume: 0.2 }).beds.ambience[0];
  assert.deepEqual(plain.steps, []);
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

// ── title and end cards: real items, so every beat after them starts when the render starts it ───────────────────────────────────────
const cardsSpec = { ...spec, spine: { ...spec.spine, cards: { intro: { title: "intro_title", seconds: "intro_seconds", default_seconds: 2.5, label: "Title card" }, outro: { title: "outro_title", seconds: "outro_seconds", default_seconds: 3 } } } };
const withCards = (story) => layout(cardsSpec, { entry: row("s", story), spine: bedBeats, groups: chapters, lanes: { lines: [], sounds: [] } });

test("cards: a title card and an end card are items that shift every beat after them and add to the total", () => {
  const laid = withCards({ intro_title: "Granny's Advice", intro_seconds: 3, outro_title: "Subscribe" });
  assert.deepEqual(laid.items.map((i) => [i.card ?? i.slug, i.start, i.seconds]).slice(0, 2), [["intro", 0, 3], ["b1", 3, 4]]);
  assert.equal(laid.items[0].text, "Granny's Advice");
  assert.deepEqual(laid.items.at(-1) && [laid.items.at(-1).card, laid.items.at(-1).start, laid.items.at(-1).seconds], ["outro", 23, 3]); // five 4 s beats, then the end card (default 3 s)
  assert.equal(laid.total, 26);
  assert.deepEqual([laid.groups[0].card, laid.groups[0].start, laid.groups.at(-1).card], ["intro", 0, "outro"]);
});

test("cards: a card with no title does not exist; a view with no cards has none; defaults fill in the length", () => {
  assert.equal(withCards({ intro_title: "  " }).items.some((i) => i.card), false);
  assert.equal(layout(spec, { entry: row("s", { intro_title: "x" }), spine: bedBeats, groups: chapters, lanes: { lines: [], sounds: [] } }).items.some((i) => i.card), false);
  const [intro] = withCards({ intro_title: "Hi" }).items;
  assert.equal(intro.seconds, 2.5);
});

test("cards: they are not beats (progress), have no bands, no overlay, and play as silence", () => {
  const laid = withCards({ intro_title: "Hi", outro_title: "Bye" });
  assert.equal(progress(cardsSpec, laid).find((p) => p.label.includes("picture")).total, 5); // the five beats, not seven items
  const silent = cues(laid, cardsSpec.lanes).filter((c) => c.item.startsWith("card:"));
  assert.deepEqual(silent.map((c) => [c.item, c.audio, c.seconds]), [["card:intro", null, 2.5], ["card:outro", null, 3]]);
  assert.deepEqual(quiets(laid.items, cardsSpec.lanes[0]).filter((q) => q.id.startsWith("card:")), []);
});

// ── a pause where a scene ends: the render adds the same seconds, so the timeline must ────────────────────────────────────────────────────
const breakSpec = { ...spec, spine: { ...spec.spine, scene_break: { field: "scene", seconds: "scene_break_seconds" } } };
const withBreaks = (story, scenesOn) => layout(breakSpec, { entry: row("s", story), spine: bedBeats.map((b, i) => ({ ...b, dataJson: { ...b.dataJson, scene: scenesOn[i] ?? "" } })), groups: chapters, lanes: { lines: [], sounds: [] } });

test("scene break: a pause follows an item whose next item is in another scene, and shifts everything after it", () => {
  const laid = withBreaks({ scene_break_seconds: 1.5 }, ["deck", "deck", "cabin", "", "cabin"]);
  assert.deepEqual(laid.items.map((i) => [i.slug, i.start, i.seconds, i.pause]), [["b1", 0, 4, 0], ["b2", 4, 5.5, 1.5], ["b3", 9.5, 4, 0], ["b4", 13.5, 4, 0], ["b5", 17.5, 4, 0]]); // deck→cabin after b2; b3 to an empty scene and b4 to cabin break nothing
  assert.equal(laid.total, 21.5);
});

test("scene break: none set, zero or no scenes means no pause (whatever a stored default was)", () => {
  for (const story of [{}, { scene_break_seconds: 0 }, { scene_break_seconds: "" }, { scene_break_seconds: -1 }]) assert.equal(withBreaks(story, ["deck", "cabin", "deck", "cabin", "deck"]).total, 20);
  assert.equal(withBreaks({ scene_break_seconds: 2 }, []).total, 20);
  assert.equal(layout(spec, { entry: row("s", { scene_break_seconds: 3 }), spine: bedBeats, groups: chapters, lanes: { lines: [], sounds: [] } }).total, 20); // a view that does not declare it
});

// ── a beat lasts until its last placed sound has finished, as the render does ──────────────────────────────────────────────────────────
test("a beat lasts at least until its last placed sound ends, and a sound inside the beat changes nothing", () => {
  const long = row("rumble", { duration_seconds: 9 }, { assets: [take] });
  const short = row("click", { duration_seconds: 1 }, { assets: [take] });
  const place = (cues) => layout(spec, { spine: [row("b1", { story: "s", number: 1, chapter: "c1", sounds: cues }), row("b2", { story: "s", number: 2, chapter: "c1" })], groups: chapters, lanes: { lines: [], sounds: [long, short] } });
  const over = place([{ sound: "rumble", at: 2 }]); // ends at 11, past the beat's 4 s hold
  assert.deepEqual(over.items.map((i) => [i.start, i.seconds]), [[0, 11], [11, 4]]);
  const inside = place([{ sound: "click", at: 1 }]); // ends at 2, inside it
  assert.deepEqual(inside.items.map((i) => [i.start, i.seconds]), [[0, 4], [4, 4]]);
  assert.equal(over.total, 15);
});

test("a sound with no length known does not stretch a beat", () => {
  const unknown = row("rumble", {}, { assets: [take] });
  const laid = layout(spec, { spine: [row("b1", { story: "s", number: 1, chapter: "c1", sounds: [{ sound: "rumble", at: 2 }] })], groups: chapters, lanes: { lines: [], sounds: [unknown] } });
  assert.equal(laid.items[0].seconds, 4);
});

test("overlay lane: a PNG or an animated GIF is an overlay too, named by its title", () => {
  const png = { role: "overlay", publicUrl: "https://cdn/media/card.png", mimeType: "image/png", name: "Real fact card" };
  const gif = { role: "overlay", publicUrl: "https://cdn/media/typed.gif", mimeType: "image/gif" };
  assert.deepEqual(coverLaid({ storyAssets: [png] }).covers.overlay.map((c) => [c.name, c.items.length]), [["Real fact card", 5]]);
  assert.equal(coverLaid({ storyAssets: [gif] }).covers.overlay[0].name, "typed.gif");
  const audio = { role: "overlay", publicUrl: "https://cdn/x.mp3", mimeType: "audio/mpeg" };
  assert.deepEqual(coverLaid({ storyAssets: [audio] }).covers.overlay, []); // a sound is no overlay
});

test("aspectOf: the shape is the trailing WxH of the format, width over height; anything else is no shape", () => {
  assert.equal(aspectOf("short-9x16"), 9 / 16);
  assert.equal(aspectOf("wide-16x9"), 16 / 9);
  assert.equal(aspectOf("square-1x1"), 1);
  assert.equal(aspectOf(" portrait-4x5 "), 4 / 5);
  assert.equal(aspectOf("9x16"), 9 / 16);
  for (const nothing of ["", "short", "short-9x", "x9x16y", null, undefined, 3, "short-0x16"]) assert.equal(aspectOf(nothing), null);
});

test("a picture size gives the strip its height and a card the room one frame in the story's shape needs", () => {
  assert.deepEqual(PICTURE_SIZES, { s: 120, m: 180, l: 260 });
  assert.equal(cardMinPx(120, null), 72); // no shape named: the usual minimum
  assert.equal(cardMinPx(120, 9 / 16), 72); // a tall frame of 68 px still fits the minimum
  assert.equal(cardMinPx(260, 9 / 16), 146); // larger, the frame needs more
  assert.equal(cardMinPx(180, 16 / 9), 320); // a wide video needs the most
  assert.equal(minInnerWidth([{ seconds: 4 }, { seconds: 6 }], 10, 146), 365); // the strip floor follows the card floor
});

test("a placed sound with no take is drawn with an estimated width from its text but does not lengthen its beat", () => {
  const spec = { kind: "timeline", entry_type: "story", spine: { entry_type: "beat", of: "story", order: "number", seconds: { hold: "hold_seconds", defaults: { hold: 4, lead: 0, gap: 0, tail: 0 } } }, lanes: [{ id: "sounds", title: "Sounds", entry_type: "sound", of: "story", placed: { field: "sounds", ref: "sound", at: "at" }, audio: "audio", seconds: "duration_seconds", estimate_from: "prompt" }] };
  const row = (slug, dataJson) => ({ id: slug, slug, title: slug, dataJson });
  const laid = layout(spec, { entry: row("s", {}), spine: [row("b1", { number: "1", story: "s", hold_seconds: 2, sounds: [{ sound: "splinter", at: 1 }] })], groups: [], lanes: { sounds: [row("splinter", { prompt: "The sound of wood splintering echoes from deep below and goes on" })] }, via: {}, bands: {} });
  const piece = laid.chapters ? laid.chapters[0].items[0].lanes.sounds[0] : laid.items[0].lanes.sounds[0];
  assert.equal(piece.estimated, true);
  assert.ok(piece.seconds >= 1, "it has a width");
  assert.equal(laid.items[0].seconds, 2, "the beat is still its hold: nothing plays, so the placeholder adds no time");
});

test("review: Keep and Redo show only on an item whose status is one of the waiting ones", () => {
  const review = { ready: ["made"], keep: "approved", redo: "redo" };
  assert.equal(canReview("made", review), true);
  assert.equal(canReview("approved", review), false);
  assert.equal(canReview("", review), false);
  assert.equal(canReview("made", undefined), false);
  assert.equal(canReview("made", null), false);
});

test("transport: |< goes to the start and >| to the end", () => {
  const starts = [0, 4, 9.5, 13];
  assert.equal(jumpTo(starts, 20, 11, "start"), 0);
  assert.equal(jumpTo(starts, 20, 3, "end"), 20);
});

test("transport: >> goes to the next item's start, and to the end after the last", () => {
  const starts = [0, 4, 9.5, 13];
  assert.equal(jumpTo(starts, 20, 0, "next"), 4);
  assert.equal(jumpTo(starts, 20, 4, "next"), 9.5, "at an item's start, the next is the one after it");
  assert.equal(jumpTo(starts, 20, 5, "next"), 9.5);
  assert.equal(jumpTo(starts, 20, 13.01, "next"), 20);
  assert.equal(jumpTo([], 20, 3, "next"), 20);
});

test("transport: << restarts the item you are in, and from near its start goes to the one before", () => {
  const starts = [0, 4, 9.5, 13];
  assert.equal(jumpTo(starts, 20, 6, "back"), 4, "well into an item: its own start");
  assert.equal(jumpTo(starts, 20, 4.5, "back"), 0, "within a second of its start: the one before");
  assert.equal(jumpTo(starts, 20, 4, "back"), 0);
  assert.equal(jumpTo(starts, 20, 0.5, "back"), 0, "at the first item: the very start");
  assert.equal(jumpTo(starts, 20, 19, "back"), 13, "in the last item: its start");
  assert.equal(jumpTo([], 20, 7, "back"), 0);
  assert.equal(jumpTo([4, 4, 9.5], 20, 2, "back"), 0, "before the first start: the very start; duplicates are one");
});

test("the playhead clock reads hours, minutes, seconds and thousandths", () => {
  assert.equal(clockText(0), "0:00:00.000");
  assert.equal(clockText(83.456), "0:01:23.456");
  assert.equal(clockText(3723.5), "1:02:03.500");
  assert.equal(clockText(59.9996), "0:01:00.000", "rounding carries into the next second");
  assert.equal(clockText(-4), "0:00:00.000");
  assert.equal(clockText(Number.NaN), "0:00:00.000");
});

test("a time typed into the clock: seconds, m:s, h:m:s, or h:m:s:thousandths; anything else is refused", () => {
  assert.equal(parseClock("83.5"), 83.5);
  assert.equal(parseClock("1:23.5"), 83.5);
  assert.equal(parseClock("0:01:23.456"), 83.456);
  assert.equal(parseClock(" 1:02:03 "), 3723);
  assert.equal(parseClock("0:01:23:456"), 83.456);
  assert.equal(parseClock("1,5"), 1.5, "a comma is a decimal point");
  for (const bad of ["", "abc", "1:xx", "-3", "1:2:3:4:5", "0:01:23.4:456", "::"]) assert.equal(parseClock(bad), null, bad);
});

test("the clock round-trips: what it shows can be typed back", () => {
  for (const t of [0, 0.001, 12.34, 83.456, 3723.5]) assert.equal(parseClock(clockText(t)), t);
});

test("the playhead is in the item that started last, and the offset is how far into it", () => {
  const starts = [0, 4, 9.5, 13];
  assert.deepEqual(placeIn(starts, 0), { index: 0, offset: 0 });
  assert.deepEqual(placeIn(starts, 6.25), { index: 1, offset: 2.25 });
  assert.deepEqual(placeIn(starts, 9.5), { index: 2, offset: 0 }, "exactly at a start: that item, offset 0");
  assert.deepEqual(placeIn(starts, 99), { index: 3, offset: 86 });
  assert.equal(placeIn([], 3), null);
  assert.equal(placeIn([5], 3), null, "before the first item");
});


import { wavePeaks, wavePolygon, WAVE_POINTS } from "./timeline.ts";

test("a waveform comes from an array of peaks or from audiowaveform JSON, also as text, and a bad value draws nothing", () => {
  assert.deepEqual(wavePeaks([0, 0.5, 1, 0.25]), [0, 0.5, 1, 0.25]);
  assert.deepEqual(wavePeaks([0, 50, 100, 25]), [0, 0.5, 1, 0.25]); // larger numbers are taken relative to the largest
  const file = { version: 2, bits: 8, data: [0, 0, -64, 32, -128, 127, 10, -20] }; // min, max pairs, as audiowaveform writes them
  assert.deepEqual(wavePeaks(file), [0, 0.5, 1, 0.156]); // the larger of each pair's two sides, over the full scale of the bits
  assert.deepEqual(wavePeaks(JSON.stringify(file)), wavePeaks(file));
  for (const bad of [null, undefined, "", "not json", {}, [], [1], { data: [1] }, [1, "a"], { data: [1, "x", 2, 3] }, 5]) assert.equal(wavePeaks(bad), null, String(bad));
});

test("a waveform with more peaks than a block can show keeps the loudest of each group", () => {
  const many = Array.from({ length: 1000 }, (_, i) => (i === 500 ? 1 : 0.1));
  const out = wavePeaks(many, 100);
  assert.equal(out.length, 100);
  assert.equal(Math.max(...out), 1); // the one loud peak is not averaged away
  assert.equal(out[50], 1);
  assert.equal(wavePeaks(many).length, WAVE_POINTS);
});

test("a waveform outline is one polygon: the peaks above the middle line and the same below, a quiet stretch still a line", () => {
  const pts = wavePolygon([1, 0]).split(" ");
  assert.equal(pts.length, 4);
  assert.deepEqual(pts, ["0.50,2.0", "1.50,49.4", "1.50,50.6", "0.50,98.0"]);
});

// ── marks lanes: one choice per item (the camera's move) ──────────────────────────────────────────────────────────────────────────────────────
const marksLane = { id: "camera", title: "Camera", entry_type: "beat", marks: { field: "camera", via: "scene", entry_type: "scene", labels: { "pan-left": "Pan left!" }, icons: { "push-in": "⤢" }, other: { field: "move", label: "Custom move" } } };
const marksSpec = { ...spec, lanes: [...spec.lanes, marksLane] };
const marksLaid = ({ story = {}, sceneData = {}, beatsData = [], lane = marksLane }) => {
  const spine = bedBeats.map((b, i) => ({ ...b, dataJson: { ...b.dataJson, ...(beatsData[i] ?? {}) } }));
  const view = lane === marksLane ? marksSpec : { ...spec, lanes: [...spec.lanes, lane] };
  return layout(view, { entry: row("s", story), spine, groups: chapters, lanes: { lines: [], sounds: [] }, via: { camera: [row("deck", sceneData)] } });
};
const marksOf = (laid) => laid.marks.camera.map((m) => [m.item, m.label, m.from, m.start, m.seconds]);

test("marks lane: an item's own choice wins, then its scene's, then the story's, and an item with none has no mark", () => {
  const laid = marksLaid({ story: { camera: "drift" }, sceneData: { camera: "tilt-up" }, beatsData: [{ camera: "pan-left" }, {}, {}, {}, {}] });
  assert.deepEqual(laid.marks.camera.map((m) => [m.value, m.from]), [
    ["pan-left", "beat"], // b1's own
    ["tilt-up", "scene"], // b2 and b3: the deck's
    ["tilt-up", "scene"],
    ["drift", "story"], // b4's scene is not the deck, b5's does not exist: the story's
    ["drift", "story"],
  ]);
  assert.equal(marksLaid({}).marks.camera.length, 0);
});

test("marks lane: a label says how a value reads, else the value is spaced and capitalised, and an icon is kept", () => {
  const laid = marksLaid({ beatsData: [{ camera: "pan-left" }, { camera: "push-in" }, { camera: "pedestal_down" }] });
  assert.deepEqual(laid.marks.camera.map((m) => [m.label, m.icon]), [["Pan left!", ""], ["Push in", "⤢"], ["Pedestal down", ""]]);
});

test("marks lane: an item's own numbers beat the choice it also holds, and both beat what its scene or the story chose", () => {
  const laid = marksLaid({
    story: { camera: "drift" },
    sceneData: { camera: "tilt-up" },
    beatsData: [{ move: { from: { x: 0.5 }, to: { x: 0.6 } }, camera: "push-in" }, { move: { from: { x: 0.5 }, to: { x: 0.6 } } }, { move: {} }],
  });
  assert.deepEqual(laid.marks.camera.slice(0, 3).map((m) => [m.custom, m.label, m.from]), [
    [true, "Custom move", ""], // it chose a name and wrote numbers: the numbers were written on purpose (a preset's, then changed), so they show
    [true, "Custom move", ""], // numbers alone, over the deck's choice
    [false, "Tilt up", "scene"], // an empty move is no setting
  ]);
});

test("marks lane: each mark spans its item's time, in order", () => {
  const laid = marksLaid({ story: { camera: "drift" } });
  assert.deepEqual(marksOf(laid).map(([item, , , start, seconds]) => [item, start, seconds]), [["id-b1", 0, 4], ["id-b2", 4, 4], ["id-b3", 8, 4], ["id-b4", 12, 4], ["id-b5", 16, 4]]);
});

test("marks lane: a view without one has no marks, and a lane with no via reads the item then the story", () => {
  assert.deepEqual(layout(spec, { spine: bedBeats, groups: chapters, lanes: { lines: [], sounds: [] } }).marks, {});
  const plain = { id: "camera", title: "Camera", entry_type: "beat", marks: { field: "camera" } };
  const laid = marksLaid({ story: { camera: "drift" }, sceneData: { camera: "tilt-up" }, beatsData: [{ camera: "pan-left" }], lane: plain });
  assert.deepEqual(laid.marks.camera.map((m) => m.value).slice(0, 3), ["pan-left", "drift", "drift"]); // no scene tier
});

// ── an item's own hold is the least it lasts ────────────────────────────────────────────────────────────────────────────────────────────────────
test("hold: an item with timed pieces lasts their length plus the silences, or its own hold when that is longer", () => {
  const pieces = [{ seconds: 2.5 }];
  const sec = { hold: "hold_seconds", lead: "lead_seconds", gap: "gap_seconds", tail: "tail_seconds", defaults: { hold: 4, lead: 0.3, gap: 0.25, tail: 0.35 } };
  assert.ok(Math.abs(itemSeconds(row("b", {}), pieces, sec) - 3.15) < 1e-9, "no hold of its own: lead + speech + tail (the view's default hold of 4 is for an empty item)");
  assert.equal(itemSeconds(row("b", { hold_seconds: 8 }), pieces, sec), 8, "its own hold, when longer, is the least it lasts");
  assert.ok(Math.abs(itemSeconds(row("b", { hold_seconds: 2 }), pieces, sec) - 3.15) < 1e-9, "a hold shorter than the speech changes nothing");
  assert.equal(itemSeconds(row("b", { hold_seconds: 8 }), [], sec), 8, "an empty item still holds");
  assert.equal(itemSeconds(row("b", {}), [], sec), 4, "and the view's default when it sets none");
});

// ── a lane's `off` field leaves an entry out ────────────────────────────────────────────────────────────────────────────────────────────────────
const lineLane = { id: "lines", title: "Lines", entry_type: "line", of: "story", in: "beat", order: "order", off: "leave_out", seconds: "duration_seconds", text: "text" };
const lineSpec = { ...spec, lanes: [lineLane] };
const lineBeats = [row("b1", { story: "s", number: 1, chapter: "c1" })];
const linesOf = (lines) => layout(lineSpec, { entry: row("s", {}), spine: lineBeats, groups: chapters, lanes: { lines } });

test("lane off: a line with its box ticked is not timed, drawn or counted, and the beat is as long as the others need", () => {
  const laid = linesOf([
    row("l1", { beat: "b1", order: 1, duration_seconds: 2, text: "one" }),
    row("l2", { beat: "b1", order: 2, duration_seconds: 5, text: "two", leave_out: true }),
    row("l3", { beat: "b1", order: 3, duration_seconds: 1, text: "three" }),
  ]);
  const [item] = laid.items;
  assert.deepEqual(item.lanes.lines.map((p) => p.text), ["one", "three"]);
  assert.equal(item.seconds, 0.3 + 2 + 0.25 + 1 + 0.35); // lead, one, gap, three, tail: the left-out line is not there
});

test("lane off: \"true\" and \"yes\" read as ticked, and false, empty or missing leave the line in", () => {
  const laid = linesOf([
    row("a", { beat: "b1", order: 1, duration_seconds: 1, text: "a", leave_out: "true" }),
    row("b", { beat: "b1", order: 2, duration_seconds: 1, text: "b", leave_out: "yes" }),
    row("c", { beat: "b1", order: 3, duration_seconds: 1, text: "c", leave_out: false }),
    row("d", { beat: "b1", order: 4, duration_seconds: 1, text: "d", leave_out: "" }),
    row("e", { beat: "b1", order: 5, duration_seconds: 1, text: "e" }),
  ]);
  assert.deepEqual(laid.items[0].lanes.lines.map((p) => p.text), ["c", "d", "e"]);
});

test("lane order: lines play by their order number, those with none after them in slug order", () => {
  const laid = linesOf([
    row("l-b", { beat: "b1", duration_seconds: 1, text: "no number b" }),
    row("l-a", { beat: "b1", duration_seconds: 1, text: "no number a" }),
    row("l-z", { beat: "b1", order: 2, duration_seconds: 1, text: "second" }),
    row("l-y", { beat: "b1", order: 1.5, duration_seconds: 1, text: "between" }),
    row("l-x", { beat: "b1", order: 1, duration_seconds: 1, text: "first" }),
  ]);
  assert.deepEqual(laid.items[0].lanes.lines.map((p) => p.text), ["first", "between", "second", "no number a", "no number b"]);
});

// ── marks that run together across a cut ───────────────────────────────────────────────────────────────────────────────────────────────────────
const mergeLane = { ...marksLane, marks: { ...marksLane.marks, merge: ["rocking"] } };
const mergeLaid = (args) => marksLaid({ ...args, lane: mergeLane });

test("marks merge: consecutive items with the same listed choice from the same scene are one block", () => {
  const laid = mergeLaid({ sceneData: { camera: "rocking" } }); // b1, b2, b3 are in the deck
  const [first, ...rest] = laid.marks.camera;
  assert.deepEqual([first.value, first.from, first.start, first.seconds, first.count], ["rocking", "scene", 0, 12, 3]);
  assert.equal(rest.length, 0, "b4 and b5 are not in the deck and choose nothing");
});

test("marks merge: a value not listed stays one chip per item, and so does a choice each item made itself", () => {
  assert.equal(mergeLaid({ sceneData: { camera: "push-in" } }).marks.camera.length, 3);
  const own = mergeLaid({ beatsData: [{ camera: "rocking" }, { camera: "rocking" }] });
  assert.deepEqual(own.marks.camera.map((m) => m.count), [2], "the same listed choice on the next beat itself joins too, since rocking carries on");
});

test("marks merge: two different scenes with the same choice stay two blocks, and a break in time or in the choice splits a block", () => {
  const spine = [row("b1", { story: "s", number: 1, scene: "deck", chapter: "c1" }), row("b2", { story: "s", number: 2, scene: "hold", chapter: "c1" }), row("b3", { story: "s", number: 3, scene: "hold", chapter: "c1" })];
  const laid = layout({ ...spec, lanes: [...spec.lanes, mergeLane] }, { entry: row("s", {}), spine, groups: chapters, lanes: { lines: [], sounds: [] }, via: { camera: [row("deck", { camera: "rocking" }), row("hold", { camera: "rocking" })] } });
  assert.deepEqual(laid.marks.camera.map((m) => [m.source, m.count]), [["deck", 1], ["hold", 2]]);
  const mixed = mergeLaid({ sceneData: { camera: "rocking" }, beatsData: [{}, { camera: "push-in" }, {}] });
  assert.deepEqual(mixed.marks.camera.map((m) => [m.label, m.count]), [["Rocking", 1], ["Push in", 1], ["Rocking", 1]]);
});

test("marks merge: a custom (written out) move is never merged", () => {
  const laid = mergeLaid({ beatsData: [{ move: { from: { x: 0.5 }, to: { x: 0.6 } } }, { move: { from: { x: 0.5 }, to: { x: 0.6 } } }] });
  assert.deepEqual(laid.marks.camera.slice(0, 2).map((m) => [m.custom, m.count]), [[true, 1], [true, 1]]);
});
