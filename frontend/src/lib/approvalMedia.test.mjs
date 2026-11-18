// What an approval's media URL is (approvalMedia.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { isAudioUrl, isVideoUrl, mediaKind } from "./approvalMedia.ts";

describe("isAudioUrl", () => {
  test("a recorded take is audio, whatever the case or query string", () => {
    assert.equal(isAudioUrl("https://assets.example.com/ws/cook-line.mp3"), true);
    assert.equal(isAudioUrl("https://assets.example.com/ws/Line.WAV?sig=abc#t=2"), true);
    assert.equal(isAudioUrl("/assets/ws/take.m4a"), true);
  });

  test("a picture, a missing URL or an extension in the middle is not", () => {
    assert.equal(isAudioUrl("https://assets.example.com/ws/still.png"), false);
    assert.equal(isAudioUrl("https://assets.example.com/ws/notes.mp3.txt"), false);
    assert.equal(isAudioUrl(null), false);
    assert.equal(isAudioUrl(""), false);
  });
});

describe("isVideoUrl and mediaKind", () => {
  test("a generated moving shot is video, whatever the case or query string", () => {
    assert.equal(isVideoUrl("https://assets.example.com/ws/slow-push-in.mp4"), true);
    assert.equal(isVideoUrl("/assets/ws/Shot.MOV?sig=abc"), true);
    assert.equal(mediaKind("/assets/ws/shot.m4v#t=1"), "video");
  });

  test("a recorded take (webm too) stays audio, and anything else is a picture", () => {
    assert.equal(mediaKind("/assets/ws/take.webm"), "audio");
    assert.equal(mediaKind("/assets/ws/line.mp3"), "audio");
    assert.equal(mediaKind("/assets/ws/still.png"), "image");
    assert.equal(mediaKind(null), "image");
    assert.equal(isVideoUrl("/assets/ws/notes.mp4.txt"), false);
  });
});
