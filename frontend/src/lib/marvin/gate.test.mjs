// Whether the Ask bubble shows (gate.ts). Run with `npm test` — plain `node --test`, which strips
// gate.ts's types itself. Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { bubbleAllowed } from "./gate.ts";

describe("bubbleAllowed", () => {
  test("shows when AI is on and no sources policy is set", () => {
    assert.equal(bubbleAllowed({ enabled: true }), true);
    assert.equal(bubbleAllowed({ enabled: true, invocationSources: null }), true);
  });

  test("hides when AI is off for the workspace", () => {
    assert.equal(bubbleAllowed({ enabled: false, invocationSources: { agent: true } }), false);
  });

  test("hides when the Ask source is switched off", () => {
    assert.equal(bubbleAllowed({ enabled: true, invocationSources: { agent: false } }), false);
  });

  test("other sources being off doesn't hide it", () => {
    assert.equal(bubbleAllowed({ enabled: true, invocationSources: { editor: false, mcp: false } }), true);
  });

  test("no settings at all means no bubble", () => {
    assert.equal(bubbleAllowed(null), false);
    assert.equal(bubbleAllowed(undefined), false);
  });
});
