// Which canned lines the bubble speaks (persona.ts voiceFor). Run with `npm test` — plain `node --test`,
// which strips persona.ts's types itself. Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { MARVIN_VOICE, neutralVoice, voiceFor } from "./persona.ts";

const ADA_LINES = {
  greetings: ["Well hello there. What can I help you with?"],
  taglines: ["here whenever you need me"],
  thinking: ["Let me take a look."],
  errors: ["Oh, that didn't go right."],
  emotes: ["*smiles warmly*"],
};

const marvinLines = new Set(Object.values(MARVIN_VOICE).flat());

describe("voiceFor", () => {
  test("test_voice_for_marvin_without_stored_lines_returns_marvins_voice", () => {
    assert.deepEqual(voiceFor("Marvin"), MARVIN_VOICE);
  });

  test("test_voice_for_marvin_with_a_custom_persona_but_no_lines_keeps_marvins_voice", () => {
    // Mash & Burn: a long custom Marvin persona, still named Marvin.
    assert.deepEqual(voiceFor("Marvin", null), MARVIN_VOICE);
  });

  test("test_voice_for_a_renamed_assistant_without_lines_returns_the_neutral_set", () => {
    assert.deepEqual(voiceFor("Ada"), neutralVoice("Ada"));
  });

  test("test_voice_for_stored_lines_win_over_marvin_by_name", () => {
    assert.deepEqual(voiceFor("Marvin", ADA_LINES), ADA_LINES);
  });

  test("test_voice_for_stored_lines_win_over_the_neutral_set", () => {
    assert.deepEqual(voiceFor("Ada", ADA_LINES), ADA_LINES);
  });

  test("test_voice_for_an_empty_or_missing_list_falls_back_per_list", () => {
    const voice = voiceFor("Marvin", { greetings: ["Hey."], taglines: [], thinking: ["  "] });
    assert.deepEqual(voice.greetings, ["Hey."]);
    assert.deepEqual(voice.taglines, MARVIN_VOICE.taglines);
    assert.deepEqual(voice.thinking, MARVIN_VOICE.thinking);
    assert.deepEqual(voice.emotes, MARVIN_VOICE.emotes);
  });

  test("test_voice_for_ada_never_gets_a_marvin_line", () => {
    for (const stored of [undefined, null, {}, { greetings: ["Hi, sugar."] }, { taglines: [] }]) {
      const lines = Object.values(voiceFor("Ada", stored)).flat();
      assert.equal(lines.filter((line) => marvinLines.has(line)).length, 0);
    }
  });

  test("test_voice_for_never_mutates_the_built_in_voice", () => {
    voiceFor("Marvin", ADA_LINES);
    assert.equal(MARVIN_VOICE.greetings.includes(ADA_LINES.greetings[0]), false);
  });
});
