// Tone helpers (tones.ts) behind the bubble's `/tone` and the tone pickers. Run with `npm test` — plain
// `node --test`, which strips tones.ts's types itself. Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { BUILTIN_TONES, findTone, pickerTones, previewSections, toneOptions } from "./tones.ts";

const custom = (slug, name, over = {}) => ({
  slug,
  name,
  instructions: "x",
  persona: "frame",
  description: null,
  builtin: false,
  hidden: false,
  usedBy: [],
  ...over,
});

const TONES = [...BUILTIN_TONES, custom("board-report", "Board Report"), custom("old", "Old", { hidden: true })];

describe("findTone", () => {
  test("matches a slug or a name, case-insensitively", () => {
    assert.equal(findTone(TONES, "board-report")?.slug, "board-report");
    assert.equal(findTone(TONES, "  board REPORT ")?.slug, "board-report");
    assert.equal(findTone(TONES, "Professional")?.slug, "professional");
  });

  test("never offers a hidden tone or an empty ref", () => {
    assert.equal(findTone(TONES, "old"), undefined);
    assert.equal(findTone(TONES, ""), undefined);
  });
});

describe("pickerTones", () => {
  test("drops hidden tones but keeps the stored value", () => {
    assert.deepEqual(
      pickerTones(TONES).map((t) => t.slug),
      ["auto", "professional", "playful", "board-report"],
    );
    assert.ok(pickerTones(TONES, "old").some((t) => t.slug === "old"));
  });
});

describe("toneOptions", () => {
  test("selects the stored tone and leads with the inherit option", () => {
    const html = toneOptions(TONES, "board-report", { inherit: "Workspace default" });
    assert.match(html, /^<option value="">Workspace default<\/option>/);
    assert.match(html, /<option value="board-report" selected>Board Report<\/option>/);
  });

  test("keeps a deleted slug selectable so saving doesn't silently change it", () => {
    assert.match(toneOptions(TONES, "gone"), /<option value="gone" selected>gone \(deleted/);
  });

  test("escapes names", () => {
    assert.match(toneOptions([custom("x", "<b>")], null), /&#60;b&#62;/);
  });
});

describe("previewSections", () => {
  const preview = (over = {}) => ({
    clause: "x",
    tokens: 1,
    persona: "frame",
    personaSummary: "Frame only: the character talks, work product follows this tone.",
    hasPersona: true,
    character: "Character: You are Ada.",
    fromTone: "Tone (Warm): Write warmly.",
    rule: "Where the tone and the character disagree…",
    ...over,
  });

  test("passes the parts through with no notes when each part has text", () => {
    const p = previewSections(preview());
    assert.equal(p.character, "Character: You are Ada.");
    assert.equal(p.fromTone, "Tone (Warm): Write warmly.");
    assert.equal(p.characterNote, "");
    assert.equal(p.fromToneNote, "");
  });

  test("says a drop tone leaves the character out", () => {
    const p = previewSections(preview({ persona: "drop", character: "", rule: "" }));
    assert.equal(p.characterNote, "Not used — this tone drops the character.");
  });

  test("says when there is no persona to add", () => {
    const p = previewSections(preview({ hasPersona: false, character: "", fromTone: "", rule: "" }));
    assert.equal(p.characterNote, "No character set, so there's none to add.");
    assert.match(p.fromToneNote, /only places the character/);
  });
});
