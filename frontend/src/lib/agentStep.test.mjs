// The agent step's editor and run-detail parts (agentStep.ts).

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  agentRunView,
  agentSummary,
  costText,
  offeredAgents,
  offeredPlaybooks,
  readAgentStep,
} from "./agentStep.ts";

const form = (change = {}) => ({ agent: "writer", message: "Draft it.", playbooks: [], maxSteps: "8", onEntry: true, ...change });

describe("the agents and Playbooks offered", () => {
  const agents = [
    { slug: "writer", name: "Writer", enabled: true, canDraft: true },
    { slug: "asleep", name: "Asleep", enabled: false },
  ];

  test("only switched-on agents, plus the one the step already names", () => {
    assert.deepEqual(offeredAgents(agents).map((a) => a.slug), ["writer"]);
    assert.deepEqual(offeredAgents(agents, "asleep").map((a) => a.slug), ["writer", "asleep"]);
    assert.deepEqual(offeredAgents(null), []);
  });

  test("the summary says whether it may save drafts", () => {
    assert.match(agentSummary({ ...agents[0], description: "Writes posts." }), /^Writes posts\. May save drafts on its own\.$/);
    assert.match(agentSummary({ slug: "r", name: "R", canDraft: false }), /Entries: author to Allow/);
    assert.equal(agentSummary(undefined), "");
  });

  test("a manual-only Playbook is not offered", () => {
    assert.deepEqual(offeredPlaybooks([{ name: "a" }, { name: "b", manualOnly: true }]).map((p) => p.name), ["a"]);
  });
});

describe("reading the step back from its form", () => {
  test("it needs an agent and a message", () => {
    assert.equal(readAgentStep(form({ agent: " " })), null);
    assert.equal(readAgentStep(form({ message: "  " })), null);
  });

  test("defaults stay out of the saved step", () => {
    assert.deepEqual(readAgentStep(form()), { kind: "agent", agent: "writer", message: "Draft it." });
  });

  test("playbooks are trimmed, de-duplicated and capped at three", () => {
    const step = readAgentStep(form({ playbooks: [" a ", "a", "b", "c", "d"] }));
    assert.deepEqual(step.playbooks, ["a", "b", "c"]);
  });

  test("max steps is clamped to 1-15 and falls back to 8", () => {
    assert.equal(readAgentStep(form({ maxSteps: "40" })).max_steps, 15);
    assert.equal(readAgentStep(form({ maxSteps: 3 })).max_steps, 3);
    assert.equal("max_steps" in readAgentStep(form({ maxSteps: "0" })), false);
    assert.equal("max_steps" in readAgentStep(form({ maxSteps: "nope" })), false);
  });

  test("turning on_entry off is kept; on is the default", () => {
    assert.equal(readAgentStep(form({ onEntry: false })).on_entry, false);
    assert.equal("on_entry" in readAgentStep(form(), { on_entry: false }), false);
  });

  test("what the form can't edit survives, and a cleared field is dropped", () => {
    const step = readAgentStep(form(), { id: "social", when: { field: "entry.status" }, playbooks: ["old"], max_steps: 5 });
    assert.deepEqual(step, { kind: "agent", id: "social", when: { field: "entry.status" }, agent: "writer", message: "Draft it." });
  });
});

describe("a run's agent output", () => {
  test("answer, drafts with links, Playbooks, how it ended, cost and the execution", () => {
    const view = agentRunView({
      answer: "Drafted two posts.",
      entries: [{ id: "e1", title: "Launch post", status: "draft", url: "/workspace/entries/e1", reviewLink: "[Review the draft](/workspace/entries/e1)" }],
      playbooks: ["social-post"],
      stopped: "max_steps",
      execution_id: "x1",
      tokens: 1234,
      cost_usd: 0.0123,
    });
    assert.equal(view.answer, "Drafted two posts.");
    assert.deepEqual(view.entries, [{ id: "e1", title: "Launch post", status: "draft", href: "/workspace/entries/e1", reviewLink: "[Review the draft](/workspace/entries/e1)" }]);
    assert.deepEqual(view.playbooks, ["social-post"]);
    assert.deepEqual(view.stopped, { code: "max_steps", text: "Ran out of steps: it answered with what it had" });
    assert.equal(view.executionId, "x1");
    assert.equal(costText(view.tokens, view.costUsd), "1,234 tokens · $0.01");
  });

  test("a skipped step says why; anything else is not an agent output", () => {
    const view = agentRunView({ answer: "", entries: [], playbooks: [], stopped: "refused", skipped: "its own run" });
    assert.equal(view.skipped, "its own run");
    assert.equal(agentRunView({ answer: "x" }), null);
    assert.equal(agentRunView(null), null);
  });

  test("cost text leaves out what wasn't recorded", () => {
    assert.equal(costText(null, null), "");
    assert.equal(costText(900, null), "900 tokens");
    assert.equal(costText(null, 0.0004), "$0.0004");
  });
});
