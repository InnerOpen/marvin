// What an entry's media slot shows (entryMedia.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { extraSound, leadAsset, thumbOf } from "./entryMedia.ts";

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

describe("files that are not pictures", () => {
  const file = (mimeType) => ({ role: "transcript", publicUrl: "https://a/file", mimeType });

  test("a text, JSON, PDF or video file is no thumbnail: it would be a broken picture", () => {
    for (const type of ["text/plain", "application/json", "application/pdf", "video/mp4"]) assert.equal(thumbOf([file(type)], "x"), null, type);
  });

  test("an entry with a transcript and a picture shows the picture, wherever the transcript sits", () => {
    const picture = { role: "cover", publicUrl: "https://a/p.png", mimeType: "image/png", altText: "p" };
    const thumb = thumbOf([file("text/plain"), picture], "x");
    assert.deepEqual([thumb?.kind, thumb?.url], ["image", "https://a/p.png"]);
    assert.equal(leadAsset([file("text/plain"), picture]), picture);
  });

  test("with only files, the lead is still the first (for what else reads it), and there is no thumbnail", () => {
    const first = file("text/plain");
    assert.equal(leadAsset([first, file("application/json")]), first);
  });
});

describe("extraSound", () => {
  const sample = { role: "voice_sample", publicUrl: "https://a/sarah.mp3", mimeType: "audio/mpeg", altText: null };

  test("an actor's voice sample rides along with the picture that leads", () => {
    const got = extraSound([picture, sample], "Sarah");
    assert.deepEqual([got?.kind, got?.url], ["audio", "https://a/sarah.mp3"]);
  });

  test("there is none when the entry has no recording", () => {
    assert.equal(extraSound([picture], "Sarah"), null);
  });

  test("there is none when the recording already leads (the slot plays it)", () => {
    assert.equal(extraSound([take, picture], "Your feast."), null);
  });

  test("there is none when the entry has no assets at all", () => {
    assert.equal(extraSound([], "x"), null);
    assert.equal(extraSound(undefined, "x"), null);
  });
});
