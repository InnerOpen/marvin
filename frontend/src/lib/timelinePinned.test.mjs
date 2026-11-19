import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { layout } from "./timeline.ts";
import { PINNED_CASES } from "./timelinePinned.cases.mjs";

// What layout gave for these views before `spine.start` and a lane's `per` existed (made with the code of develop at 1253bcaf).
const PINNED = JSON.parse(readFileSync(new URL("./timelinePinned.json", import.meta.url), "utf8"));

for (const [name, { spec, rows }] of Object.entries(PINNED_CASES)) {
  test(`a view placed in order and with no rows per value is laid out exactly as before: ${name}`, () => {
    assert.deepEqual(JSON.parse(JSON.stringify(layout(spec, rows))), PINNED[name]);
  });
}
