// Workflow conditions in people's words (conditions.ts). Run with `npm test` — plain `node --test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { describeCondition, describeConditions, fieldGroups, fieldLabel, needsValue, valueChoices } from "./conditions.ts";

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
