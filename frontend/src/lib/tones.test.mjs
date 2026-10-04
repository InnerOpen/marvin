// Tone helpers (tones.ts) behind the bubble's `/tone` and the tone pickers. Run with `npm test` — plain
// `node --test`, which strips tones.ts's types itself. Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { BUILTIN_TONES, findTone, pickerTones, toneOptions } from "./tones.ts";

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
