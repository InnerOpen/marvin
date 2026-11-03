// Workflow conditions in people's words (conditions.ts). Run with `npm test` — plain `node --test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  conditionValueText,
  conditionValueToSave,
  describeCondition,
  describeConditions,
  fieldGroups,
  fieldLabel,
  needsValue,
  valueChoices,
} from "./conditions.ts";

const CATALOG = [
  { field: "event.event_type", label: "Event type" },
  { field: "entry.entry_type", label: "Entry type" },
  { field: "entry.status", label: "Status" },
  { field: "event.after.status", label: "Status changed to…" },
  { field: "entry.data.", label: "Type field" },
];
const INPUTS = [{ name: "style", label: "Style", type: "choice", options: ["haiku", "limerick"] }];
const STEPS = [{ id: "ok", label: "Wait for approval", keys: ["decision"] }, { id: "mail", label: "Email a member", keys: ["sent"] }];
const GROUPS = fieldGroups(CATALOG, { inputs: INPUTS, steps: STEPS });
const CTX = { entryTypes: [{ value: "recipe", label: "Recipe" }], inputs: INPUTS };

describe("the fields a condition can read", () => {
  test("are grouped: the entry, what changed, the event, run inputs, earlier steps", () => {
    assert.deepEqual(GROUPS.map((g) => g.label), ["The entry", "What changed", "The event", "Run inputs", "Earlier steps"]);
    assert.deepEqual(GROUPS.at(-1).options.map((o) => o.field), ["steps.ok.output.decision", "steps.mail.output.sent"]);
  });

  test("a start such as a type's field reads as its label with the rest", () => {
    assert.equal(fieldLabel("entry.data.price", GROUPS), "Type field “price”");
    assert.equal(fieldLabel("event.payload.object", GROUPS), "event › payload › object");
  });
});

describe("the values a field takes", () => {
  test("are offered where Marvin knows them", () => {
    assert.deepEqual(valueChoices("entry.entry_type", CTX), [{ value: "recipe", label: "Recipe" }]);
    assert.equal(valueChoices("entry.status")[0].value, "draft");
    assert.deepEqual(valueChoices("event.bucket").map((c) => c.value), ["keyword", "lead", "question", "feedback", "support", "noise"]);
    assert.equal(valueChoices("steps.ok.output.decision")[0].value, "approved");
    assert.deepEqual(valueChoices("steps.mail.output.sent").map((c) => c.value), ["true", "false"]);
    assert.deepEqual(valueChoices("input.style", CTX).map((c) => c.value), ["haiku", "limerick"]);
  });

  test("and left free where it doesn't", () => {
    assert.equal(valueChoices("entry.title"), null);
    assert.equal(valueChoices("entry.entry_type", {}), null);  // the types not loaded yet: type it
  });

  test("exists and changed need no value", () => {
    assert.equal(needsValue("exists"), false);
    assert.equal(needsValue("changed"), false);
    assert.equal(needsValue("eq"), true);
  });
});

describe("a condition read back", () => {
  test("names the field, the comparison and the value in words", () => {
    assert.equal(describeCondition({ field: "entry.entry_type", op: "eq", value: "recipe" }, GROUPS, CTX), "Entry type is Recipe");
    assert.equal(describeCondition({ field: "steps.ok.output.decision", op: "eq", value: "approved" }, GROUPS, CTX), "Wait for approval (ok) → decision is Approved");
    assert.equal(describeCondition({ field: "entry.title", op: "exists" }, GROUPS, CTX), "entry › title is set");
    assert.equal(describeCondition({ field: "input.style", op: "in", value: "haiku, limerick" }, GROUPS, CTX), "Style is one of haiku, limerick");
    assert.equal(describeCondition({ field: "entry.title", op: "longer_than", value: "60" }, GROUPS, CTX), "entry › title is longer than “60” characters");
  });

  test("several join with and; a grouped one is named", () => {
    const list = [{ field: "entry.status", op: "eq", value: "published" }, { field: "entry.entry_type", op: "neq", value: "recipe" }];
    assert.equal(describeConditions(list, GROUPS, CTX), "Status is Published and Entry type is not Recipe");
    assert.equal(describeConditions({ any: [] }, GROUPS, CTX), "a grouped condition (see JSON)");
    assert.equal(describeConditions(null, GROUPS, CTX), "");
  });
});

describe("a condition's value in the builder's text box", () => {
  test("text shows as itself, and numbers, booleans, null and lists as readable text", () => {
    assert.equal(conditionValueText("draft"), "draft");
    assert.equal(conditionValueText(50), "50");
    assert.equal(conditionValueText(0), "0");
    assert.equal(conditionValueText(true), "true");
    assert.equal(conditionValueText(false), "false");
    assert.equal(conditionValueText(null), "");
    assert.equal(conditionValueText(undefined), "");
    assert.equal(conditionValueText(["a", "b"]), "a, b");
    assert.equal(conditionValueText([1, 2]), "1, 2");
  });

  test("a list holding a comma, or an object, shows as JSON so nothing reads wrong", () => {
    assert.equal(conditionValueText(["a,b", "c"]), '["a,b","c"]');
    assert.equal(conditionValueText({ min: 1 }), '{"min":1}');
  });

  test("an untouched box saves the original value, so a round trip keeps its type", () => {
    for (const original of [50, 0, true, false, null, ["a", "b"], ["a,b"], { min: 1 }]) {
      assert.deepEqual(conditionValueToSave(conditionValueText(original), original), original);
    }
  });

  test("an edited box saves what was typed, as text", () => {
    assert.equal(conditionValueToSave("60", 50), "60");
    assert.equal(conditionValueToSave("a, b, c", ["a", "b"]), "a, b, c");
    assert.equal(conditionValueToSave("", 50), "");
  });

  test("a text original, or none, saves the typed text", () => {
    assert.equal(conditionValueToSave("draft", "draft"), "draft");
    assert.equal(conditionValueToSave("x"), "x");
  });
});
