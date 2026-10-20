// Which entry types are offered for writing (entryTypeListing.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  INTERNAL_TYPE_SLUGS,
  isListedType,
  listedTypes,
} from "./entryTypeListing.ts";

describe("internal entry types", () => {
  test("listed unless the flag says false or the slug is a core internal one", () => {
    assert.equal(isListedType({ slug: "note" }), true);
    assert.equal(isListedType({ slug: "note", capabilitiesJson: {} }), true);
    assert.equal(
      isListedType({ slug: "note", capabilitiesJson: { listed: true } }),
      true,
    );
    assert.equal(
      isListedType({ slug: "note", capabilitiesJson: { publishable: false } }),
      true,
    );
    assert.equal(
      isListedType({ slug: "secret", capabilitiesJson: { listed: false } }),
      false,
    );
    for (const slug of INTERNAL_TYPE_SLUGS)
      assert.equal(isListedType({ slug, capabilitiesJson: null }), false);
    assert.equal(isListedType(null), true);
  });

  test("the types to offer leave the internal ones out and keep the order", () => {
    const types = [
      { slug: "page" },
      { slug: "social-auto-reply" },
      { slug: "post", capabilitiesJson: { listed: false } },
      { slug: "note" },
    ];
    assert.deepEqual(
      listedTypes(types).map((t) => t.slug),
      ["page", "note"],
    );
    assert.deepEqual(listedTypes(null), []);
  });

  test("the slugs match the backend's list", () => {
    assert.deepEqual([...INTERNAL_TYPE_SLUGS].sort(), [
      "social-auto-reply",
      "social-reply-log",
    ]);
  });
});
