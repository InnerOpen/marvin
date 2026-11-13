import assert from "node:assert/strict";
import { test } from "node:test";
import { inOrder, jobLead, leftOutLine, listLine, nothingLine, runButton, shortText } from "./runList.ts";

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

test("a long text is cut at a paragraph or a word, and says there is more", () => {
  assert.deepEqual(shortText("All good.", 50), { lead: "All good.", more: false });
  assert.deepEqual(shortText("Two problems.\n\nLine 3: a speaker in lower case.", 50), { lead: "Two problems.", more: true });
  const long = shortText("word ".repeat(40).trim(), 22);
  assert.equal(long.more, true);
  assert.ok(long.lead.length <= 23 && long.lead.endsWith("…"), long.lead);
  assert.deepEqual(shortText("", 50), { lead: "", more: false });
});

test("a job's words: the start of what it said, or where it failed", () => {
  assert.deepEqual(jobLead("Checked: 2 problems.\n\nLine 3: …", false), { lead: "Checked: 2 problems.", more: true });
  assert.deepEqual(jobLead("Reading the file.\n\nNo story “x” in this workspace.", true), { lead: "No story “x” in this workspace.", more: true });
  assert.deepEqual(jobLead("   ", true), { lead: "", more: false });
});
