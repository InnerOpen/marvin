// The shared prompt-preview renderer (promptPreview.ts) behind the tone, Character and agent previews. Run with
// `npm test` — plain `node --test`, which strips the types itself. Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  agentPreviewView,
  characterPreviewView,
  promptPreviewHtml,
  tonePreviewView,
  toolsNote,
} from "./promptPreview.ts";

const RULE = "Where the tone and the character disagree on formality, length or mood, follow the tone.";

const tone = (over = {}) => ({
  clause: "\n\nCharacter: You are Ada.\n\nTone (Warm): Write warmly.",
  tokens: 12,
  persona: "frame",
  personaSummary: "Frame only: the character talks, work product follows this tone.",
  hasPersona: true,
  character: "Character: You are Ada.",
  fromTone: "Tone (Warm): Write warmly.",
  rule: RULE,
  toneSlug: "warm",
  toneName: "Warm",
  ...over,
});

const agent = (over = {}) => ({
  system: "PREAMBLE\n\nScout the bench.…",
  tokens: 900,
  kind: "persona",
  workspace: "You are working inside the workspace.",
  instructions: "Scout the bench.",
  defaultInstructions: false,
  tone: tone(),
  toneSource: "agent",
  roster: "Other agents you can hand off to: ask.",
  toolCount: 9,
  askFirstCount: 2,
  toolCategories: [
    { id: "entries_read", label: "Entries: read", count: 5 },
    { id: "links", label: "Links", count: 4 },
  ],
  ...over,
});

const labels = (view) => view.parts.map((p) => p.label);

describe("tone and Character previews", () => {
  test("a tone shows the persona's part, the tone's part and which wins", () => {
    const view = tonePreviewView(tone());
    assert.deepEqual(labels(view), ["From your", "From this tone", "Which wins"]);
    assert.equal(view.parts[0].labelLink.text, "Persona");
    assert.equal(view.full, tone().clause.trim());
  });

  test("the Character box names the default tone and points at its own field", () => {
    const view = characterPreviewView(tone({ toneSlug: "auto", toneName: "Auto", rule: "" }));
    assert.match(view.summary, /workspace default tone, Auto/);
    assert.deepEqual(labels(view), ["From the Character field", "From the default tone (Auto)"]);
    assert.equal(view.parts[0].labelLink, undefined);
  });

  test("a part with no text says why instead", () => {
    const view = tonePreviewView(tone({ persona: "drop", character: "", rule: "" }));
    assert.equal(view.parts[0].emptyNote, "Not used — this tone drops the character.");
    assert.match(promptPreviewHtml(view), /prompt-part-empty">Not used — this tone drops the character\./);
  });
});

describe("agent preview", () => {
  test("parts follow the prompt: workspace, agent, character, tone, rule, roster", () => {
    assert.deepEqual(labels(agentPreviewView(agent())), [
      "Workspace context",
      "From this agent",
      "From your",
      "From the tone Warm",
      "Which wins",
      "Other agents",
    ]);
  });

  test("says where the tone comes from and when the instructions are the default", () => {
    const view = agentPreviewView(agent({ toneSource: "workspace", defaultInstructions: true }));
    assert.match(view.summary, /^Tone: Warm \(the workspace default tone\)\./);
    assert.equal(view.parts[1].label, "Default instructions");
  });

  test("a model agent has no workspace part and says it has no tools", () => {
    const view = agentPreviewView(
      agent({ kind: "model", workspace: "", roster: "", toolCount: 0, toolCategories: [] }),
    );
    assert.equal(labels(view)[0], "From this agent");
    assert.deepEqual(view.notes, ["No tools: a model agent is plain chat."]);
  });

  test("tools are summarised by category, never listed", () => {
    assert.equal(
      toolsNote(agent()),
      "9 tools, as you would run it from Ask, 2 of them ask first: Entries: read (5), Links (4). Their definitions are sent too and aren't shown here.",
    );
  });
});

describe("promptPreviewHtml", () => {
  test("escapes prompt text and folds the long background parts", () => {
    const html = promptPreviewHtml(agentPreviewView(agent({ instructions: "<b>bold</b> & co" })));
    assert.match(html, /&lt;b&gt;bold&lt;\/b&gt; &amp; co/);
    assert.match(html, /<details class="prompt-part"><summary class="prompt-part-label">Workspace context/);
    assert.match(html, /<p class="prompt-preview-rule"><strong>Which wins:<\/strong>/);
    assert.match(html, /About 900 tokens/);
  });
});
