// The workflow editor's JSON view (workflowJson.ts). Run with `npm test` — plain `node --test`, which strips
// the .ts types itself. Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { definitionDifferences, freeSlug, parseWorkflowJson, workflowDocument } from "./workflowJson.ts";

const DEFINITION = {
  trigger: { type: "event", event: "entry_published" },
  conditions: [{ field: "entry.entry_type", op: "eq", value: "post" }],
  actions: [{ kind: "entry", op: "archive" }],
};

const parse = (value) => parseWorkflowJson(typeof value === "string" ? value : JSON.stringify(value));

describe("parseWorkflowJson", () => {
  test("a bare definition goes in as-is, with no name", () => {
    assert.deepEqual(parse(DEFINITION), { ok: true, definition: DEFINITION, ignored: [] });
  });

  test("a whole workflow document fills the name and slug and keeps only the definition", () => {
    const result = parse({ name: "  Archive posts ", slug: "archive-posts", definition: DEFINITION });
    assert.deepEqual(result, {
      ok: true,
      definition: DEFINITION,
      name: "Archive posts",
      slug: "archive-posts",
      ignored: [],
    });
  });

  test("never takes enabled (or ids, or other read-only keys) from the JSON", () => {
    const result = parse({ id: "x", groupId: "y", name: "A", enabled: true, description: "d", definition: DEFINITION });
    assert.equal(result.ok, true);
    assert.deepEqual(result.ignored, ["id", "groupId", "enabled", "description"]);
    assert.equal("enabled" in result, false);
    assert.deepEqual(result.definition, DEFINITION);
  });

  test("a name written into a bare definition is the workflow's name, not part of the definition", () => {
    const result = parse({ name: "Archive posts", enabled: true, ...DEFINITION });
    assert.equal(result.ok, true);
    assert.equal(result.name, "Archive posts");
    assert.deepEqual(result.definition, DEFINITION);
    assert.deepEqual(result.ignored, ["enabled"]);
  });

  test("a document without a name is fine — the Name field stays as it is", () => {
    const result = parse({ definition: DEFINITION });
    assert.equal(result.ok, true);
    assert.equal(result.name, undefined);
  });

  test("broken JSON says why", () => {
    const result = parse('{"trigger": ');
    assert.equal(result.ok, false);
    assert.match(result.error, /^Invalid JSON: /);
  });

  test("an empty box, a non-object, or an object that isn't a workflow shows the accepted shapes", () => {
    for (const text of ["", "  ", "[]", '"hi"', '{"foo": 1}']) {
      const result = parse(text);
      assert.equal(result.ok, false, text);
      assert.match(result.error, /"name": "…", "definition"/, text);
    }
  });

  test("rejects the obvious type mistakes", () => {
    assert.match(parse({ name: 1, definition: DEFINITION }).error, /"name" must be a string/);
    assert.match(parse({ name: "A", definition: [] }).error, /"definition" must be an object/);
    assert.match(parse({ trigger: "entry_published", actions: [] }).error, /"trigger" must be an object/);
    assert.match(parse({ trigger: {}, actions: {} }).error, /"actions" must be a list/);
    assert.match(parse({ trigger: {}, actions: ["publish"] }).error, /Each step/);
    assert.match(parse({ trigger: {}, actions: [], conditions: "x" }).error, /"conditions" must be a list/);
  });

  test("accepts a single condition group (the API does)", () => {
    const result = parse({ ...DEFINITION, conditions: { any: [] } });
    assert.equal(result.ok, true);
  });

  test("what Copy JSON gives back pastes straight in, slug included", () => {
    const doc = workflowDocument({ id: "1", name: "Archive posts", slug: "archive-old", enabled: true, definition: DEFINITION });
    assert.deepEqual(doc, { name: "Archive posts", slug: "archive-old", definition: DEFINITION });
    const pasted = parse(doc);
    assert.equal(pasted.ok, true);
    assert.equal(pasted.slug, "archive-old"); // a renamed workflow keeps its slug, so chains to it survive the copy
    assert.deepEqual(workflowDocument({ name: "No slug yet", definition: DEFINITION }), { name: "No slug yet", definition: DEFINITION });
  });

  test("a slug this workspace already uses gets the next free number", () => {
    assert.equal(freeSlug("archive-old", ["other"]), "archive-old");
    assert.equal(freeSlug("archive-old", ["archive-old"]), "archive-old-2");
    assert.equal(freeSlug("archive-old", ["archive-old", "archive-old-2", "archive-old-3"]), "archive-old-4");
  });
});

describe("definitionDifferences", () => {
  test("identical definitions match", () => {
    assert.deepEqual(definitionDifferences(DEFINITION, structuredClone(DEFINITION)), []);
  });

  test("defaults the builder writes match a missing key", () => {
    const original = { trigger: { type: "manual" }, actions: [{ kind: "operation", op: "generate_summary" }] };
    const rebuilt = {
      trigger: { type: "manual" },
      conditions: [],
      actions: [{ kind: "operation", op: "generate_summary", write_back: false }],
    };
    assert.deepEqual(definitionDifferences(original, rebuilt), []);
  });

  test("names what the builder dropped or changed", () => {
    const original = {
      trigger: { type: "schedule", schedule_type: "cron", schedule_config: { cron: "0 9 * * *" } },
      conditions: [{ field: "entry.data.count", op: "eq", value: 3 }],
      actions: [{ kind: "entry", op: "archive" }, { kind: "custom" }],
    };
    const rebuilt = {
      trigger: { type: "schedule", schedule_type: "interval", schedule_config: { interval_seconds: 86400 } },
      conditions: [{ field: "entry.data.count", op: "eq", value: "3" }],
      actions: [{ kind: "entry", op: "archive" }],
    };
    assert.deepEqual(definitionDifferences(original, rebuilt), [
      "trigger.schedule_type",
      "trigger.schedule_config.cron",
      "trigger.schedule_config.interval_seconds",
      "conditions[0].value",
      "actions[1]",
    ]);
  });

  test("a single condition group isn't a list of conditions", () => {
    assert.deepEqual(definitionDifferences({ conditions: { any: [{ field: "a" }] } }, { conditions: [] }), [
      "conditions",
    ]);
  });

  test("false and an empty string are both values, not interchangeable", () => {
    assert.deepEqual(definitionDifferences({ value: false }, { value: "" }), ["value"]);
    assert.deepEqual(definitionDifferences({ value: null }, {}), []);
  });
});
