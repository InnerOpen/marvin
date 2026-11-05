// Web addresses in an approval's message (linkify.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { describeAddress, messageParts } from "./linkify.ts";

describe("messageParts", () => {
  test("a message with no address is one plain part", () => {
    assert.deepEqual(messageParts("Make the still?"), [{ text: "Make the still?" }]);
  });

  test("an address becomes a link, with the text around it kept", () => {
    assert.deepEqual(messageParts("Watch it: https://a.example/f.html (opens in a tab)."), [
      { text: "Watch it: " },
      { text: "https://a.example/f.html", href: "https://a.example/f.html" },
      { text: " (opens in a tab)." },
    ]);
  });

  test("punctuation that ends a sentence is not part of the address", () => {
    const parts = messageParts("See https://a.example/x.");
    assert.deepEqual(parts[1], { text: "https://a.example/x", href: "https://a.example/x" });
    assert.deepEqual(parts[2], { text: "." });
  });

  test("two addresses, and only http or https ones, are links", () => {
    const parts = messageParts("a https://one.example b http://two.example c javascript:alert(1)");
    assert.deepEqual(parts.filter((p) => p.href).map((p) => p.href), ["https://one.example", "http://two.example"]);
    assert.equal(parts.map((p) => p.text).join(""), "a https://one.example b http://two.example c javascript:alert(1)");
  });

  test("an empty or missing message is no parts", () => {
    assert.deepEqual(messageParts(""), []);
    assert.deepEqual(messageParts(undefined), []);
  });
});

describe("describeAddress", () => {
  test("names the site and the rest of the address in short", () => {
    assert.deepEqual(describeAddress("https://admin.iwobble.com/workspace/assets/74e83b26/view?x=1#top"), { host: "admin.iwobble.com", path: "workspace/assets/74e83b26/view" });
    assert.deepEqual(describeAddress("https://www.example.com/"), { host: "example.com", path: "" });
    assert.deepEqual(describeAddress("http://localhost:4321/a/"), { host: "localhost:4321", path: "a" });
  });

  test("an address the browser cannot parse is shown whole", () => {
    assert.deepEqual(describeAddress("https://"), { host: "https://", path: "" });
  });
});
