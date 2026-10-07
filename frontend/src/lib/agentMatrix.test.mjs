// Permission-matrix editor helpers (agentMatrix.ts) behind Settings → AI → Agents. Run with `npm test` —
// plain `node --test`, which strips agentMatrix.ts's types itself. Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  inheritedDefaults,
  inheritLabel,
  matrixCategories,
  matrixState,
  matrixTools,
  POLICY_LABELS,
  policyFromChoices,
} from "./agentMatrix.ts";

const read = { id: "entries_read", writes: false };
const write = { id: "automation_run", writes: true };

describe("inheritLabel", () => {
  test("custom agents: reads allow, writes follow Allow writes", () => {
    assert.equal(inheritLabel(read, false), "Default (allow)");
    assert.equal(inheritLabel(write, true), "Default (ask first — writes on)");
    assert.equal(inheritLabel(write, false), "Default (block — read-only)");
  });

  test("a built-in's own default wins when the server gives one", () => {
    assert.equal(inheritLabel(write, true, "ask"), "Default (ask first)");
    assert.equal(inheritLabel({ id: "links", writes: true }, true, "allow"), "Default (allow)");
    assert.equal(inheritLabel(read, false, "block"), "Default (block)");
    assert.equal(inheritLabel(write, false, null), "Default (block — read-only)");
  });

  test("labels match the selects", () => {
    assert.deepEqual(POLICY_LABELS, { allow: "Allow", ask: "Ask first", block: "Block" });
  });
});

test("inheritedDefaults maps rows to their inherited decision", () => {
  const rows = [
    { id: "links", inherited: "allow" },
    { id: "automation_run", inherited: "ask" },
    { id: "old" }, // an older backend without the field
  ];
  assert.deepEqual(inheritedDefaults(rows), { links: "allow", automation_run: "ask" });
});

describe("matrixTools / matrixCategories", () => {
  const tools = [
    { name: "search_content", category: "entries_read" },
    { name: "compose_entry", category: "entries_author" },
    { name: "suggest_agent", category: "agents_read" },
  ];
  const cats = [
    { id: "entries_read", writes: false },
    { id: "entries_author", writes: true },
    { id: "agents_read", writes: false },
    { id: "automation_run", writes: true },
    { id: "mcp", writes: true },
  ];

  test("no allowlist: every tool, every used row plus the MCP rows", () => {
    assert.equal(matrixTools(tools, null), tools);
    assert.deepEqual(
      matrixCategories(cats, tools, null).map((c) => c.id),
      ["entries_read", "entries_author", "agents_read", "mcp"],
    );
  });

  test("an allowlist (Ask) keeps only its tools and their rows, no MCP rows", () => {
    const allow = ["search_content", "suggest_agent"];
    const listed = matrixTools(tools, allow);
    assert.deepEqual(
      listed.map((t) => t.name),
      ["search_content", "suggest_agent"],
    );
    assert.deepEqual(
      matrixCategories(cats, listed, allow).map((c) => c.id),
      ["entries_read", "agents_read"],
    );
  });
});

test("matrixState says Default or Changed", () => {
  assert.equal(matrixState({ toolPolicyOverridden: true }), "Changed");
  assert.equal(matrixState({ toolPolicyOverridden: false }), "Default");
  assert.equal(matrixState({}), "Default");
});

test("policyFromChoices keeps explicit choices and is null when there are none", () => {
  assert.deepEqual(
    policyFromChoices([
      ["links", "block"],
      ["attach_tag", ""],
      ["automation_run", "allow"],
      ["mcp", "ask"],
      ["", "allow"],
      ["x", "maybe"],
    ]),
    { links: "block", automation_run: "allow", mcp: "ask" },
  );
  assert.equal(policyFromChoices([["links", ""]]), null);
  assert.equal(policyFromChoices([]), null);
});
