// The usage card's unpriced-runs note (aiUsage.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { test } from "node:test";

import { integrationCall, isUnitBilled, unpricedNotice } from "./aiUsage.ts";

const m = (provider, model, runs) => ({ provider, model, runs, tokens: runs * 100 });

test("nothing to say when every run had a price", () => {
  assert.equal(unpricedNotice(0, []), null);
  assert.equal(unpricedNotice(undefined, undefined), null);
});

test("names the models, three at most, and says the limit can't see them", () => {
  const note = unpricedNotice(12, [m("anthropic", "claude-x", 9), m("google", "gemini-y", 2), m("openai", "gpt-z", 1), m("ollama", "q", 0)]);
  assert.match(note, /^12 runs this month used a model with no price \(anthropic claude-x, google gemini-y, openai gpt-z and 1 more\)/);
  assert.match(note, /monthly limit can't see it/);
  assert.match(unpricedNotice(1, [m("google", "g", 1)]), /^1 run .*its cost/);
});

import { integrationLines } from "./aiUsage.ts";

test("an integration's calls are tallied in its own unit, with the multiplier only when it changed the figure", () => {
  const speech = { provider: "elevenlabs", unit: "characters", calls: 12, units: 4300, billed: 2900 };
  assert.deepEqual(integrationLines([speech]), ["elevenlabs: 12 calls, 4,300 characters, 2,900 billed at the models' multipliers"]);
  assert.deepEqual(integrationLines([{ ...speech, calls: 1, billed: 4300 }]), ["elevenlabs: 1 call, 4,300 characters"]);
  assert.deepEqual(integrationLines([{ provider: "openai_images", unit: "calls", calls: 3, units: 3, billed: 3 }]), ["openai_images: 3 calls"]);
  assert.deepEqual(integrationLines(undefined), []);
});

test("an integration call shows its units and multiplier where tokens and dollars would be", () => {
  assert.deepEqual(integrationCall({ unit: "characters", units: 285, multiplier: 0.5 }), { used: "285 characters × 0.5", billed: "142.5 billed" });
  assert.deepEqual(integrationCall({ unit: "characters", units: 33, multiplier: 1 }), { used: "33 characters × 1", billed: "33 billed" });
  assert.deepEqual(integrationCall({ unit: "characters", units: 1200 }), { used: "1,200 characters × 1", billed: "1,200 billed" }); // no multiplier: one for one
  assert.deepEqual(integrationCall({ unit: "calls", units: 1 }), { used: "1 call", billed: "—" });
  assert.equal(integrationCall(null), null);
  assert.equal(integrationCall({}), null);
});

test("a row whose credits were measured shows them, and what is left", () => {
  const measured = { unit: "characters", units: 285, multiplier: 1, credits: 300, credits_remaining: 98760 };
  assert.deepEqual(integrationCall(measured), { used: "285 characters", billed: "300 credits · 98,760 left" });
  assert.deepEqual(integrationCall({ unit: "characters", units: 40, multiplier: 0.5, credits_remaining: 500 }), { used: "40 characters × 0.5", billed: "20 billed · 500 left" });
  assert.deepEqual(integrationCall({ unit: "characters", units: 40, credits: 0 }), { used: "40 characters", billed: "0 credits" });
});

test("an integration row shows units only when it has no tokens", () => {
  assert.equal(isUnitBilled("integration", null), true); // ElevenLabs: characters, no tokens
  assert.equal(isUnitBilled("integration", 0), true);
  assert.equal(isUnitBilled("integration", 2185), false); // OpenAI Images: tokens and an estimated cost, like an AI run
  assert.equal(isUnitBilled("agent", null), false);
  assert.equal(isUnitBilled(undefined, 10), false);
});
