// A failed entry save re-renders what was submitted (entryForm.ts). Run with `npm test` — plain
// `node --test`, which strips the .ts types itself. Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { withSubmittedValues } from "./entryForm.ts";

const stored = {
  id: "e1",
  title: "October newsletter",
  slug: "october-newsletter",
  summary: "Old summary",
  status: "draft",
  dataJson: { subject: "" },
  metadataJson: { campaign: "fall" },
  publishAt: "2026-10-03T21:00:00.000Z",
  expireAt: null,
  tags: ["news"],
  collections: [{ id: "c1", name: "Newsletters", role: "primary", placementMetadata: null, sortOrder: 0 }],
  assets: [
    { id: "a1", name: "hero.jpg", role: "hero", placementMetadata: null, position: 0 },
    { id: "a9", name: "ai.png", role: null, placementMetadata: { suggested: true }, position: 1 },
  ],
  resources: [],
};

const lookups = {
  collections: [
    { id: "c1", name: "Newsletters" },
    { id: "c2", name: "Featured" },
  ],
  assets: [
    { id: "a1", name: "hero.jpg" },
    { id: "a2", name: "footer.png" },
  ],
  resources: [{ id: "r1", title: "Signup form" }],
  tags: [
    { id: "t1", slug: "news" },
    { id: "t2", slug: "fall" },
  ],
};

describe("withSubmittedValues", () => {
  test("shows the submitted scalar fields, content and schedule", () => {
    const shown = withSubmittedValues(
      stored,
      {
        title: "October news",
        summary: "New summary",
        status: "needs_review",
        data_json: { subject: "Fall is here" },
        metadata_json: { campaign: "autumn" },
        publish_at: "2026-10-04T09:00:00.000Z",
        expire_at: null,
      },
      lookups,
    );

    assert.deepEqual(
      [shown.title, shown.summary, shown.status, shown.dataJson, shown.metadataJson, shown.publishAt, shown.expireAt],
      [
        "October news",
        "New summary",
        "needs_review",
        { subject: "Fall is here" },
        { campaign: "autumn" },
        "2026-10-04T09:00:00.000Z",
        null,
      ],
    );
  });

  test("shows the stored status after a refused publish, so Save keeps the edits and Publish retries", () => {
    const shown = withSubmittedValues(stored, { title: "October news", status: "published" }, lookups);

    assert.deepEqual([shown.title, shown.status], ["October news", "draft"]);
  });

  test("keeps stored values the payload doesn't carry", () => {
    const shown = withSubmittedValues(stored, { title: "T", slug: null, data_json: null }, lookups);

    assert.deepEqual(
      [shown.slug, shown.dataJson, shown.publishAt],
      ["october-newsletter", { subject: "" }, "2026-10-03T21:00:00.000Z"],
    );
  });

  test("shows the submitted tags, resolving ids added in this edit", () => {
    const shown = withSubmittedValues(stored, { tag_ids: ["t2", "t1", "gone"] }, lookups);

    assert.deepEqual(shown.tags, ["fall", "news"]);
  });

  test("shows submitted attachments in submitted order with their placement", () => {
    const shown = withSubmittedValues(
      stored,
      {
        collection_attachments: [
          { collection_id: "c2", role: "featured", metadata: { pin: true } },
          { collection_id: "c1", role: null, metadata: null },
        ],
        resource_attachments: [{ resource_id: "r1", role: "cta", metadata: null }],
      },
      lookups,
    );

    assert.deepEqual(
      shown.collections.map((c) => [c.id, c.name, c.role, c.placementMetadata, c.sortOrder]),
      [
        ["c2", "Featured", "featured", { pin: true }, 0],
        ["c1", "Newsletters", null, null, 1],
      ],
    );
    assert.deepEqual(
      shown.resources.map((r) => [r.id, r.title, r.role, r.position]),
      [["r1", "Signup form", "cta", 0]],
    );
  });

  test("keeps AI-suggested assets, which the form never posts", () => {
    const shown = withSubmittedValues(
      stored,
      {
        asset_attachments: [
          { asset_id: "a2", role: null, metadata: null, position: 0 },
          { asset_id: "a1", role: "hero", metadata: null, position: 1 },
        ],
      },
      lookups,
    );

    assert.deepEqual(
      shown.assets.map((a) => [a.id, a.position]),
      [
        ["a2", 0],
        ["a1", 1],
        ["a9", 1],
      ],
    );
  });

  test("drops an attachment that no longer exists", () => {
    const shown = withSubmittedValues(stored, { collection_attachments: [{ collection_id: "deleted" }] }, lookups);

    assert.deepEqual(shown.collections, []);
  });

  test("leaves the stored entry untouched", () => {
    withSubmittedValues(stored, { title: "Changed", tag_ids: [] }, lookups);

    assert.deepEqual([stored.title, stored.tags], ["October newsletter", ["news"]]);
  });
});
