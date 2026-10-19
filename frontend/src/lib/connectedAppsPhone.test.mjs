// Connected apps must stay disconnectable on a phone (Jared, 2026-10-18). Two ways the Disconnect button left the screen:
//  - Admin: a six-column table scrolled sideways, Disconnect in the last column ~620px out at 390px wide;
//  - My API tokens: the card grid's implicit `auto` column grew to a long unbreakable client name (a hostname), widening
//    the page to 1400px with the button at its far end.
// Checked in a phone-width browser against a seeded connection; these keep the two rules in place.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";

const SRC = new URL("../", import.meta.url);
const read = (path) => readFileSync(new URL(path, SRC), "utf8");
const GLOBAL_CSS = read("styles/global.css");

describe("admin connected apps", () => {
  const page = read("pages/admin/connected-apps.astro");

  test("stacks into cards on a phone, so Disconnect is not off to the right", () => {
    assert.match(page, /<table class="table stacks\b/);
    assert.match(GLOBAL_CSS, /@media \(max-width: 640px\)\s*\{\s*\.table\.stacks,/);
    assert.match(page, /@media \(max-width: 640px\)[^}]*\.apps tr \{ grid-template-columns: minmax\(0, 1fr\)/);
  });

  test("every cell the stacked card shows names itself", () => {
    const labelled = [...page.matchAll(/<td data-label="([^"]+)"/g)].map((m) => m[1]);
    assert.deepEqual(labelled, ["User", "Workspace", "Access", "Last used"]);
  });
});

describe("my connected apps (API tokens page)", () => {
  const page = read("pages/user/api-tokens.astro");
  const rule = (selector) => page.match(new RegExp(`${selector.replace(".", "\\.")}\\s*\\{([^}]*)\\}`))?.[1] ?? "";

  test("the card list cannot be widened by a long client name", () => {
    assert.match(rule(".tokens-list"), /grid-template-columns:\s*minmax\(0,\s*1fr\)/);
    assert.match(rule(".token-info"), /min-width:\s*0/);
    assert.match(rule(".token-info"), /overflow-wrap:\s*anywhere/);
  });
});
