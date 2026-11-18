// After a recording the dialog hides the live preview and shows the take. The stage's own video rule used to beat the generic
// hidden rule, so the hidden preview kept its place and pushed the take, with its play controls, out of view.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const source = readFileSync(new URL("../components/VideoRecorder.astro", import.meta.url), "utf8");

test("a hidden video in the recorder's stage is not displayed", () => {
  assert.match(source, /\.video-recorder \.vr-stage video\[hidden\]\s*\{\s*display:\s*none;?\s*\}/);
});

test("the hidden rule comes after the stage's video rule, so it wins", () => {
  const stage = source.indexOf(".video-recorder .vr-stage video {");
  const hidden = source.indexOf(".video-recorder .vr-stage video[hidden]");
  assert.ok(stage >= 0 && hidden > stage);
});
