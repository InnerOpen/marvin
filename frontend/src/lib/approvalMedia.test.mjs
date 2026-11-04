// What an approval's media URL is (approvalMedia.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { isAudioUrl } from "./approvalMedia.ts";

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
