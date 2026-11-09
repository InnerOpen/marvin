import test from "node:test";
import assert from "node:assert/strict";
import { acceptTokens, matchesAccept, uploadAccept } from "./assetAccept.ts";

test("nothing accepted means everything fits", () => {
  assert.equal(matchesAccept("", { mimeType: "image/png", name: "a.png" }), true);
  assert.equal(matchesAccept(undefined, { mimeType: null, name: "" }), true);
});

test("a wildcard matches the type, an exact type matches exactly, parameters are ignored", () => {
  assert.equal(matchesAccept("audio/*", { mimeType: "audio/webm;codecs=opus", name: "a" }), true);
  assert.equal(matchesAccept("audio/*", { mimeType: "image/png", name: "a" }), false);
  assert.equal(matchesAccept("application/pdf", { mimeType: "application/pdf", name: "x.pdf" }), true);
  assert.equal(matchesAccept("application/pdf", { mimeType: "application/msword", name: "x.doc" }), false);
  assert.equal(matchesAccept("text/html", { mimeType: "TEXT/HTML; charset=utf-8", name: "p" }), true);
});

test("an ending matches the name, and is the only way an asset of unknown type fits", () => {
  assert.equal(matchesAccept(".fountain,.txt", { mimeType: "application/octet-stream", name: "Story.FOUNTAIN" }), true);
  assert.equal(matchesAccept(".fountain", { mimeType: null, name: "story.txt" }), false);
  assert.equal(matchesAccept("application/pdf", { mimeType: null, name: "x.pdf" }), false);
});

test("several tokens: any one is enough", () => {
  assert.equal(matchesAccept("text/html,.html", { mimeType: "text/plain", name: "page.html" }), true);
  assert.deepEqual(acceptTokens(" Audio/* , .MP3 ,, "), ["audio/*", ".mp3"]);
});

test("the upload dialog takes the field's accept, else the usual kinds", () => {
  assert.equal(uploadAccept("application/pdf"), "application/pdf");
  assert.match(uploadAccept(""), /image\/\*/);
});
