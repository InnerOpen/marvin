import assert from "node:assert/strict";
import { test } from "node:test";
import { inOrder, leftOutLine, listLine, nothingLine, previewCards, previewLine, previewProblem, runButton } from "./runList.ts";

test("a run step's button counts what it lists, and reads well when it cannot", () => {
  assert.equal(runButton("Make these ${count} sounds", 3), "Make these 3 sounds");
  assert.equal(runButton("Make these ${count} sounds", null), "Make these sounds");
  assert.equal(runButton("${count} to keep", null), "to keep");
  assert.equal(runButton("Make these sounds (${count})", 3), "Make these sounds (3)");
  assert.equal(runButton("Make these sounds (${count})", null), "Make these sounds");
  assert.equal(runButton("Sounds to make: ${count}", null), "Sounds to make");
  assert.equal(runButton(undefined, 4), "Run");
  assert.equal(runButton("Check the Fountain", 2), "Check the Fountain");
});

test("the line above the list says how many, and the next few of more when it takes some at a time", () => {
  assert.equal(listLine({ count: 3, total: 3, limit: 30 }), "It works on these 3:");
  assert.equal(listLine({ count: 1, total: 1, limit: 30 }), "It works on this one:");
  assert.equal(listLine({ count: 30, total: 45, limit: 30 }), "It works on the next 30 of 45 (30 at a time):");
  assert.equal(listLine({ count: 0, total: 0, limit: 30 }), null);
});

test("what is left out is the package's words with a count, only the ones that count", () => {
  const reasons = [{ label: "music" }, { label: "already have a file" }, { label: "with no description" }];
  assert.equal(leftOutLine(reasons, [1, 3, 0]), "Not included: 1 music, 3 already have a file.");
  assert.equal(leftOutLine(reasons, [0, 0, 0]), null);
  assert.equal(leftOutLine([], []), null);
  assert.equal(leftOutLine(reasons, []), null); // the server gave no counts
});

test("nothing to do says so in the package's words, or plainly", () => {
  assert.equal(nothingLine("No sound is waiting to be made."), "No sound is waiting to be made.");
  assert.equal(nothingLine(undefined), "There is nothing for this step to do right now. Go on to the next step.");
  assert.equal(nothingLine("  ", false), "There is nothing for this step to do right now."); // the last step
});

test("the entries are shown in the workflow's own order, and one that cannot be read is left out", () => {
  const rows = [{ id: "b" }, { id: "a" }, { id: "c" }];
  assert.deepEqual(inOrder(rows, ["a", "x", "b", "c"]).map((r) => r.id), ["a", "b", "c"]);
});

// A template's preview, as POST /api/automations/selection answers it for a workflow that starts with one.
const FIELDS = [
  { key: "medium", label: "Medium (what it is made of)", type: "text" },
  { key: "group", label: "Page", type: "select", options: [{ value: "ornaments", label: "Ornaments" }] },
  { key: "sellOnline", label: "Sell online", type: "boolean" },
  { key: "featured", label: "Featured", type: "boolean" },
  { key: "image", label: "Image", type: "asset" },
];
const owl = { id: "a1", name: "Snowy Owl", filename: "IMG_1.png", url: "/files/owl.png" };
const newRow = { action: "create", title: "Snowy Owl", asset: owl, changes: { title: "Snowy Owl", status: "inbox", fields: { medium: "Acrylic and Ink on Ceramic", group: "ornaments", sellOnline: true, featured: false, image: "a1" } } };
const counts = (rows, errors = 0) => ({ create: rows.filter((r) => r.action === "create").length, fill: rows.filter((r) => r.action === "fill").length, skip: rows.filter((r) => r.action === "skip").length, errors, rows });

test("the line above a template's cards says what the button will make", () => {
  assert.equal(previewLine({ create: 12, fill: 0, skip: 0 }), "It will make these 12:");
  assert.equal(previewLine({ create: 1, fill: 0, skip: 0 }), "It will make this one:");
  assert.equal(previewLine({ create: 10, fill: 2, skip: 1 }), "It will make 10 and fill in 2 that are already there, and leave 1 as it is:");
  assert.equal(previewLine({ create: 0, fill: 1, skip: 2 }), "It will fill in 1 that is already there, and leave 2 as they are:");
  assert.equal(previewLine({ create: 0, fill: 0, skip: 3 }), null); // nothing to do: the step's empty line speaks
});

test("a row with a problem stops the whole run, and the page says so", () => {
  assert.equal(previewProblem({ errors: 0 }), null);
  assert.equal(previewProblem({ errors: 1 }), "One of them has a problem, shown on its card. Nothing is made until that is fixed.");
  assert.equal(previewProblem({ errors: 3 }), "3 of them have a problem, shown on their cards. Nothing is made until that is fixed.");
});

test("a new entry's card shows its picture, its title and the values it gets, in words", () => {
  const [card] = previewCards(counts([newRow]), FIELDS);
  assert.deepEqual(card, {
    href: "/workspace/assets/a1", // not made yet: the card opens the picture
    title: "Snowy Owl",
    picture: "/files/owl.png",
    subtitle: "Medium: Acrylic and Ink on Ceramic · Page: Ornaments · Sell online", // each under its field's name; a choice by its label, a switch that is on by its name, never the picture's id
    pills: ["New"],
  });
  assert.equal(previewCards(counts([newRow]))[0].subtitle, "medium: Acrylic and Ink on Ceramic · group: ornaments · sellOnline"); // without the type's fields: as stored
});

test("a card for an entry that is already there opens it, and one left alone or stopped says why", () => {
  const fill = { action: "fill", entryId: "e1", title: "Ornament 7", asset: owl, treated: { id: "t1", url: "/files/owl-treated.webp" }, changes: { fields: { medium: "Acrylic", image: ["t1"] } }, note: "named after its file" };
  const skip = { action: "skip", entryId: "e2", title: "Ornament 8", asset: owl, changes: {}, note: "it already has everything this template sets" };
  const stopped = { ...newRow, error: "venue: this field is required" };
  const cards = previewCards(counts([fill, skip, stopped], 1), FIELDS);
  assert.deepEqual(cards[0], { href: "/workspace/entries/e1", title: "Ornament 7", picture: "/files/owl-treated.webp", subtitle: "Medium: Acrylic · named after its file", pills: ["Already there: only what is empty is filled"] });
  assert.deepEqual([cards[1].href, cards[1].subtitle, cards[1].pills], ["/workspace/entries/e2", "it already has everything this template sets", ["Already there"]]);
  const trashed = { action: "skip", title: "Blue Jay", asset: owl, note: "the picture is in the Trash" };
  assert.deepEqual(previewCards(counts([trashed]))[0].pills, ["Left out"]); // no entry, and none will be made
  assert.deepEqual([cards[2].subtitle, cards[2].pills], ["venue: this field is required", ["Problem"]]);
});

test("a long run of values is cut, so a card stays a card", () => {
  const long = { ...newRow, changes: { fields: { medium: "x".repeat(300) } } };
  const { subtitle } = previewCards(counts([long]), FIELDS)[0];
  assert.equal(subtitle.length, 200);
  assert.ok(subtitle.endsWith("…"));
});
