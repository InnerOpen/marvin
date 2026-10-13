// Share links on an entry (shareLinks.ts): the buttons the entry page shows. Run with `npm test`.

import assert from "node:assert/strict";
import { test } from "node:test";

import { shareLinks } from "./shareLinks.ts";

test("keeps web and mail links with their labels, and the post text", () => {
  const { links, text } = shareLinks({
    share_text: "New etching. ",
    share_links: { Bluesky: "https://bsky.app/intent/compose?text=x", Email: "mailto:?subject=x" },
  });
  assert.deepEqual(links, [
    { label: "Bluesky", href: "https://bsky.app/intent/compose?text=x" },
    { label: "Email", href: "mailto:?subject=x" },
  ]);
  assert.equal(text, "New etching.");
});

test("drops anything that isn't an https or mailto link", () => {
  const { links } = shareLinks({ share_links: { Evil: "javascript:alert(1)", Plain: "http://x.test", Odd: 3 } });
  assert.deepEqual(links, []);
});

test("an entry without share links has none", () => {
  assert.deepEqual(shareLinks(null), { links: [], text: null });
  assert.deepEqual(shareLinks({ share_links: ["https://x.test"] }), { links: [], text: null });
});
