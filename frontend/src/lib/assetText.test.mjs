// Which files preview as text, and reading the start of one (assetText.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { fetchTextPreview, isTextMime } from "./assetText.ts";

describe("isTextMime", () => {
  test("text types, JSON, XML and YAML are text; HTML, images, audio and nothing are not", () => {
    for (const t of ["text/plain", "text/markdown", "text/csv", "text/plain; charset=utf-8", "application/json", "application/ld+json", "application/xml", "application/atom+xml", "application/x-yaml"]) assert.equal(isTextMime(t), true, t);
    for (const t of ["text/html", "image/png", "audio/mpeg", "application/pdf", "", null, undefined]) assert.equal(isTextMime(t), false, String(t));
  });
});

describe("fetchTextPreview", () => {
  const reply = (body, ok = true) => async () => ({ ok, text: async () => body });

  test("a short file is shown whole", async () => {
    assert.deepEqual(await fetchTextPreview("u", 100, reply("hello")), { text: "hello", truncated: false });
  });

  test("a long file is cut at the limit and says so", async () => {
    assert.deepEqual(await fetchTextPreview("u", 3, reply("abcdef")), { text: "abc", truncated: true });
  });

  test("a refused or failed read is null, not an error", async () => {
    assert.equal(await fetchTextPreview("u", 100, reply("x", false)), null);
    assert.equal(await fetchTextPreview("u", 100, async () => { throw new Error("down"); }), null);
  });
});
