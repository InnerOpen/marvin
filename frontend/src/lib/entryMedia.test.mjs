// What an entry's media slot shows (entryMedia.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { leadAsset, thumbOf } from "./entryMedia.ts";

const picture = { role: null, publicUrl: "https://a/x.png", mimeType: "image/png", altText: "A still" };
const take = { role: "audio", publicUrl: "https://a/line.mp3", mimeType: "audio/mpeg" };

describe("thumbOf", () => {
  test("a voice line's recording is audio, so the slot gets a play button, not a picture", () => {
    assert.deepEqual(thumbOf([take], "Your feast."), { kind: "audio", url: "https://a/line.mp3", alt: "Your feast.", focalPoint: undefined });
  });

  test("a picture stays a picture, with its alt text", () => {
    const t = thumbOf([picture], "Beat 04");
    assert.equal(t?.kind, "image");
    assert.equal(t?.alt, "A still");
  });

  test("the featured asset leads, whatever order the assets come in", () => {
    assert.equal(thumbOf([take, { ...picture, role: "featured" }], "x")?.kind, "image");
    assert.equal(leadAsset([take, { ...picture, role: "hero" }])?.role, "hero");
  });

  test("a line made again leads with its latest take, not the first one it ever had", () => {
    const older = { ...take, publicUrl: "https://a/take-1.mp3" };
    const newer = { ...take, publicUrl: "https://a/take-2.mp3" };
    assert.equal(leadAsset([older, newer])?.publicUrl, "https://a/take-2.mp3");
    assert.equal(thumbOf([older, newer], "x")?.url, "https://a/take-2.mp3");
    assert.equal(leadAsset([older, newer, { ...picture, role: "featured" }])?.role, "featured"); // a chosen picture still wins
  });

  test("an asset type that says nothing is treated as a picture, and no usable asset is no thumbnail", () => {
    assert.equal(thumbOf([{ publicUrl: "https://a/x" }], "x")?.kind, "image");
    assert.equal(thumbOf([{ role: "audio", mimeType: "audio/mpeg" }], "x"), null);
    assert.equal(thumbOf([], "x"), null);
    assert.equal(thumbOf(null, "x"), null);
  });
});
