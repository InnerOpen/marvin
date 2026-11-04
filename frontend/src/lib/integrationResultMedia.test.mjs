// The audio and pictures an action's result carries (integrationResultMedia.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { assetSlug, mediaExtension, mediaFile, mediaIn, sniffImageMime, withoutMediaBytes } from "./integrationResultMedia.ts";

const PNG = "iVBORw0KGgoAAAANSUhEUg";
const JPEG = "/9j/4AAQSkZJRg";
const MP3 = Buffer.from("ID3 a pretend take").toString("base64");

describe("mediaIn", () => {
  test("a speech result is one audio item with the details worth keeping", () => {
    const [item] = mediaIn({ audio_b64: MP3, mime: "audio/mpeg", duration_seconds: 1.07, characters: 11, voice_id: "v1", model: "m", usage: { x: 1 } });
    assert.equal(item.kind, "audio");
    assert.equal(item.mime, "audio/mpeg");
    assert.deepEqual(item.details, { duration_seconds: 1.07, characters: 11, voice_id: "v1", model: "m" });
  });

  test("audio with no mime, or a mime that isn't audio, is treated as mp3", () => {
    assert.equal(mediaIn({ audio_b64: MP3 })[0].mime, "audio/mpeg");
    assert.equal(mediaIn({ audio_b64: MP3, mime: "application/json" })[0].mime, "audio/mpeg");
    assert.equal(mediaIn({ audio_b64: MP3, mime: "audio/wav; codecs=1" })[0].mime, "audio/wav");
  });

  test("an images list and a top-level picture are both found, each typed from its bytes", () => {
    const found = mediaIn({ images: [{ image_b64: PNG }, { image_b64: JPEG }, { url: "https://x" }], image_b64: PNG });
    assert.deepEqual(found.map((m) => [m.kind, m.mime]), [["image", "image/png"], ["image", "image/jpeg"], ["image", "image/png"]]);
  });

  test("a result with no media, or no result, has none", () => {
    assert.deepEqual(mediaIn({ voices: [] }), []);
    assert.deepEqual(mediaIn(null), []);
    assert.deepEqual(mediaIn([{ audio_b64: MP3 }]), []);
    assert.deepEqual(mediaIn({ audio_b64: "" }), []);
  });
});

describe("withoutMediaBytes", () => {
  test("swaps each payload for its size and leaves the rest as it was", () => {
    const out = withoutMediaBytes({ audio_b64: MP3, mime: "audio/mpeg", images: [{ image_b64: PNG, revised_prompt: "p" }] });
    assert.match(out.audio_b64, /^\(\d+ KB, shown above\)$/);
    assert.equal(out.mime, "audio/mpeg");
    assert.match(out.images[0].image_b64, /shown above/);
    assert.equal(out.images[0].revised_prompt, "p");
  });

  test("does not change the result it was given", () => {
    const result = { audio_b64: MP3 };
    withoutMediaBytes(result);
    assert.equal(result.audio_b64, MP3);
  });
});

describe("files and names", () => {
  test("the file holds the decoded bytes, named with the right extension", async () => {
    const [item] = mediaIn({ audio_b64: MP3 });
    const file = mediaFile(item, "your-feast");
    assert.equal(file.name, "your-feast.mp3");
    assert.equal(file.type, "audio/mpeg");
    assert.equal(await file.text(), "ID3 a pretend take");
  });

  test("extensions and image sniffing", () => {
    assert.equal(mediaExtension("image/jpeg"), "jpg");
    assert.equal(mediaExtension("audio/x-odd"), "x-odd");
    assert.equal(sniffImageMime("UklGRabc"), "image/webp");
  });

  test("slugs are lowercase words, then the tail", () => {
    assert.equal(assetSlug("Synthesize speech!", "ab12cd34"), "synthesize-speech-ab12cd34");
    assert.equal(assetSlug("???", "ab12cd34"), "result-ab12cd34");
  });
});
