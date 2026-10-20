// Where the entry editor's Back goes (entryBack.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  ENTRIES_PATH,
  entryBackPath,
  returnPathOf,
  ruleEditorHref,
  ruleNetworks,
  withReturn,
} from "./entryBack.ts";

const RULES_TAB = "/workspace/social/instagram?tab=rules";
const rule = (networks) => ({ typeSlug: "social-auto-reply", data: { networks } });

describe("returnPathOf", () => {
  test("keeps a path on this site, with its query", () => {
    assert.equal(returnPathOf(RULES_TAB), RULES_TAB);
    assert.equal(returnPathOf("/workspace/entries"), "/workspace/entries");
  });

  test("anything that could leave the site, or break a header, is no return path", () => {
    for (const value of [
      "https://evil.example",
      "//evil.example",
      "/\\evil.example",
      "javascript:alert(1)",
      "workspace/entries",
      "/ok\r\nSet-Cookie: x=1",
      "/ok\n",
      "",
      null,
      undefined,
    ]) {
      assert.equal(returnPathOf(value), null, String(value));
    }
  });
});

describe("the links that carry a return path", () => {
  test("a rule's editor link comes back to its network's Rules tab", () => {
    const href = ruleEditorHref("/workspace/entries/abc", "instagram");
    assert.equal(href, `/workspace/entries/abc?return=${encodeURIComponent(RULES_TAB)}`);
    assert.equal(new URL(href, "http://x").searchParams.get("return"), RULES_TAB);
  });

  test("a network slug is encoded, and an existing query gets an &", () => {
    assert.equal(
      new URL(ruleEditorHref("/workspace/entries/abc", "my net"), "http://x").searchParams.get("return"),
      "/workspace/social/my%20net?tab=rules",
    );
    assert.equal(withReturn("/e/1?x=1", "/a"), "/e/1?x=1&return=%2Fa");
  });

  test("no return, or an unsafe one, leaves the link as it is", () => {
    assert.equal(withReturn("/e/1", null), "/e/1");
    assert.equal(withReturn("/e/1", "https://evil.example"), "/e/1");
  });
});

describe("ruleNetworks", () => {
  test("words of the field, lower-cased and without @, once each; a list works too", () => {
    assert.deepEqual(ruleNetworks("Instagram, @Threads  instagram"), ["instagram", "threads"]);
    assert.deepEqual(ruleNetworks(["IG", " "]), ["ig"]);
    assert.deepEqual(ruleNetworks(""), []);
    assert.deepEqual(ruleNetworks(undefined), []);
    assert.deepEqual(ruleNetworks(5), []);
  });
});

describe("entryBackPath", () => {
  test("a return path wins, for any entry", () => {
    assert.equal(entryBackPath({ returnTo: RULES_TAB, ...rule("threads") }), RULES_TAB);
    assert.equal(entryBackPath({ returnTo: "/workspace/collections/1", typeSlug: "note" }), "/workspace/collections/1");
  });

  test("an unsafe return path falls back to the default", () => {
    assert.equal(entryBackPath({ returnTo: "//evil.example", typeSlug: "note" }), ENTRIES_PATH);
    assert.equal(entryBackPath({ returnTo: "https://evil.example", ...rule("") }), "/workspace/social");
  });

  test("an ordinary entry goes back to All entries", () => {
    assert.equal(entryBackPath({ typeSlug: "note", data: { networks: "instagram" } }), ENTRIES_PATH);
    assert.equal(entryBackPath({}), ENTRIES_PATH);
  });

  test("a Social rule with no return path goes back to Social: its network's Rules tab when it names exactly one", () => {
    assert.equal(entryBackPath(rule("instagram")), RULES_TAB);
    assert.equal(entryBackPath(rule(["instagram"])), RULES_TAB);
    assert.equal(entryBackPath(rule("")), "/workspace/social");
    assert.equal(entryBackPath(rule("instagram, threads")), "/workspace/social");
    assert.equal(entryBackPath({ typeSlug: "social-auto-reply" }), "/workspace/social");
  });
});
