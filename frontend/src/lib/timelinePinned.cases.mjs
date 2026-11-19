// Views laid out in order (no `spine.start`, no lane `per`), with rows like their packages make: what `layout` gave for them before dates
// and rows per person existed is kept in timelinePinned.json, and timelinePinned.test.mjs holds layout to it, to the last digit.

const row = (slug, data, extra = {}) => ({ id: `id-${slug}`, slug, title: slug, dataJson: data, ...extra });
const still = { role: "still", publicUrl: "https://cdn/still.png", mimeType: "image/png" };
const take = { role: "audio", publicUrl: "https://cdn/take.mp3", mimeType: "audio/mpeg" };
const music = { role: "audio", publicUrl: "https://cdn/music.mp3", mimeType: "audio/mpeg" };

const story = {
  spec: {
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
      cards: { intro: { title: "intro_title", default_seconds: 2 }, outro: { title: "outro_title", seconds: "outro_seconds" } },
      scene_break: { field: "scene", seconds: "scene_pause" },
      bands: [{ entry_type: "scene", field: "scene" }],
    },
    lanes: [
      { id: "lines", title: "Lines", entry_type: "speech-line", of: "story", in: "beat", order: "number", text: "text", who: "speaker", audio: "audio", seconds: "duration_seconds", estimate_from: "text", status: "status", nudge: "nudge" },
      { id: "sounds", title: "Sounds", entry_type: "sound", placed: { field: "sounds", ref: "sound", at: "at" }, audio: "audio", seconds: "duration_seconds", volume: "volume" },
      { id: "music", title: "Music", entry_type: "sound", bed: { field: "music", item_volume: "music_volume" }, audio: "audio", seconds: "duration_seconds", loop: "loop", volume: "volume" },
    ],
  },
  rows: {
    entry: row("s", { intro_title: "Once", outro_title: "The end", outro_seconds: 3, scene_pause: 0.5, music: "theme" }),
    spine: [
      row("b2", { story: "s", number: 2, chapter: "c1", picture: "A door.", scene: "hall" }),
      row("b1", { story: "s", number: 1, chapter: "c1", picture: "A street.", scene: "street", sounds: [{ sound: "rain", at: 1.5 }, { sound: "nope", at: 0 }] }, { assets: [still] }),
      row("b3", { story: "s", number: 3, chapter: "c2", hold_seconds: 6, scene: "hall", music_volume: 0 }),
      row("b4", { story: "s", number: 4, chapter: "c-missing" }),
    ],
    groups: [row("c2", { number: 2 }), row("c1", { number: 1 })],
    lanes: {
      lines: [
        row("l2", { beat: "b1", number: 2, text: "one two three", speaker: "Ann", nudge: 0.4 }),
        row("l1", { beat: "b1", number: 1, text: "ignored because recorded", speaker: "Bob", duration_seconds: 2 }, { assets: [take] }),
        row("l3", { beat: "b2", number: 1, text: "", speaker: "Ann" }),
        row("l4", { beat: "b3", number: 1, text: "a few words said here", speaker: "Bob" }),
      ],
      sounds: [row("rain", { duration_seconds: 3 })],
      music: [row("theme", { duration_seconds: 30, loop: true }, { assets: [music] })],
    },
    bands: { scene: [row("street", {}), row("hall", {})] },
  },
};

const agenda = {
  spec: {
    kind: "timeline",
    title: "Event agenda",
    unit: "minutes",
    entry_type: "demo-event",
    spine: {
      entry_type: "demo-session",
      of: "event",
      order: "order",
      group: { entry_type: "demo-block", field: "block", order: "order" },
      picture: "picture",
      status: "status",
      seconds: { hold: "minutes", defaults: { hold: 30 } },
    },
    lanes: [
      { id: "people", title: "People", entry_type: "demo-speaker", of: "event", in: "session", order: "order", who: "role", seconds: "minutes" },
      { id: "cues", title: "Room and AV cues", entry_type: "demo-cue", placed: { field: "cues", ref: "cue", at: "at" }, seconds: "minutes" },
    ],
  },
  rows: {
    entry: row("ev", {}),
    spine: [
      row("doors", { event: "ev", block: "am", order: 1, minutes: 30, status: "ready", cues: [{ cue: "music", at: 0 }] }),
      row("keynote", { event: "ev", block: "am", order: 2, minutes: 45, cues: [{ cue: "lights", at: 0 }, { cue: "slides", at: 5 }] }),
      row("panel", { event: "ev", block: "am", order: 3, minutes: 45 }),
      row("lunch", { event: "ev", block: "pm", order: 4, minutes: 60, cues: [{ cue: "music", at: 15 }] }),
      row("closing", { event: "ev", block: "pm", order: 5 }),
    ],
    groups: [row("am", { order: 1 }), row("pm", { order: 2 })],
    lanes: {
      people: [
        row("host", { session: "keynote", order: 1, role: "Host", minutes: 5 }),
        row("speaker", { session: "keynote", order: 2, role: "Speaker", minutes: 35 }),
        row("mod", { session: "panel", order: 1, role: "Moderator" }),
        row("p1", { session: "panel", order: 2, role: "Panelist" }),
        row("closer", { session: "closing", order: 1, role: "Host", minutes: 10 }),
      ],
      cues: [row("music", { minutes: 15 }), row("lights", { minutes: 1 }), row("slides", { minutes: 1 })],
    },
  },
};

const plan = {
  spec: {
    kind: "timeline",
    title: "Content plan",
    unit: "days",
    entry_type: "demo-plan",
    spine: { entry_type: "demo-day", of: "plan", order: "number", status: "status", seconds: { hold: "days", defaults: { hold: 1 } } },
    lanes: [{ id: "posts", title: "Posts", entry_type: "demo-post", of: "plan", in: "day", order: "order", who: "channel", status: "status" }],
  },
  rows: {
    entry: row("plan", {}),
    spine: [1, 2, 3, 4, 5].map((n) => row(`d${n}`, { plan: "plan", number: n, status: n < 3 ? "ready" : "draft", ...(n === 4 ? { days: 2 } : {}) })),
    lanes: {
      posts: [
        row("p1", { day: "d1", order: 1, channel: "LinkedIn", status: "published" }),
        row("p2", { day: "d1", order: 2, channel: "Instagram" }),
        row("p3", { day: "d4", order: 1, channel: "Newsletter" }),
      ],
    },
  },
};

export const PINNED_CASES = { story, agenda, plan };
