// The usage card's unpriced-runs note (aiUsage.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { test } from "node:test";

import { unpricedNotice } from "./aiUsage.ts";

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
