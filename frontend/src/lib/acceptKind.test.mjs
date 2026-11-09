import assert from "node:assert/strict";
import { test } from "node:test";
import { acceptKind, acceptsAudio, isKind } from "./acceptKind.ts";

test("a MIME pattern names its kind", () => {
  assert.equal(acceptKind("audio/*"), "audio");
  assert.equal(acceptKind("image/*"), "image");
  assert.equal(acceptKind("image/png, image/jpeg"), "image");
});

test("extensions name their kind, as a string or a list", () => {
  assert.equal(acceptKind(".mp3,.wav"), "audio");
  assert.equal(acceptKind([".MP3", ".m4a"]), "audio");
  assert.equal(acceptKind([".fountain", ".txt"]), "file");
});

test("an empty or mixed accept is any file", () => {
  assert.equal(acceptKind(undefined), "file");
  assert.equal(acceptKind(""), "file");
  assert.equal(acceptKind("audio/*,image/*"), "file");
});

test("any audio part takes a recording", () => {
  assert.equal(acceptsAudio("audio/*,image/*"), true);
  assert.equal(acceptsAudio([".txt", ".mp3"]), true);
  assert.equal(acceptsAudio("image/*"), false);
  assert.equal(acceptsAudio(undefined), false);
});

test("a file is of a kind by its type or, when the type is vague, its name", () => {
  assert.equal(isKind({ type: "audio/mpeg", name: "take.mp3" }, "audio"), true);
  assert.equal(isKind({ type: "video/webm", name: "take.webm" }, "audio"), true);
  assert.equal(isKind({ type: "", name: "take.wav" }, "audio"), true);
  assert.equal(isKind({ type: "image/png", name: "face.png" }, "audio"), false);
  assert.equal(isKind({ type: "audio/mpeg", name: "take.mp3" }, "image"), false);
  assert.equal(isKind({ type: "text/plain", name: "a.txt" }, "file"), true);
});
