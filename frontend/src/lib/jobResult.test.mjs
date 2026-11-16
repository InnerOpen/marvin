import assert from "node:assert/strict";
import { test } from "node:test";
import { jobResult, listsOf, segs, statsOf, toneOf } from "./jobResult.ts";

// Texts in the shapes the Studio worker writes (render/storyrender: validate.report, fountain.report, the import's split_plan and
// sheet_log), with made-up names.
const CHECK = `The import will go ahead: nothing stops it. 6 lines are worth a look (below).
Checked the Fountain (812 lines).
It reads as 3 chapters, 120 beats, 140 spoken lines, 9 characters and 14 places.
Bringing it in will take about 2 minutes (290 records at about 2.4 a second).

Worth a look (6): the import goes ahead with these; change one only if it is not what you meant.
  speaker names shortened to one word: Old Ada → Ada, Dr. Moss → Dr-moss, The Clerk → Clerk. See the import's preview.
  line 1: the title page has no Premise:, which the pictures read. Add a \`Premise:\` line (or fill the story's Premise field in Marvin).
  line 1: the title page has no Setting:, which the pictures read. Add a \`Setting:\` line (or fill the story's Setting field in Marvin).
  line 17: \`A BELL.\` stands alone in capitals, so it is read as action, not as a speaker (a speaker's name needs their words on the line under it). If it is a sound, write it as a note (\`[[Sound: a bell]]\`); if it is action, start it with ! (\`!A BELL.\`) to say so.
  line 75: \`ON THE PIER\` stands alone in capitals, so it is read as action, not as a speaker (a speaker's name needs their words on the line under it). If it is a sound, write it as a note (\`[[Sound: on the pier]]\`); if it is action, start it with ! (\`!ON THE PIER\`) to say so.
  line 254: \`> _THE LAMP_ <\` is centered text standing alone, so it is a plain card: a beat of its own that shows the words on the story's card colour, with no picture made for it. Nothing if a card is what you want; to have the words in a picture instead, write them as an action line (or \`SUPER: …\` for a title over the picture).

Checked 2026-11-16 17:16 UTC.`;

const STOPS = `The import will stop: 2 mistakes to fix first (under “Fix before importing”). The other 1 is worth a look.
Checked the Fountain (40 lines).
It reads as 1 chapter, 8 beats, 6 spoken lines, 2 characters and 2 places.
Bringing it in will take about 1 minute (20 records at about 2.4 a second).

Fix before importing (2): the import stops until these are fixed.
  line 12: a note is opened with [[ and never closed, so it is ignored (a note ends at its ]] or at a blank line). Close it with ]] on the same paragraph.
  line 30: \`CUT TO\` has no colon, so it is read as a line of the story, not a transition. Write \`CUT TO:\`.

Worth a look (1): the import goes ahead with these; change one only if it is not what you meant.
  line 2: \`ada\` stands alone above a line: if it is a speaker, it is read as action because it is not in capitals. Write it \`ADA\`, or join it to the sentence.

Checked 2026-11-16 09:02 UTC.`;

const PLAN = `2026-11-16 18:12 UTC · import, chapters all

Done: made 3 chapters, 120 beats, 140 spoken lines, 4 scenes and 2 sounds to fill in.

3 chapters, 12 scenes, about 30 pages, 120 beats, 140 spoken lines.

  1  Opening                                       scenes 1–4  ·  ~10 pp  ·  40 beats  ·  50 lines  ·  Ada, Clerk, Dr-moss
  2  Int. Lamp Room - Night                        scenes 5–9  ·  ~12 pp  ·  50 beats  ·  60 lines  ·  Ada, Dr-moss, Pell, Rook, Sable, Tam
  3  Ext. Pier - Day [flashback                    scenes 10–12  ·  ~8 pp  ·  30 beats  ·  0 lines  ·  no speech (not in this run)

Speakers: Old Ada → Ada; Dr. Moss → Dr-moss; The Clerk → Clerk; Pell → Pell

Check:
  - line 17: \`A BELL.\` stands alone in capitals, so it is read as action, not as a speaker (a speaker's name needs their words on the line under it): if it is a sound, write it as a note (\`[[Sound: a bell]]\`); if it is action, start it with ! (\`!A BELL.\`) to say so
  - line 75: \`ON THE PIER\` stands alone in capitals, so it is read as action, not as a speaker (a speaker's name needs their words on the line under it): if it is a sound, write it as a note (\`[[Sound: on the pier]]\`); if it is action, start it with ! (\`!ON THE PIER\`) to say so
  - and 26 more like these
  - speaker names shortened to one word: Old Ada → Ada, Dr. Moss → Dr-moss, The Clerk → Clerk

made 120 beats and 140 spoken lines (each of 3 chapters holds its own part of the Fountain text) and 3 chapters (0 already there), 0 characters (), 4 scenes (Lamp Room, Pier, Stair (Upper), Cellar) and 2 sounds to fill in (Pier ambience, Cellar ambience). 0 beats and 0 lines were already there (the rest left alone).

The story still lacks: no Premise: one or two sentences saying what the story is about (a \`Premise:\` line on the title page, or the Premise field).

Setting taken from the screenplay: “Lamp Room (interior), Night”.`;

const SHEET_LOG = `2026-11-14 10:01 UTC · add · from the Fountain · +120 beats, +140 lines, +3 chapters
2026-11-16 18:12 UTC · refresh · from the Fountain (chapters 2) · +4 beats, +2 lines · 3 updated · trashed: beat-2-07, beat-2-08`;

/** Every non-blank line of the text, in order, is in exactly one block: nothing lost, doubled or moved. */
function assertKeepsEveryLine(text) {
  const { blocks } = jobResult(text);
  const said = blocks.flatMap((b) => b.src.split("\n")).filter((l) => l.trim());
  const lines = text
    .trim()
    .split("\n")
    .map((l) => l.replace(/\s+$/, ""))
    .filter((l) => l.trim());
  assert.deepEqual(said, lines);
}

test("every line of a job's text lands in one block, in order", () => {
  for (const text of [
    CHECK,
    STOPS,
    PLAN,
    SHEET_LOG,
    "just one line",
    "a\n\nb\n  c\n\n- d\n# e",
    "Done.\n\nWorth a look (1): x.\nnot indented",
  ])
    assertKeepsEveryLine(text);
});

test("text it does not know is kept as written, and says nothing was laid out", () => {
  const text = "# Notes\nsome words\n\n  indented\n\n| a | b |";
  const r = jobResult(text);
  assert.equal(r.formatted, false);
  assert.deepEqual(
    r.blocks.map((b) => b.kind),
    ["text"],
  );
  assert.equal(r.blocks[0].text, text);
  assert.deepEqual(jobResult("  ").blocks, []);
});

test("a check report: its verdict, counts, time, findings grouped by kind, and when", () => {
  const r = jobResult(CHECK);
  assert.equal(r.formatted, true);
  assert.deepEqual(
    r.blocks.map((b) => b.kind),
    ["verdict", "stats", "note", "findings", "note"],
  );
  const [verdict, stats, , findings] = r.blocks;
  assert.equal(verdict.tone, "good");
  assert.deepEqual(verdict.sub, [[{ text: "Checked the Fountain (812 lines)." }]]);
  assert.deepEqual(
    stats.items.map((i) => `${i.value} ${i.label}`),
    ["3 chapters", "120 beats", "140 spoken lines", "9 characters", "14 places"],
  );
  assert.equal(findings.title, "Worth a look");
  assert.equal(findings.count, 6);
  assert.equal(findings.tone, "warn");
  const groups = findings.groups;
  assert.deepEqual(
    groups.map((g) => [g.title, g.count]),
    [
      ["Speaker names shortened to one word", 3],
      ["The title page has no …", 2],
      ["Stands alone in capitals", 2],
      ["Centered text standing alone", 1],
    ],
  );
  assert.deepEqual(groups[0].pairs, [
    ["Old Ada", "Ada"],
    ["Dr. Moss", "Dr-moss"],
    ["The Clerk", "Clerk"],
  ]);
  assert.deepEqual(groups[0].after, ["See the import's preview."]);
  // Rows of one kind say their words once; each row keeps its line and what it quotes.
  assert.ok(groups[2].why.some((s) => s.text.includes("stands alone in capitals")));
  assert.deepEqual(
    groups[2].rows.map((r) => [r.line, r.quotes]),
    [
      [17, ["A BELL.", "[[Sound: a bell]]", "!A BELL."]],
      [75, ["ON THE PIER", "[[Sound: on the pier]]", "!ON THE PIER"]],
    ],
  );
  // Rows that differ in their own words keep them all.
  assert.equal(groups[1].why, null);
  assert.equal(groups[3].why, null);
});

test("what stops an import is its own section, and reads as bad", () => {
  const r = jobResult(STOPS);
  assert.equal(r.blocks[0].tone, "bad");
  const sections = r.blocks.filter((b) => b.kind === "findings");
  assert.deepEqual(
    sections.map((s) => [s.title, s.count, s.tone]),
    [
      ["Fix before importing", 2, "bad"],
      ["Worth a look", 1, "warn"],
    ],
  );
  assert.equal(sections[0].groups[0].rows[0].line, 12);
});

test("a chapter plan: its stamp, verdict, counts, table, speakers, check, what it made and what the story lacks", () => {
  const r = jobResult(PLAN);
  assert.deepEqual(
    r.blocks.map((b) => b.kind),
    ["stamp", "verdict", "stats", "table", "pairs", "findings", "lists", "lack", "note"],
  );
  const [stamp, , stats, table, pairs, check, lists, lack, last] = r.blocks;
  assert.deepEqual([stamp.when, stamp.parts], ["2026-11-16 18:12 UTC", ["import, chapters all"]]);
  assert.deepEqual(
    stats.items.map((i) => i.value),
    ["3", "12", "~30", "120", "140"],
  );
  assert.deepEqual(table.columns, ["Scenes", "Pages", "Beats", "Lines"]);
  assert.equal(table.listColumn, "Who speaks");
  assert.deepEqual(table.rows[0], {
    n: "1",
    name: "Opening",
    cells: ["1–4", "~10", "40", "50"],
    list: ["Ada", "Clerk", "Dr-moss"],
    note: null,
  });
  assert.deepEqual(
    [table.rows[2].name, table.rows[2].list, table.rows[2].note],
    ["Ext. Pier - Day [flashback", ["no speech"], "not in this run"],
  );
  assert.equal(pairs.title, "Speakers");
  assert.equal(pairs.pairs.length, 4);
  assert.deepEqual(
    check.groups.map((g) => [g.title, g.count, g.after]),
    [
      ["Stands alone in capitals", 28, ["and 26 more like these"]],
      ["Speaker names shortened to one word", 3, []],
    ],
  );
  assert.deepEqual(lists.lists, [
    { label: "4 scenes", items: ["Lamp Room", "Pier", "Stair (Upper)", "Cellar"] },
    { label: "2 sounds to fill in", items: ["Pier ambience", "Cellar ambience"] },
  ]);
  assert.ok(lack.text.some((s) => s.code && s.text === "Premise:"));
  assert.deepEqual(last.text, [{ text: "Setting taken from the screenplay: “Lamp Room (interior), Night”." }]);
});

test("a preview says so plainly; nothing new is good news", () => {
  assert.equal(toneOf("Preview only: nothing was made. It would make 3 chapters and 120 beats."), "plain");
  assert.equal(toneOf("Nothing new: 120 beats and 140 lines were already there, so nothing was made."), "good");
  assert.equal(
    toneOf("Skipped: job-12 already had my-story (started 2026-11-16 18:00 UTC, still running); nothing was done."),
    "warn",
  );
  assert.equal(toneOf("Failed: no story “x” in this workspace."), "bad");
  assert.equal(toneOf("Bob.wav → bob.mp3, 3.2 s."), "plain");
});

test("a sheet log: the newest run first, with what it added as tiles, and the rest under Earlier", () => {
  const r = jobResult(SHEET_LOG);
  assert.equal(r.blocks.length, 1);
  const [log] = r.blocks;
  assert.equal(log.kind, "history");
  assert.deepEqual(log.latest, {
    kind: "import",
    when: "2026-11-16 18:12 UTC",
    title: "Refreshed chapter 2",
    tiles: [
      { value: "4", label: "beats" },
      { value: "2", label: "lines" },
    ],
    notes: ["3 updated", "trashed: beat-2-07, beat-2-08"],
  });
  assert.deepEqual(
    log.earlier.map((e) => [e.title, e.when]),
    [["Brought in all chapters", "2026-11-14 10:01 UTC"]],
  );
});

test("a sheet log with a clear in it: the import just run is the result, never the older numbers or the clear's", () => {
  // Jared's story, 2026-11-16: an import of everything, a clear, then an import of chapter 1 only.
  const text =
    "2026-11-16 18:12 UTC · add · from the Fountain · +599 beats, +768 lines, +14 chapters\nclear · permanent · 768 speech lines, 599 beats, 146 scenes, 48 characters, 21 sounds and 14 chapters\n2026-11-16 21:45 UTC · add · from the Fountain (chapters  1) · +53 beats, +53 lines, +1 chapters";
  const r = jobResult(text);
  assert.deepEqual(
    r.blocks.map((b) => b.kind),
    ["history"],
  );
  const [log] = r.blocks;
  assert.deepEqual(log.latest, {
    kind: "import",
    when: "2026-11-16 21:45 UTC",
    title: "Brought in chapter 1",
    tiles: [
      { value: "53", label: "beats" },
      { value: "53", label: "lines" },
      { value: "1", label: "chapter" },
    ],
    notes: [],
  });
  assert.deepEqual(log.earlier, [
    {
      kind: "clear",
      when: null,
      title: "Cleared (deleted for good)",
      tiles: [],
      notes: ["768 speech lines, 599 beats, 146 scenes, 48 characters, 21 sounds and 14 chapters"],
    },
    {
      kind: "import",
      when: "2026-11-16 18:12 UTC",
      title: "Brought in all chapters",
      tiles: [
        { value: "599", label: "beats" },
        { value: "768", label: "lines" },
        { value: "14", label: "chapters" },
      ],
      notes: [],
    },
  ]);
  assert.ok(!r.blocks.some((b) => b.kind === "stats"));
});

test("a sheet log line it does not know is kept as written; a clear can be the newest", () => {
  const r = jobResult("clear · trash · 3 beats and 2 lines\nsomething an older version wrote");
  const [log] = r.blocks;
  assert.equal(log.kind, "history");
  assert.deepEqual([log.latest.kind, log.latest.title], ["text", "something an older version wrote"]);
  assert.deepEqual([log.earlier[0].title, log.earlier[0].tiles], ["Cleared (moved to the Trash)", []]);
  const two = jobResult(
    "2026-11-16 21:45 UTC · refresh · from the Fountain (chapters 1–3) · +2 beats\nclear · permanent · 9 beats",
  );
  assert.deepEqual([two.blocks[0].latest.title, two.blocks[0].latest.tiles], ["Cleared (deleted for good)", []]);
  assert.equal(two.blocks[0].earlier[0].title, "Refreshed chapters 1–3");
  // Prose with one dated line in it is not a log.
  assert.equal(
    jobResult("Some words.\n2026-11-16 21:45 UTC · add · from the Fountain · +2 beats\nMore words.\nAnd more.")
      .blocks[0].kind,
    "verdict",
  );
});

test("a failed job's reason is its last paragraph, as a bad verdict", () => {
  const r = jobResult("Reading the story.\n\nWriting beats.\n\nno story “x” in this workspace", { failed: true });
  assert.equal(r.blocks.length, 1);
  assert.equal(r.blocks[0].tone, "bad");
  assert.deepEqual(r.blocks[0].text, [{ text: "no story “x” in this workspace" }]);
  assert.equal(r.formatted, true);
});

test("a skipped job and a one-line log read as a verdict", () => {
  const r = jobResult(
    "Skipped: job-12 already had my-story (started 2026-11-16 18:00 UTC, still running); nothing was done.\nThat job was asked for before this one.",
  );
  assert.deepEqual(
    r.blocks.map((b) => [b.kind, b.tone]),
    [["verdict", "warn"]],
  );
  assert.equal(r.blocks[0].sub.length, 1);
});

test("a lone plain sentence is the text as written, with no second showing", () => {
  const r = jobResult("“take-01.wav” is already mp3: nothing to do.");
  assert.deepEqual(
    r.blocks.map((b) => [b.kind, b.tone]),
    [["verdict", "plain"]],
  );
  assert.equal(r.formatted, false);
});

test("counts are read only from a line that is a list of counts", () => {
  assert.deepEqual(statsOf("It reads as 1 chapter, 8 beats and 2 places."), [
    { value: "1", label: "chapter" },
    { value: "8", label: "beats" },
    { value: "2", label: "places" },
  ]);
  assert.equal(statsOf("Bringing it in will take about 2 minutes (290 records at about 2.4 a second)."), null);
  assert.equal(statsOf("3 chapters and 4 beats."), null);
  assert.equal(statsOf("Done: made 3 chapters, 120 beats and 4 scenes."), null);
});

test("a list in brackets is taken only when it holds as many names as its count, and brackets close", () => {
  assert.equal(listsOf("made 3 beats (each of 2 chapters holds its part) and 2 chapters (0 already there)"), null);
  assert.equal(listsOf("2 scenes (Pier, Cellar"), null);
  assert.deepEqual(listsOf("and 2 scenes (Pier (west), Cellar)."), {
    text: "and 2 scenes.",
    lists: [{ label: "2 scenes", items: ["Pier (west)", "Cellar"] }],
  });
});

test("quoted bits are code", () => {
  assert.deepEqual(segs("write `A` or `B`."), [
    { text: "write " },
    { text: "A", code: true },
    { text: " or " },
    { text: "B", code: true },
    { text: "." },
  ]);
  assert.deepEqual(segs("no quotes"), [{ text: "no quotes" }]);
});

test("a quote every row of a kind has alike is said once, with the kind's words", () => {
  const text =
    "Done.\n\nWorth a look (2): x.\n  line 3: `> A <` is centered text standing alone, or `SUPER: …` over it.\n  line 9: `> B <` is centered text standing alone, or `SUPER: …` over it.";
  const [group] = jobResult(text).blocks[1].groups;
  assert.deepEqual(
    group.rows.map((r) => r.quotes),
    [["> A <"], ["> B <"]],
  );
  assert.deepEqual(group.why, [
    { text: "…" },
    { text: " is centered text standing alone, or " },
    { text: "SUPER: …", code: true },
    { text: " over it." },
  ]);
});
