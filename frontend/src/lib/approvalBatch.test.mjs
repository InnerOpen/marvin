// Answering several approvals at once (approvalBatch.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { batchGroups, batchItems, batchLabel, combinedEstimate } from "./approvalBatch.ts";

const card = (id, slug, extra = {}) => ({ id, automationSlug: slug, automationName: `Flow ${slug}`, ...extra });

describe("batchGroups", () => {
  test("two or more cards of one workflow go together; a lone card does not", () => {
    const groups = batchGroups([card("a", "sound"), card("b", "still"), card("c", "sound"), card("d", "sound")]);
    assert.deepEqual(groups, [{ slug: "sound", name: "Flow sound", ids: ["a", "c", "d"], choices: [] }]);
  });
  test("cards offering different choices are not answered together", () => {
    assert.deepEqual(
      batchGroups([card("a", "keep", { choices: ["Keep", "Redo"] }), card("b", "keep", { choices: ["Yes", "No"] })]),
      [],
    );
    const same = batchGroups([
      card("a", "keep", { choices: ["Keep", "Redo"] }),
      card("b", "keep", { choices: ["Keep", "Redo"] }),
    ]);
    assert.deepEqual(same[0].choices, ["Keep", "Redo"]);
  });
});

describe("combinedEstimate", () => {
  const est = (amount, unit) => ({ text: "x", total: { amount, unit } });
  test("adds up what shares a unit and says how many have no estimate", () => {
    const cards = [
      card("a", "s", { estimate: est(400, "ElevenLabs credits") }),
      card("b", "s", { estimate: est(150, "ElevenLabs credits") }),
    ];
    assert.equal(combinedEstimate(cards), "About 550 ElevenLabs credits in all");
    const withUnknown = [...cards, card("c", "s", { estimate: { text: "cost unknown" } })];
    assert.equal(combinedEstimate(withUnknown), "About 550 ElevenLabs credits in all; 1 of 3 cost unknown");
    assert.equal(
      combinedEstimate([
        card("a", "s", { estimate: est(0.05, "USD") }),
        card("b", "s", { estimate: est(0.06, "USD") }),
      ]),
      "About $0.11 in all",
    );
  });
  test("nothing paid: no line", () => {
    assert.equal(combinedEstimate([card("a", "s")]), null);
  });
});

describe("batchLabel and batchItems", () => {
  test("all, or only the picked ones", () => {
    assert.equal(batchLabel("Approve", 20, 20), "Approve all 20");
    assert.equal(batchLabel("Keep", 3, 20), "Keep these 3");
  });
  test("each picked card carries the batch's choice and only its own changed boxes", () => {
    const changed = (id) => (id === "b" ? { prompt: "Sliced thin" } : {});
    assert.deepEqual(batchItems(["a", "b"], "Keep", changed), [
      { id: "a", choice: "Keep" },
      { id: "b", choice: "Keep", fields: { prompt: "Sliced thin" } },
    ]);
    assert.deepEqual(batchItems(["a"], null, changed), [{ id: "a" }]);
  });
});
