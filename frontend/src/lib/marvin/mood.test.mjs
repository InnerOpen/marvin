// lib/marvin/mood.ts: what the Social Battery changes in the bubble — the band's lines, the resting state, the battery, /mood.
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { batteryHtml, moodText, moodVoice, restState } from "./mood.ts";

const VOICE = { greetings: ["Hi."], taglines: ["here to help"], thinking: [], errors: [], emotes: [] };
const MOOD = { meter: "visible", low: { greetings: ["Mm-hmm."], taglines: [] }, high: { greetings: [], taglines: ["almost cheerful"] } };

describe("the band's lines", () => {
  test("a low or high band swaps in the lines it has and keeps the rest", () => {
    assert.deepEqual(moodVoice(VOICE, MOOD, "low").greetings, ["Mm-hmm."]);
    assert.deepEqual(moodVoice(VOICE, MOOD, "low").taglines, ["here to help"]);
    assert.deepEqual(moodVoice(VOICE, MOOD, "high").taglines, ["almost cheerful"]);
    assert.deepEqual(moodVoice(VOICE, MOOD, "high").greetings, ["Hi."]);
  });

  test("neutral, no settings or blank lines change nothing", () => {
    assert.equal(moodVoice(VOICE, MOOD, "neutral"), VOICE);
    assert.equal(moodVoice(VOICE, null, "low"), VOICE);
    assert.deepEqual(moodVoice(VOICE, { low: { greetings: ["  ", ""] } }, "low").greetings, ["Hi."]);
  });
});

describe("what the bubble shows", () => {
  test("a low mood rests in the waiting state when the pack has one", () => {
    assert.equal(restState("low", { idle: "a.gif", waiting: "b.gif" }), "waiting");
    assert.equal(restState("low", { idle: "a.gif" }), "idle");
    assert.equal(restState("high", { idle: "a.gif", waiting: "b.gif" }), "idle");
  });

  test("the battery shows the level with the band, escaped, and hides when the character keeps it to itself", () => {
    const html = batteryHtml({ level: 24, band: "low", visible: true }, "Marvin <b>");
    assert.match(html, /class="marvin-battery mood-low"/);
    assert.match(html, /🪫/);
    assert.match(html, /marvin-battery-level">24</);
    assert.match(html, /Marvin &lt;b&gt;/);
    assert.equal(batteryHtml({ level: null, band: "low", visible: false }, "Ada"), "");
    assert.equal(batteryHtml(null, "Ada"), "");
  });

  test("/mood says the level, what it means and that it's a game; or that it's off", () => {
    const text = moodText({ level: 81, band: "high", visible: true }, "Ada");
    assert.match(text, /81 of 100 — doing well/);
    assert.match(text, /It's a game/);
    assert.match(text, /\/mood reset/);
    assert.match(moodText({ level: null, band: "low", visible: false }, "Ada"), /keeps the number to itself — running low/);
    assert.match(moodText(null, "Ada"), /isn't keeping a Social Battery/);
  });
});
