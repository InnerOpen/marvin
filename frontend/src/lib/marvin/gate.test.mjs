// Whether the Ask surfaces show (gate.ts). Run with `npm test` — plain `node --test`, which strips
// gate.ts's types itself. Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { askPageAllowed, bubbleAllowed, sourceAllowed } from "./gate.ts";

describe("bubbleAllowed", () => {
  test("shows when AI is on and no sources policy is set", () => {
    assert.equal(bubbleAllowed({ enabled: true }), true);
    assert.equal(bubbleAllowed({ enabled: true, invocationSources: null }), true);
  });

  test("hides when AI is off for the workspace", () => {
    assert.equal(bubbleAllowed({ enabled: false, invocationSources: { bubble: true } }), false);
  });

  test("hides when the bubble source is switched off", () => {
    assert.equal(bubbleAllowed({ enabled: true, invocationSources: { bubble: false } }), false);
  });

  test("hides when the legacy agent source is switched off", () => {
    assert.equal(bubbleAllowed({ enabled: true, invocationSources: { agent: false } }), false);
  });

  test("the Ask page being off doesn't hide it", () => {
    assert.equal(bubbleAllowed({ enabled: true, invocationSources: { ask_page: false, editor: false } }), true);
  });

  test("no settings at all means no bubble", () => {
    assert.equal(bubbleAllowed(null), false);
    assert.equal(bubbleAllowed(undefined), false);
  });
});

describe("askPageAllowed", () => {
  test("allowed when AI is on and no sources policy is set", () => {
    assert.equal(askPageAllowed({ enabled: true }), true);
  });

  test("off when AI is off for the workspace", () => {
    assert.equal(askPageAllowed({ enabled: false }), false);
  });

  test("off when the ask_page source is switched off", () => {
    assert.equal(askPageAllowed({ enabled: true, invocationSources: { ask_page: false } }), false);
  });

  test("off when the legacy agent source is switched off", () => {
    assert.equal(askPageAllowed({ enabled: true, invocationSources: { agent: false } }), false);
  });

  test("the bubble being off doesn't switch it off", () => {
    assert.equal(askPageAllowed({ enabled: true, invocationSources: { bubble: false } }), true);
  });
});

describe("sourceAllowed", () => {
  test("a source is on unless explicitly false", () => {
    assert.equal(sourceAllowed(null, "editor"), true);
    assert.equal(sourceAllowed({ editor: true }, "editor"), true);
    assert.equal(sourceAllowed({ editor: false }, "editor"), false);
  });

  test("legacy agent:false switches off only the Ask surfaces", () => {
    const policy = { agent: false };
    assert.equal(sourceAllowed(policy, "bubble"), false);
    assert.equal(sourceAllowed(policy, "ask_page"), false);
    assert.equal(sourceAllowed(policy, "editor"), true);
  });
});
