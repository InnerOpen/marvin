import assert from "node:assert/strict";
import test from "node:test";

import { deciderLabel, decisionLabel, firstLine } from "./approvalHistory.ts";

test("a settled approval reads as its decision, with the choice when one was picked", () => {
  assert.equal(decisionLabel("approved"), "Approved");
  assert.equal(decisionLabel("approved", "Dusk"), "Approved: Dusk");
  assert.equal(decisionLabel("denied", "Dusk"), "Denied"); // a denial carries no choice
  assert.equal(decisionLabel("expired"), "Expired");
  assert.equal(decisionLabel("stale"), "Stale: the entry changed");
  assert.equal(decisionLabel("something-new"), "something-new");
});

test("an approval nobody decided names no one", () => {
  assert.equal(deciderLabel("Jared "), "Jared");
  assert.equal(deciderLabel(null), "no one");
  assert.equal(deciderLabel("  "), "no one");
});

test("a row shows a question's first line", () => {
  assert.equal(firstLine("Record this?\n\nA long script follows"), "Record this?");
  assert.equal(firstLine("  One line  "), "One line");
  assert.equal(firstLine(""), "");
});
